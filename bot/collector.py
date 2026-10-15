# -*- coding: utf-8 -*-
"""collector — the actual job-gathering pipeline: fetching every provider's feed for every
profile's keywords, running each item through matching.evaluate(), merging cross-site duplicates,
and (run_once) deciding which of those matches are genuinely new, queuing them during quiet
hours, and pushing the rest. LAST_RUN_STATS (read by bot.commands.build_stats_text()) is set
here, at the end of every real (non-dry) run_once() call.

Sixth extraction step of jobbot.py's split into focused modules.
"""
import time
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # noqa: BLE001  (Python < 3.9 — quiet hours just won't apply)
    ZoneInfo = None

from .i18n import t
from .config import MAX_AGE_DAYS, FIRST_RUN_LIMIT
from .logutil import log
from .sources import PROVIDERS
from .telegram_api import tg_chat, send_telegram_plain
from .matching import normalize_title, desc_fingerprint, find_duplicate_posting, job_id, evaluate, is_priority
from .state import load_state, save_state, mark_seen, mark_seen_silent, _seen_pub, get_setting, get_profiles
from .notify import notify, send_one, serialize_rec, deserialize_rec  # noqa: F401  (re-exported for jobbot.py)
from .runtime import TZ_NAME, REOPEN_GAP_SEC, FEED_FAIL_THRESHOLD, PUSH_THROTTLE_SEC

# Populated by run_once() after every real (non-dry) run — what /stats' "last run" section
# reads (via bot.commands, as `collector.LAST_RUN_STATS` — a live module attribute, not a
# snapshot import). None until the first run completes (e.g. brand new process, or still
# mid-startup).
LAST_RUN_STATS = None

# url -> how many consecutive runs have failed in a row; url -> already alerted about this failure
_feed_fail_streak = {}
_feed_fail_alerted = set()


def _note_feed_ok(url, src):
    if _feed_fail_streak.get(url) and url in _feed_fail_alerted:
        send_telegram_plain(tg_chat(), t("feed_recovered", src=src, url=url))
    _feed_fail_streak[url] = 0
    _feed_fail_alerted.discard(url)


def _note_feed_fail(url, src):
    if FEED_FAIL_THRESHOLD <= 0:
        return
    n = _feed_fail_streak.get(url, 0) + 1
    _feed_fail_streak[url] = n
    if n >= FEED_FAIL_THRESHOLD and url not in _feed_fail_alerted:
        _feed_fail_alerted.add(url)
        send_telegram_plain(
            tg_chat(),
            t("feed_failing", src=src, n=n, url=url),
        )


def _collect_item(found, label, prof, must_text, item, src, counts):
    if not item["link"]:
        counts["no_link"] = counts.get("no_link", 0) + 1
        return
    meta, reason = evaluate(prof, must_text, item)
    if meta is None:
        counts[reason] = counts.get(reason, 0) + 1
        return
    jid = job_id(item["link"])
    # Besides the general AI-agentic heuristic (is_priority): for Embedded — Lviv/remote
    # is also priority, and for iOS — always priority (regardless of location).
    priority = (
        is_priority(item["title"], item["desc"])
        or meta.get("location_tag") == "lviv_remote"
        or prof["resume_key"] == "iOS"
    )
    rec = found.setdefault(jid, {"item": item, "src": src, "labels": [], "meta": meta,
                                  "resume_key": prof["resume_key"],
                                  "priority": priority})
    if label not in rec["labels"]:
        rec["labels"].append(label)


def collect():
    """Returns ({id: {item, src, labels, meta, resume_key}}, counts) — jobs matching ≥1 profile,
    plus a breakdown of how many raw feed items were rejected and why (see evaluate()'s reason
    strings) — this is what /stats' "last run" section is built from. Loops every profile's
    "keywords" against every active provider in sources.PROVIDERS (DOU/Djinni are always active;
    Jooble/RemoteOK/Work.ua only when their /set source_* toggle is on) — see sources/__init__.py
    for what a provider is and how to add one."""
    found = {}
    fetched = {}
    counts = {}
    for label, prof in get_profiles().items():
        for keyword, must_text in prof.get("keywords", []):
            for provider in PROVIDERS:
                if provider.setting_name and not get_setting(provider.setting_name):
                    continue
                cache_key = f"{provider.name}:{keyword}"
                if cache_key not in fetched:
                    try:
                        fetched[cache_key] = provider.fetch(keyword)
                        _note_feed_ok(cache_key, provider.name)
                    except Exception as e:  # noqa: BLE001
                        log(f"✗ {provider.name} {keyword}: {e}")
                        fetched[cache_key] = []
                        _note_feed_fail(cache_key, provider.name)
                for item in fetched[cache_key]:
                    _collect_item(found, label, prof, must_text, item, provider.name, counts)
    return dedup_cross_site(found), counts


