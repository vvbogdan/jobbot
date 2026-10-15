# -*- coding: utf-8 -*-
"""state — the bot's one persistence layer: state.json itself (local file or Firebase, picked
transparently), the /set-able settings schema, and the search-profile CRUD that backs /profiles
and /addprofile. Everything here either reads/writes the state dict or derives text from it —
nothing here sends a Telegram message or talks to any API other than Firebase's. The interactive
wizard that walks someone through /addprofile (and sends the Telegram prompts along the way)
stays in jobbot.py; it calls build_profile_from_wizard()/add_profile() here once it has an
answer for every step.

Third extraction step of jobbot.py's split into focused modules (after telegram_api.py/
logutil.py, then matching.py) — see README/commit history for the rest of the plan.
"""
import html
import json
import os
import re
import threading
import time
import urllib.parse
import zlib
from pathlib import Path

from . import firebase_store
from .logutil import log
from .i18n import t
from .config import PROFILES, SENIOR_WORDS
from .matching import DEDUP_FINGERPRINT_DAYS

STATE_FILE = Path(os.environ.get("JOBBOT_STATE", "state.json"))
STATE_LOCK = threading.Lock()

JOBS_CACHE_DAYS = 14       # how many days to keep a job's full text for the "resume" button
SEEN_RETENTION_DAYS = 120  # pure memory cap — how long a job id is kept in "seen" at all before
                            # it's pruned from state.json. The actual "recruiter reopened this
                            # posting" detection doesn't wait on this (see jobbot.py's
                            # REOPEN_GAP_SEC); this is only the outer bound for how long
                            # state.json remembers anything, so it doesn't grow forever.
SEEN_LOG_DAYS = int(os.environ.get("SEEN_LOG_DAYS", "14"))  # how many days to keep the silent-seen log

# ───────────────────────── STATE (state.json) ─────────────────────────

# In-memory cache for the whole state — load_state() used to hit disk on every single call
# (cheap for a local file, but with --loop 60 that's a full read+write of the whole state every
# minute, which would blow through any free remote DB's bandwidth quota in days). Now the state
# lives in this one process-wide dict for the life of the process: load_state() fetches it once
# (from Firebase if configured, else the local file) and every caller afterwards gets the SAME
# object — mutating it in place, the way state_update()/run_once() already do — so nothing needs
# to change at any call site. save_state() then only actually writes out (to Firebase, or the
# local file if Firebase isn't configured) when the content genuinely changed since the last
# successful write, via the _last_saved_json comparison below.
_cached_state = None
_last_saved_json = None


def load_state():
    global _cached_state
    if _cached_state is not None:
        return _cached_state
    with STATE_LOCK:
        if _cached_state is not None:  # another thread filled it while we were waiting
            return _cached_state
        st = None
        if firebase_store.enabled():
            try:
                st = firebase_store.get_state()
            except Exception as e:  # noqa: BLE001
                log("✗ firebase load (falling back to local file):", e)
        if not isinstance(st, dict):
            try:
                st = json.loads(STATE_FILE.read_text())
            except Exception:  # noqa: BLE001
                st = None
        if not isinstance(st, dict):
            st = {"seen": {}, "jobs": {}, "initialized": False, "tg_offset": 0}
        _cached_state = st
        return _cached_state


def _firebase_active():
    """Whether state should actually go to Firebase right now: the two env vars are set AND the
    "use_firebase" setting (/set use_firebase 0|1, stored in state.json, default on) hasn't been
    flipped off. Only save_state() consults the setting — load_state()'s very first bootstrap
    call always tries Firebase when env-configured instead, since there's no state loaded yet to
    read a stored override from. Flipping this off takes effect on the very next save (routes to
    the local file instead); flipping it back on pushes everything that changed in the meantime
    up to Firebase on the next change. It does NOT survive a Render restart by itself — Render
    wipes the local file too, so a real restart falls back to whatever's in Firebase (or the env
    vars being unset entirely, for a lasting disable — see README section 7b)."""
    return firebase_store.enabled() and bool(get_setting("use_firebase"))


