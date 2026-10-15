# -*- coding: utf-8 -*-
"""commands — text/keyboard building and state mutations behind the bot's Telegram commands and
inline-keyboard interactions: /help, /stats, /pending, /seen, /skipped, the "pending checklist"
(mark applied/not-interested in place, with pagination), and setMyCommands registration.

Eighth extraction step of jobbot.py's split into focused modules.
"""
import html
import json
import time
from datetime import datetime

from .i18n import t
from .net import http
from .logutil import log
from .telegram_api import tg_token, send_telegram_plain
from .matching import apply_link, job_priority_and_location, job_badge, format_age
from .state import load_state, state_update, get_setting, build_settings_text, SEEN_LOG_DAYS
from .runtime import BOT_VERSION, PROCESS_STARTED, PUSH_THROTTLE_SEC
from . import collector  # read collector.LAST_RUN_STATS live (not a stale import-time snapshot)

# A persistent keyboard with buttons instead of typing commands by hand.
MAIN_MENU_KEYBOARD = {
    "keyboard": [
        [{"text": t("menu_stats")}, {"text": t("menu_pending")}],
        [{"text": t("menu_backup")}, {"text": t("menu_help")}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}

# Button text -> which command it means (the button sends its own text as a plain message).
BUTTON_TEXT_TO_COMMAND = {
    t("menu_stats"): "/stats",
    t("menu_pending"): "/pending",
    t("menu_backup"): "/backup",
    t("menu_help"): "/help",
}


def set_bot_commands():
    """Registers commands with Telegram so they show up in the "/" menu next to the input field."""
    token = tg_token()
    if not token:
        return
    commands = [
        {"command": "start", "description": t("cmd_start_desc")},
        {"command": "stats", "description": t("cmd_stats_desc", days=get_setting("stats_period_days"))},
        {"command": "pending", "description": t("cmd_pending_desc")},
        {"command": "seen", "description": t("cmd_seen_desc")},
        {"command": "skipped", "description": t("cmd_skipped_desc")},
        {"command": "backup", "description": t("cmd_backup_desc")},
        {"command": "settings", "description": t("cmd_settings_desc")},
        {"command": "profiles", "description": t("cmd_profiles_desc")},
        {"command": "addprofile", "description": t("cmd_addprofile_desc")},
    ]
    try:
        http(f"https://api.telegram.org/bot{token}/setMyCommands",
             data=json.dumps({"commands": commands}).encode(),
             headers={"Content-Type": "application/json"}, timeout=15, retries=1)
    except RuntimeError as e:  # noqa: BLE001
        log("✗ setMyCommands:", e)


def build_help_text():
    reminder_hours = get_setting("reminder_hours")
    stats_days = get_setting("stats_period_days")
    return t("help_text", reminder_hours=int(reminder_hours), stats_days=stats_days)


def build_stats_text():
    st = load_state()
    events = st.get("events", [])
    now = time.time()
    stats_period_days = get_setting("stats_period_days")
    period_ago = now - stats_period_days * 86400
    sent = [e for e in events if e.get("type") == "sent" and e["ts"] >= period_ago]
    applied = [e for e in events if e.get("type") == "applied" and e["ts"] >= period_ago]
    skipped = [e for e in events if e.get("type") == "skipped" and e["ts"] >= period_ago]

    by_profile = {}
    for e in sent:
        k = e.get("resume_key", "?")
        by_profile[k] = by_profile.get(k, 0) + 1

    period_label = t("stats_period_1_day") if stats_period_days == 1 else (
        t("stats_period_2_4_days", n=stats_period_days) if stats_period_days in (2, 3, 4)
        else t("stats_period_n_days", n=stats_period_days)
    )
    lines = [t("stats_header", period=period_label), t("stats_sent", n=len(sent))]
    for k, v in sorted(by_profile.items(), key=lambda x: -x[1]):
        lines.append(t("stats_by_profile_line", label=html.escape(k), n=v))
    rate = f" ({100 * len(applied) // len(sent)}%)" if sent else ""
    lines.append(t("stats_applied", n=len(applied), rate=rate))
    lines.append(t("stats_skipped", n=len(skipped)))

    jobs = st.get("jobs", {})
    pending = sum(1 for j in jobs.values() if not j.get("applied") and not j.get("not_interested"))
    lines.append(t("stats_pending", n=pending))

    # version/uptime — "did the latest fix actually deploy" without checking the Render
    # dashboard, and "last run" — why "N matches" didn't turn into new pushes, broken down by
    # filter reason, instead of that being a black box (see evaluate()/collect()).
    up = time.time() - PROCESS_STARTED
    uptime_str = t("stats_uptime_fmt", h=int(up // 3600), m=int((up % 3600) // 60))
    lines.append("")
    lines.append(t("stats_version_line", version=BOT_VERSION, uptime=uptime_str))
    last_run_stats = collector.LAST_RUN_STATS
    if last_run_stats is None:
        lines.append(t("stats_last_run_pending"))
    else:
        run_time = datetime.fromtimestamp(last_run_stats["ts"]).strftime("%H:%M:%S")
        lines.append(t("stats_last_run_header", time=run_time, found=last_run_stats["found"],
                       new=last_run_stats["new"], sent=last_run_stats["sent"]))
        filtered = last_run_stats["filtered"]
        if filtered:
            parts = [
                f"{t('filter_reason_' + reason)}: {n}"
                for reason, n in sorted(filtered.items(), key=lambda x: -x[1])
            ]
            lines.append(t("stats_last_run_filtered_prefix") + ", ".join(parts))
    return "\n".join(lines)


def build_pending_text(limit=None):
    """List of jobs the bot sent but that haven't been marked "Applied"/"Not interested" yet."""
    if limit is None:
        limit = get_setting("pending_list_limit")
    st = load_state()
    jobs = st.get("jobs", {})
    pending = [(jid, j) for jid, j in jobs.items()
               if not j.get("applied") and not j.get("not_interested")]
    if not pending:
        return t("no_pending")
    # Priority jobs (⭐ — AI-agentic or Embedded Lviv/remote) go first, the rest by time.
    pending.sort(key=lambda x: (0 if job_priority_and_location(x[1])[0] else 1, -x[1].get("ts", 0)))
    shown = pending[:limit]
    lines = [t("pending_header", n=len(pending))]
    now = time.time()
    for jid, j in shown:
        age_h = (now - j.get("ts", now)) / 3600
        link = html.escape(apply_link(j.get("link", "")))
        title = html.escape(job_badge(j) + j.get("title", "?")[:90])
        lines.append(t("pending_line", link=link, title=title, age=format_age(age_h)))
    if len(pending) > len(shown):
        lines.append(t("and_n_more", n=len(pending) - len(shown)))
    return "\n".join(lines)


def send_pending_cards(chat_id, limit=None):
    """Sends each pending job as its own message with buttons (like the original push) — so you
    can "click through" Applied/Not interested one by one, instead of just looking at a list of
    links in /pending."""
    if limit is None:
        limit = get_setting("pending_cards_limit")
    st = load_state()
    jobs = st.get("jobs", {})
    pending = [(jid, j) for jid, j in jobs.items()
               if not j.get("applied") and not j.get("not_interested")]
    if not pending:
        send_telegram_plain(chat_id, t("no_pending"))
        return
    pending.sort(key=lambda x: (0 if job_priority_and_location(x[1])[0] else 1, -x[1].get("ts", 0)))
    shown = pending[:limit]
    send_telegram_plain(chat_id, t("pending_cards_intro", n=len(shown)))
    now = time.time()
    for i, (jid, j) in enumerate(shown):
        if i:
            time.sleep(PUSH_THROTTLE_SEC)
        age_h = (now - j.get("ts", now)) / 3600
        title = html.escape((job_badge(j) + (j.get("title") or "?"))[:150])
        link = apply_link(j.get("link", ""))
        text = t("pending_card_text", title=title, age=format_age(age_h))
        buttons = [
            [{"text": t("btn_open_apply"), "url": link}],
            [
                {"text": t("btn_applied"), "callback_data": f"applied|{jid}"},
                {"text": t("btn_not_interested"), "callback_data": f"skip|{jid}"},
            ],
        ]
        send_telegram_plain(chat_id, text, buttons=buttons)
    if len(pending) > len(shown):
        send_telegram_plain(
            chat_id,
            t("pending_cards_overflow", n=len(pending) - len(shown), limit=limit),
        )


def checklist_keyboard_rows(items, mode="pending"):
    """items: a list of (jid, job-dict), ALREADY sorted by priority (job_priority_and_location)
    descending — the same way send_pending_checklist and send_skipped_checklist do. Builds TWO
    rows per job: a non-clickable title row (callback_data "noop", + a ⭐/🏙 badge) and, below it,
    one row of three action buttons — "✅ Цікаво" (mark_applied), "🔗 Відкрити" (open link), and
    either "🚫 Не цікаво" (mode="pending", mark_not_interested) or "↩️ Повернути" (mode="skipped",
    undo a previous "не цікаво"). Tapping any of the three removes both of that job's rows from
    the keyboard in place (see the pchk_applied|/pchk_skip|/pchk_undo| dispatch code) — no
    resend of the whole list. Before the priority group and before the rest, it inserts a
    non-clickable header row — so the priority group (Lviv/remote, iOS, AI) is visually
    separated from the rest, and you can immediately see whether there's anything there before
    going through the rest. Shared by /pending (mode="pending") and /skipped (mode="skipped",
    everything already marked "not interested" — "Повернути" sends it back to /pending)."""
    rows = []
    seen_priority_header = False
    seen_other_header = False
    for jid, j in items:
        priority, loc_tag = job_priority_and_location(j)
        if priority and not seen_priority_header:
            rows.append([{"text": t("checklist_priority_header"), "callback_data": "noop"}])
            seen_priority_header = True
        if not priority and not seen_other_header:
            rows.append([{"text": t("checklist_other_header"), "callback_data": "noop"}])
            seen_other_header = True
        badge = "⭐ " if priority else ("🏙 " if loc_tag == "kyiv" else "")
        title = (badge + (j.get("title") or "?"))[:60]
        rows.append([{"text": title, "callback_data": "noop"}])
        third_button = (
            {"text": t("checklist_btn_not_interested"), "callback_data": f"pchk_skip|{jid}"}
            if mode == "pending" else
            {"text": t("checklist_btn_undo"), "callback_data": f"pchk_undo|{jid}"}
        )
        rows.append([
            {"text": t("checklist_btn_applied"), "callback_data": f"pchk_applied|{jid}"},
            third_button,
            {"text": t("checklist_btn_open"), "url": apply_link(j.get("link", ""))},
        ])
    rows.append([{"text": t("checklist_btn_done"), "callback_data": "pchk_done"}])
    return rows


# Telegram rejects with "Bad Request: reply markup is too long" with no exact number in the
# docs — empirically it depends on the total content of the buttons (texts, urls, callback_data),
# not just the row count; once a second row per job appeared ("Open" + "Applied" instead of just
# "Open"), the limit started getting hit at as few as ~40-50 jobs together. We keep the
# serialized keyboard under a conservative byte budget with margin, not just under
# pending_cards_limit.
MAX_KEYBOARD_BYTES = 3000


def fit_checklist_to_telegram_limit(items, extra_rows_fn, mode="pending"):
    """Builds checklist_keyboard_rows(items, mode) + extra_rows_fn(items) (buttons that depend on
    the current set — e.g. "Dismiss all 'Other'" (N)) + "Done" at the end. If the serialized
    keyboard is too big for Telegram, it progressively drops jobs from the END of the list
    (items is already sorted priority-first, so the least-priority ones go first) and rebuilds,
    until it fits — so the user always sees a working list, just a shorter one, rather than an
    error. Returns (shown, rows) — shown can be shorter than items even if items was already
    within pending_cards_limit."""
    shown = list(items)
    while True:
        rows = checklist_keyboard_rows(shown, mode=mode)
        done_row = rows.pop()
        full_rows = rows + extra_rows_fn(shown) + [done_row]
        size = len(json.dumps({"inline_keyboard": full_rows}, ensure_ascii=False).encode("utf-8"))
        if size <= MAX_KEYBOARD_BYTES or len(shown) <= 1:
            return shown, full_rows
        shown = shown[:-1]


def send_pending_checklist(chat_id, limit=None, offset=0):
    """The main /pending view: a title row + a row of three action buttons ("✅ Цікаво",
    "🚫 Не цікаво", "🔗 Відкрити") per job, right in the same message — no separate step through
    /pending -> "Mark not interested". Tapping one removes just that job's two rows in place
    (editMessageReplyMarkup in the dispatch code), without resending the whole list.
    `offset` — which position in the sorted (priority-first) list this page starts from; when
    there are more jobs than fit in one message (the count limit or Telegram's byte limit), a
    "➡️ Next" button shows up at the bottom asking for the next page starting right where this
    one left off — without it you'd have to manually repeat /pending and scroll past the same
    start of the list every time. The last row switches to "card" mode (a separate message per
    job, same three actions)."""
    if limit is None:
        limit = get_setting("pending_cards_limit")
    st = load_state()
    jobs = st.get("jobs", {})
    pending = [(jid, j) for jid, j in jobs.items()
               if not j.get("applied") and not j.get("not_interested")]
    if not pending:
        send_telegram_plain(chat_id, t("no_pending"))
        return
    pending.sort(key=lambda x: (0 if job_priority_and_location(x[1])[0] else 1, -x[1].get("ts", 0)))
    offset = max(0, min(offset, len(pending) - 1))
    candidates = pending[offset:offset + limit]

    def extra_rows(cur_shown):
        others_count = sum(1 for jid, j in cur_shown if not job_priority_and_location(j)[0])
        rows = []
        if others_count:
            rows.append([{"text": t("checklist_btn_bulk_dismiss_other", n=others_count),
                          "callback_data": "pchk_bulk_other"}])
        rows.append([{"text": t("checklist_btn_switch_to_cards"), "callback_data": "pending_cards"}])
        return rows

    shown, rows = fit_checklist_to_telegram_limit(candidates, extra_rows, mode="pending")
    next_offset = offset + len(shown)
    if next_offset < len(pending):
        done_row = rows.pop()
        rows.append([{"text": t("checklist_btn_next_page", n=len(pending) - next_offset),
                      "callback_data": f"pchk_page|{next_offset}"}])
        rows.append(done_row)
    text = t("pending_checklist_text", n=len(pending))
    if offset > 0 or next_offset < len(pending):
        key = "checklist_page_note_more" if next_offset < len(pending) else "checklist_page_note_last"
        text += t(key, start=offset + 1, end=next_offset, total=len(pending))
    send_telegram_plain(chat_id, text, keyboard={"inline_keyboard": rows})


def send_skipped_checklist(chat_id, limit=None, offset=0):
    """List of jobs marked "not interested" (and not yet "Applied") — same layout as /pending
    (title row + action-button row per job), but "🚫 Не цікаво" is replaced with "↩️ Повернути"
    (mode="skipped" in checklist_keyboard_rows), since everything here is already "not
    interested". For the case where the same job got reopened (the company reposted it) and you
    want to apply again — "Повернути" immediately returns the job to "Pending" in /pending.
    `offset`/"➡️ Next" — the same pagination as in /pending, for a long "not interested" list."""
    if limit is None:
        limit = get_setting("pending_cards_limit")
    st = load_state()
    jobs = st.get("jobs", {})
    skipped = [(jid, j) for jid, j in jobs.items()
               if j.get("not_interested") and not j.get("applied")]
    if not skipped:
        send_telegram_plain(chat_id, t("no_skipped"))
        return
    skipped.sort(key=lambda x: (0 if job_priority_and_location(x[1])[0] else 1, -x[1].get("ts", 0)))
    offset = max(0, min(offset, len(skipped) - 1))
    candidates = skipped[offset:offset + limit]
    shown, rows = fit_checklist_to_telegram_limit(candidates, lambda cur_shown: [], mode="skipped")
    next_offset = offset + len(shown)
    if next_offset < len(skipped):
        done_row = rows.pop()
        rows.append([{"text": t("checklist_btn_next_page", n=len(skipped) - next_offset),
                      "callback_data": f"pchk_spage|{next_offset}"}])
        rows.append(done_row)
    text = t("skipped_checklist_text")
    if offset > 0 or next_offset < len(skipped):
        key = "checklist_page_note_more" if next_offset < len(skipped) else "checklist_page_note_last"
        text += t(key, start=offset + 1, end=next_offset, total=len(skipped))
    send_telegram_plain(chat_id, text, keyboard={"inline_keyboard": rows})


def build_seen_text(limit=None):
    """List of jobs the bot marked "seen" SILENTLY — i.e. never pushed (too old at the time of
    the first match, or trimmed by the first-run limit) — so it's possible to check that none
    of them should have arrived, and open one manually via its link."""
    if limit is None:
        limit = get_setting("seen_list_limit")
    st = load_state()
    log_entries = st.get("silent_seen_log", [])
    if not log_entries:
        return t("seen_empty", days=SEEN_LOG_DAYS)
    log_entries = sorted(log_entries, key=lambda e: e.get("ts", 0), reverse=True)
    shown = log_entries[:limit]
    lines = [t("seen_header", n=len(log_entries), days=SEEN_LOG_DAYS)]
    now = time.time()
    for e in shown:
        age_h = (now - e.get("ts", now)) / 3600
        link = html.escape(apply_link(e.get("link", "")))
        title = html.escape((e.get("title") or "?")[:90])
        reason = html.escape(e.get("reason", "?"))
        lines.append(t("seen_line", link=link, title=title, reason=reason, age=format_age(age_h)))
    if len(log_entries) > len(shown):
        lines.append(t("and_n_more", n=len(log_entries) - len(shown)))
    return "\n".join(lines)


def mark_applied(jid):
    def _mark(st):
        j = st.get("jobs", {}).get(jid)
        if j and not j.get("applied"):
            j["applied"] = True
            j["applied_ts"] = time.time()
            st.setdefault("events", []).append({
                "ts": time.time(), "type": "applied", "resume_key": j.get("resume_key"),
            })
    state_update(_mark)


def mark_not_interested(jid):
    """"🚫 Not interested" — remove from reminders and from "pending" in stats, but do NOT count
    it as an application (a separate event type)."""
    def _mark(st):
        j = st.get("jobs", {}).get(jid)
        if j and not j.get("applied") and not j.get("not_interested"):
            j["not_interested"] = True
            j["reminded"] = True  # so it definitely won't remind about it anymore
            if not j.get("skip_logged"):
                j["skip_logged"] = True
                st.setdefault("events", []).append({
                    "ts": time.time(), "type": "skipped", "resume_key": j.get("resume_key"),
                })
    state_update(_mark)


def unmark_not_interested(jid):
    """"↩️ Повернути" in /skipped — one-shot reverse of mark_not_interested, sending the job
    back to /pending. Doesn't touch skip_logged, so the earlier "skipped" stats event stands."""
    def _unmark(st):
        j = st.get("jobs", {}).get(jid)
        if j and j.get("not_interested"):
            j["not_interested"] = False
    state_update(_unmark)


def toggle_not_interested(jid):
    """The "not interested" toggle for the checklist in /pending — unlike the one-shot
    "🚫 Not interested" button under the push itself (mark_not_interested), here you can also
    unmark it if it was pressed by accident. Returns the new state (True = marked "not
    interested", False = unmarked, None = the job has already dropped out of the cache). The
    "skipped" stats event is logged only once per job (even if the mark is toggled on/off
    several times), so the counter doesn't get inflated."""
    result = {"checked": None}

    def _toggle(st):
        j = st.get("jobs", {}).get(jid)
        if not j:
            return
        if j.get("not_interested"):
            j["not_interested"] = False
            result["checked"] = False
        else:
            j["not_interested"] = True
            j["reminded"] = True
            if not j.get("skip_logged"):
                j["skip_logged"] = True
                st.setdefault("events", []).append({
                    "ts": time.time(), "type": "skipped", "resume_key": j.get("resume_key"),
                })
            result["checked"] = True

    state_update(_toggle)
    return result["checked"]