def dedup_cross_site(found):
    """If the same job was found on both DOU and Djinni (identical normalized title), merge it
    into one record instead of two separate pushes."""
    groups = {}
    for jid, rec in found.items():
        key = normalize_title(rec["item"]["title"])
        groups.setdefault(key, []).append(jid)
    for jids in groups.values():
        if len(jids) < 2:
            continue
        # DOU has a direct "Apply" button — keep it as the primary record, if present
        jids_sorted = sorted(jids, key=lambda j: 0 if j.startswith("dou:") else 1)
        primary = jids_sorted[0]
        rec = found[primary]
        for other_jid in jids_sorted[1:]:
            other = found.pop(other_jid, None)
            if not other:
                continue
            for lbl in other["labels"]:
                if lbl not in rec["labels"]:
                    rec["labels"].append(lbl)
            if other["src"] not in rec["src"].split(" + "):
                rec["src"] = rec["src"] + " + " + other["src"]
            rec["priority"] = rec["priority"] or other["priority"]
            rec.setdefault("dup_ids", []).append(other_jid)
    return found


def is_quiet_now():
    """Whether it's currently quiet hours (don't push, queue instead)."""
    if ZoneInfo is None:
        return False
    start, end = get_setting("quiet_hours_start"), get_setting("quiet_hours_end")
    if start == end:
        return False
    try:
        tz = ZoneInfo(TZ_NAME)
    except Exception:  # noqa: BLE001  (no tzdata etc. — better without quiet hours than crashing)
        return False
    hour = datetime.now(tz).hour
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # window crossing midnight, e.g. 22..6


def run_once(dry=False):
    global LAST_RUN_STATS
    st = load_state()
    found, filter_counts = collect()
    now = datetime.now(timezone.utc)
    fresh = []
    for jid, rec in found.items():
        pub = rec["item"]["pub"]
        if pub and now - pub > timedelta(days=MAX_AGE_DAYS):
            if jid not in st["seen"]:
                mark_seen_silent(st, jid, rec, t("reason_too_old", days=MAX_AGE_DAYS))
                filter_counts["too_old"] = filter_counts.get("too_old", 0) + 1
            continue
        seen_entry = st["seen"].get(jid)
        if seen_entry is None:
            when = find_duplicate_posting(st, rec["item"]["desc"])
            if when:
                mark_seen_silent(st, jid, rec, t("reason_duplicate_posting", when=when))
                filter_counts["duplicate_posting"] = filter_counts.get("duplicate_posting", 0) + 1
                continue
            fresh.append((jid, rec))
        else:
            seen_pub = _seen_pub(seen_entry)
            cur_pub = pub.timestamp() if pub else None
            if seen_pub and cur_pub and cur_pub - seen_pub > REOPEN_GAP_SEC:
                # same vacancy id, but the recruiter bumped pubDate — DOU/Djinni's way of
                # signaling "this is open again", not a feed glitch. Push it again instead of
                # treating "already in seen" as final.
                rec["reopened"] = True
                fresh.append((jid, rec))
                filter_counts["reopened"] = filter_counts.get("reopened", 0) + 1
            else:
                filter_counts["already_seen"] = filter_counts.get("already_seen", 0) + 1
    # priority jobs (AI agentic / Claude Code etc.) go first in the batch; within a group — oldest to newest
    fresh.sort(key=lambda x: (0 if x[1]["priority"] else 1, x[1]["item"]["pub"] or now))

    first_run = not st.get("initialized")
    if first_run and len(fresh) > FIRST_RUN_LIMIT:
        for jid, rec in fresh[:-FIRST_RUN_LIMIT]:
            mark_seen_silent(st, jid, rec, t("reason_first_run_limit", limit=FIRST_RUN_LIMIT))
            filter_counts["first_run_limit"] = filter_counts.get("first_run_limit", 0) + 1
        fresh = fresh[-FIRST_RUN_LIMIT:]

    quiet = (not dry) and is_quiet_now()
    queued = st.get("queued", [])

    # quiet hours just ended and something built up overnight — send the morning batch first
    flushed = 0
    if not quiet and queued and not dry:
        send_telegram_plain(tg_chat(), t("overnight_digest_header", n=len(queued)))
        for i, d in enumerate(queued):
            try:
                qjid, qrec = deserialize_rec(d)
            except Exception as e:  # noqa: BLE001
                log("✗ deserialize_rec:", e)
                continue
            if i:
                time.sleep(PUSH_THROTTLE_SEC)
            if send_one(qjid, qrec, dry, st):
                flushed += 1
        queued = []
        st["queued"] = []

    sent = 0
    for i, (jid, rec) in enumerate(fresh):
        if quiet:
            queued.append(serialize_rec(jid, rec))
            mark_seen(st, jid, rec)
            continue
        if i and not dry:
            time.sleep(PUSH_THROTTLE_SEC)
        if send_one(jid, rec, dry, st):
            sent += 1
    if quiet and not dry:
        st["queued"] = queued

    if not dry:
        st["initialized"] = True
        save_state(st)
    extra = f", queued (quiet hours): {len(queued)}" if quiet else ""
    extra += f", morning digest: {flushed}" if flushed else ""
    log(f"matches: {len(found)}, new: {len(fresh)}, sent: {sent}{extra}")
    if not dry:
        LAST_RUN_STATS = {
            "ts": time.time(), "found": len(found), "new": len(fresh), "sent": sent,
            "filtered": filter_counts,
        }