def save_state(st):
    global _last_saved_json
    cutoff = time.time() - SEEN_RETENTION_DAYS * 86400
    st["seen"] = {k: v for k, v in st["seen"].items() if _seen_ts(v) > cutoff}
    jcut = time.time() - JOBS_CACHE_DAYS * 86400
    st["jobs"] = {k: v for k, v in st.get("jobs", {}).items() if v.get("ts", 0) > jcut}
    ecut = time.time() - 60 * 86400
    st["events"] = [e for e in st.get("events", []) if e.get("ts", 0) > ecut]
    scut = time.time() - SEEN_LOG_DAYS * 86400
    st["silent_seen_log"] = [e for e in st.get("silent_seen_log", []) if e.get("ts", 0) > scut]
    dcut = time.time() - DEDUP_FINGERPRINT_DAYS * 86400
    st["desc_fingerprints"] = {
        k: v for k, v in st.get("desc_fingerprints", {}).items() if v.get("ts", 0) > dcut
    }
    new_json = json.dumps(st, ensure_ascii=False, sort_keys=True)
    if new_json == _last_saved_json:
        return  # nothing actually changed since the last successful save — skip the write
    if _firebase_active():
        try:
            firebase_store.put_state(st)
            _last_saved_json = new_json
            return
        except Exception as e:  # noqa: BLE001
            # Keep going — the in-memory state (and this run's results) aren't lost, just not
            # yet persisted remotely. Writing locally too so at least THIS process instance has
            # it on disk. Deliberately NOT updating _last_saved_json, so the next save_state()
            # call retries the Firebase write even if nothing else changes in the meantime.
            log("✗ firebase save (will retry next time; writing locally for now):", e)
            STATE_FILE.write_text(new_json)
            return
    STATE_FILE.write_text(new_json)
    _last_saved_json = new_json


def state_update(fn):
    """Atomically: load state, let fn(st) mutate it, save it."""
    with STATE_LOCK:
        st = load_state()
        result = fn(st)
        save_state(st)
        return result


# ───────────────────────── seen bookkeeping ─────────────────────────

def _seen_ts(entry):
    """st["seen"] values used to be a bare float (time.time() of when we marked it). Now they're
    {"ts":, "pub":} so a later reopen-bump can be detected (see jobbot.py's REOPEN_GAP_SEC) —
    this reads the wall-clock half back out regardless of which shape is on disk (old local
    state.json / old Firebase data, or one that just got migrated)."""
    return entry.get("ts", 0) if isinstance(entry, dict) else (entry or 0)


def _seen_pub(entry):
    """The job's own pubDate (epoch seconds) at the time we last marked it seen, or None if we
    don't know (legacy entry, or the feed had no pubDate) — in which case reopen-bump detection
    simply can't fire for this id until it's marked again under the new shape."""
    return entry.get("pub") if isinstance(entry, dict) else None


def mark_seen(st, jid, rec=None):
    pub = (rec or {}).get("item", {}).get("pub")
    pub_epoch = pub.timestamp() if pub else None
    ts = time.time()
    st["seen"][jid] = {"ts": ts, "pub": pub_epoch}
    for other in (rec or {}).get("dup_ids", []):
        st["seen"][other] = {"ts": ts, "pub": pub_epoch}


def mark_seen_silent(st, jid, rec, reason):
    """Like mark_seen, but also leaves a trace (title/link/reason) in silent_seen_log — so /seen
    can show which jobs went to "seen" without any push, and it's possible to double-check this
    wasn't a mistake (e.g. too old, or trimmed by the first-run limit)."""
    mark_seen(st, jid, rec)
    st.setdefault("silent_seen_log", []).append({
        "jid": jid,
        "title": rec["item"]["title"],
        "link": rec["item"]["link"],
        "reason": reason,
        "ts": time.time(),
    })


# ───────────────────────── SETTINGS (stored in state.json → included in backups) ─────────────────────────
# These keys can be changed right from Telegram (/set <key> <value>) without redeploying on
# Render — the value is written into state.json under "settings", so it survives a restart and
# is included in backups. The default is the same value that used to come only from an env var
# (which still works as the initial default).
SETTINGS_SCHEMA = {
    "reminder_hours": (float, float(os.environ.get("REMINDER_HOURS", "20")),
                        t("setting_desc_reminder_hours")),
    "quiet_hours_start": (int, int(os.environ.get("QUIET_HOURS_START", "1")),
                           t("setting_desc_quiet_hours_start")),
    "quiet_hours_end": (int, int(os.environ.get("QUIET_HOURS_END", "7")),
                         t("setting_desc_quiet_hours_end")),
    "stats_period_days": (int, int(os.environ.get("STATS_PERIOD_DAYS", "14")),
                           t("setting_desc_stats_period_days")),
    "backup_interval_hours": (float, float(os.environ.get("BACKUP_INTERVAL_HOURS", "24")),
                               t("setting_desc_backup_interval_hours")),
    "pending_list_limit": (int, int(os.environ.get("PENDING_LIST_LIMIT", "20")),
                            t("setting_desc_pending_list_limit")),
    "pending_cards_limit": (int, int(os.environ.get("PENDING_CARDS_LIMIT", "40")),
                             t("setting_desc_pending_cards_limit")),
    "seen_list_limit": (int, int(os.environ.get("SEEN_LIST_LIMIT", "20")),
                         t("setting_desc_seen_list_limit")),
    "source_jooble": (int, 0, t("setting_desc_source_jooble")),
    "source_remoteok": (int, 0, t("setting_desc_source_remoteok")),
    "source_workua": (int, 0, t("setting_desc_source_workua")),
    "use_firebase": (int, 1, t("setting_desc_use_firebase")),
}

# Settings that are strictly on/off (0 or 1), not an arbitrary number — set_setting() below
# rejects anything else for these.
BOOL_SETTINGS = {"source_jooble", "source_remoteok", "source_workua", "use_firebase"}


def get_setting(name):
    """The current value of a setting: whatever someone set via /set (stored in state.json),
    otherwise the default (previously — env var only)."""
    typ, default, _ = SETTINGS_SCHEMA[name]
    st = load_state()
    val = st.get("settings", {}).get(name)
    return val if val is not None else default


def set_setting(name, raw_value):
    """Changes a setting and immediately writes it to state.json (so it's included in the next
    backup too). Returns (True, new_value) or (False, error_text)."""
    if name not in SETTINGS_SCHEMA:
        known = ", ".join(sorted(SETTINGS_SCHEMA))
        return False, t("set_unknown_key", name=name, known=known)
    typ, _, _ = SETTINGS_SCHEMA[name]
    try:
        value = typ(raw_value)
    except (TypeError, ValueError):
        return False, t("set_not_a_number", value=raw_value)
    if name in ("quiet_hours_start", "quiet_hours_end") and not (0 <= value <= 24):
        return False, t("set_out_of_range_0_24")
    if name in BOOL_SETTINGS and value not in (0, 1):
        return False, t("set_out_of_range_0_1")
    if name != "reminder_hours" and name != "backup_interval_hours" and value < 0:
        return False, t("set_must_be_nonnegative")

    def _set(st):
        st.setdefault("settings", {})[name] = value
    state_update(_set)
    return True, value


def build_settings_text():
    st = load_state()
    overrides = st.get("settings", {})
    lines = [t("settings_header"), ""]
    for name, (typ, default, desc) in SETTINGS_SCHEMA.items():
        cur = overrides.get(name, default)
        mark = t("settings_changed_mark") if name in overrides else ""
        lines.append(t("settings_line", name=name, value=cur, mark=mark, desc=html.escape(desc)))
    return "\n".join(lines)


# ───────────────────────── PROFILES (stored in state.json → included in backups) ─────────────────────────
# Profiles started out as a static dict in config.py; now they live in state.json (so they're
# backed up/restored with everything else) and can be added/removed from Telegram with
# /addprofile and /profiles — no code editing or redeploy needed. config.PROFILES is only the
# one-time seed for a brand-new state.json (first-ever run, or after a full restore from a
# backup made before this feature existed).

def _derive_keywords_from_old_feeds(prof):
    """Migrates a profile saved before the provider refactor (old shape: "feeds" —
    [(src, url, must_text), ...] — and no "keywords" at all) by recovering the keyword from
    each feed's own URL. Wizard-built profiles already carry "feed_keywords" regardless of
    age, so that's tried first and covers them with no guessing involved."""
    if prof.get("feed_keywords"):
        return [(kw, None) for kw in prof["feed_keywords"]]
    recovered = {}
    for feed in prof.get("feeds", []):
        if len(feed) != 3:
            continue
        _src, url, must_text = feed
        m = re.search(r"[?&](?:category|primary_keyword)=([^&]+)", url)
        if not m:
            continue
        kw = urllib.parse.unquote_plus(m.group(1))
        if kw not in recovered or (must_text and not recovered[kw]):
            recovered[kw] = must_text
    return list(recovered.items())


def _repair_truncated_keyword_pairs(profiles):
    """Firebase RTDB treats a null value as "delete this path" — including a null that's an
    element of a list, so a (keyword, None) pair written before firebase_store.py learned to
    guard against this came back as a 1-element ["keyword"] list, breaking every
    "for keyword, must_text in ..." unpack below (and in collect()) with "not enough values to
    unpack". firebase_store.py now encodes None safely so this won't recur, but data already
    sitting in Firebase (or an old local state.json saved during the window before that fix)
    still needs patching back to 2-element pairs once. Returns True if anything was patched."""
    changed = False
    for prof in profiles.values():
        kw_list = prof.get("keywords")
        if not isinstance(kw_list, list):
            continue
        for i, pair in enumerate(kw_list):
            if isinstance(pair, (list, tuple)) and len(pair) < 2:
                kw_list[i] = [pair[0] if pair else None, None]
                changed = True
            elif not isinstance(pair, (list, tuple)):
                kw_list[i] = [pair, None]
                changed = True
    return changed


def _sync_keywords_from_config(profiles):
    """Keeps a profile's "keywords" in sync with config.PROFILES (matched by profile name) —
    adds any keyword config.py has that state.json doesn't yet, AND refreshes must_text for a
    keyword both already have, so editing config.py (a new keyword, or tightening an existing
    must_text regex — e.g. fixing a filter that was letting the wrong jobs through) and
    redeploying is enough, with no manual state.json edit and no /addprofile round-trip. Never
    removes or reorders a keyword, and never touches a profile whose name isn't in
    config.PROFILES (e.g. one a person built with /addprofile) — config.py can only add to /
    correct a profile it already owns, never invent or delete one. Returns True if it changed
    anything, so the caller knows whether to persist."""
    changed = False
    for name, cfg_prof in PROFILES.items():
        prof = profiles.get(name)
        if not prof:
            continue
        kw_list = prof.setdefault("keywords", [])
        by_kw = {kw: i for i, (kw, _must_text) in enumerate(kw_list)}
        for kw, must_text in cfg_prof.get("keywords", []):
            if kw not in by_kw:
                kw_list.append([kw, must_text])
                by_kw[kw] = len(kw_list) - 1
                changed = True
            elif kw_list[by_kw[kw]][1] != must_text:
                kw_list[by_kw[kw]][1] = must_text
                changed = True
    return changed


def get_profiles():
    """The live set of profiles (state.json), seeding it from config.PROFILES on first use."""
    st = load_state()
    if "profiles" not in st:
        # json round-trip: a plain deep copy, and exactly the shape these will have in state.json
        # anyway once saved (tuples -> lists), so later code never has to care which one it got.
        seeded = json.loads(json.dumps(PROFILES))

        def _seed(st):
            st.setdefault("profiles", seeded)
        state_update(_seed)
        st = load_state()

    profiles = st["profiles"]
    # Migrate any profile saved before the provider refactor (section above) — collect() only
    # reads "keywords" now, so a profile restored from an old backup (or already sitting in a
    # live state.json from before today) would otherwise silently stop matching anything.
    if any("keywords" not in prof for prof in profiles.values()):
        for prof in profiles.values():
            prof.setdefault("keywords", _derive_keywords_from_old_feeds(prof))

        def _migrate(st):
            st["profiles"] = profiles
        state_update(_migrate)

    if _repair_truncated_keyword_pairs(profiles):
        def _repair(st):
            st["profiles"] = profiles
        state_update(_repair)

    if _sync_keywords_from_config(profiles):
        def _sync(st):
            st["profiles"] = profiles
        state_update(_sync)
    return profiles


def build_profile_from_wizard(data):
    """Turns the plain-language answers collected by the /addprofile wizard (keywords, not
    regex) into a profile dict in the same shape as config.PROFILES — so get_profiles()/collect()/
    evaluate() don't need to know whether a profile came from config.py or from the wizard."""
    def _kw_re(keywords):
        parts = [re.escape(k.strip()) for k in keywords if k.strip()]
        return r"\b(" + "|".join(parts) + r")\b" if parts else None

    exclude_parts = list(data.get("exclude_keywords") or [])
    exclude_title = _kw_re(exclude_parts)
    if data.get("exclude_senior"):
        exclude_title = SENIOR_WORDS if not exclude_title else f"(?:{exclude_title})|(?:{SENIOR_WORDS})"

    return {
        "resume_key": data["resume_key"],
        # one list of keywords, queried against every active provider (sources.PROVIDERS) —
        # DOU/Djinni always, Jooble/RemoteOK/Work.ua only when their /set source_* is on
        "keywords": [(kw, None) for kw in data["feed_keywords"]],
        "must_title": _kw_re(data.get("must_keywords") or []),
        "exclude_title": exclude_title,
        "max_years": data.get("max_years"),
        # kept only for a readable /profiles listing — collect()/evaluate() use the fields above
        "feed_keywords": data["feed_keywords"],
        "must_keywords": data.get("must_keywords") or [],
        "exclude_keywords": exclude_parts,
        "exclude_senior": bool(data.get("exclude_senior")),
    }


def add_profile(label, profile):
    def _add(st):
        st.setdefault("profiles", get_profiles())[label] = profile
    state_update(_add)


def delete_profile_by_crc(crc):
    """/profiles delete buttons reference a profile by crc32(label) rather than the raw label
    (keeps callback_data short and avoids escaping issues with emoji/spaces in labels)."""
    removed = {}

    def _del(st):
        profiles = st.setdefault("profiles", get_profiles())
        for label in list(profiles):
            if str(zlib.crc32(label.encode())) == crc:
                removed["label"] = profiles.pop(label)
                removed["name"] = label
                break
    state_update(_del)
    return removed.get("name")


def build_profiles_text():
    profiles = get_profiles()
    if not profiles:
        return t("profiles_empty")
    lines = [t("profiles_header", n=len(profiles))]
    for label, prof in profiles.items():
        lines.append(t("profiles_line", label=label, resume_key=prof.get("resume_key"),
                        n_keywords=len(prof.get("keywords", []))))
    return "\n".join(lines)


def profiles_keyboard():
    profiles = get_profiles()
    # One tap only arms the row (delprof_ask|) — it takes a second tap on the confirm button
    # (delprof|) to actually delete, so a stray/accidental tap on the list can't wipe a profile.
    rows = [[{"text": t("profiles_delete_btn", label=label),
              "callback_data": f"delprof_ask|{zlib.crc32(label.encode())}"}]
            for label in profiles]
    return {"inline_keyboard": rows} if rows else None
