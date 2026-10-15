#!/usr/bin/env python3
"""
jobbot — monitors new DOU + Djinni job postings and pushes them to Telegram (and/or ntfy).

Features:
  - "📄 Tailor resume" button — uses the Claude API to prepare a PDF resume tailored to a
    specific job posting and sends it back into the same chat. The result is cached — a repeat
    click doesn't trigger a new API call; there's a separate "🔄 Regenerate" button for a new
    variant.
  - "✅ Applied" button + an automatic reminder after REMINDER_HOURS hours if not pressed.
  - "🚫 Not interested" button — removes the job from reminders/"pending" stats without
    counting it as an application.
  - The company name (when it can be parsed from the title/description) is shown right in the
    push.
  - Every BACKUP_INTERVAL_HOURS hours (and on the /backup command) sends state.json into the
    same chat; restored by forwarding that file back to the bot.
  - If the DOU/Djinni RSS feed fails FEED_FAIL_THRESHOLD runs in a row — a single warning in
    Telegram (and a single message once the feed recovers), so a technical failure isn't
    mistaken for simply "no new jobs".
  - Jobs whose text mentions "AI agentic" / "Claude Code" / similar are marked ⭐ and pushed
    first.
  - Salary (when stated in the title/description) is shown in the push.
  - Application deadline (when present in the description — "by 15.10", "deadline:",
    "apply by October 20", etc.) is shown in the push next to the salary.
  - /stats command in Telegram — how many jobs were sent and how many applications in 7 days.
  - /pending command — list of jobs awaiting a response, with "not interested" checkboxes and
    a direct link right in each row — you work through the list without leaving it.
  - A persistent keyboard with buttons (Stats/Pending/Backup/Help) — commands without typing;
    the commands also show up in the "/" menu next to the input field.

Sources:
  DOU, Djinni — public RSS feeds (no login required):
    DOU:    https://jobs.dou.ua/vacancies/feeds/?category=<Category>
    Djinni: https://djinni.co/jobs/rss/?primary_keyword=<Keyword>
  Jooble, RemoteOK, Work.ua — optional, off by default, see README section 15:
    Jooble:   REST API (needs a free JOOBLE_API_KEY), search by keyword+location
    RemoteOK: public JSON API, search by tag — mostly international remote jobs
    Work.ua:  no public RSS/API (discontinued) — HTML scraper, more fragile than the above

Environment variables:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   — required for pushes and commands
  NTFY_TOPIC, NTFY_SERVER                — optional second push channel
  ANTHROPIC_API_KEY                      — needed for the "Tailor resume" button
  ANTHROPIC_MODEL                        — Claude model (default claude-sonnet-5)
  REMINDER_HOURS                         — remind about applying after N hours (0 = off; default 20)
  JOBBOT_STATE                           — path to state.json (default ./state.json)
  PORT                                   — if set, starts a health endpoint (Render)
  TZ_NAME                                — timezone for quiet hours (default Europe/Kyiv)
  QUIET_HOURS_START, QUIET_HOURS_END     — quiet hours [start, end) — don't push, collect and
                                            send as one batch once quiet hours end
  DIGEST_WEEKDAY, DIGEST_HOUR             — when to send /stats automatically (default Sunday, 19:00)
  BACKUP_INTERVAL_HOURS                   — how often to send a state.json backup into the
                                            same chat (0 = off; default 24)
  STATS_PERIOD_DAYS                       — window for /stats and the weekly digest (default 14)
  FEED_FAIL_THRESHOLD                     — after how many consecutive failed feed runs to send
                                            a Telegram warning (0 = off; default 5)
  JOOBLE_API_KEY                          — required to enable the Jooble source (/set source_jooble 1)
  JOOBLE_LOCATION                         — location Jooble searches in (default "Україна")

Run:
  python3 jobbot.py                # one-off run (for cron / GitHub Actions)
  python3 jobbot.py --loop 60      # run continuously + listen for Telegram commands
  python3 jobbot.py --dry-run      # send nothing, just show matches
  python3 jobbot.py --test         # send a test push

Dependencies: standard library + reportlab (PDF generation) + beautifulsoup4 (only needed for
the optional Work.ua scraper).
  pip install -r requirements.txt

Architecture: this file is now just the entrypoint — argument parsing, the Telegram
command/callback dispatcher (poll_telegram_loop), and wiring up the background threads in
main(). Everything else lives in bot/ as focused modules:
  bot/config.py          search profiles and global filtering rules (the file to edit to make
                          jobbot search for your own roles)
  bot/resumes.py / bot/resumes_local.py   base resumes for the "Tailor resume" button
  bot/net.py              raw HTTP helper + HTML stripping
  bot/i18n.py             all user-facing text (uk/en)
  bot/logutil.py          the shared log() helper
  bot/firebase_store.py   optional Firebase Realtime Database backend for state.json
  bot/telegram_api.py     raw Telegram Bot API HTTP wrappers
  bot/matching.py         pure job-filtering/scoring logic (no Telegram/network/state)
  bot/state.py            state.json load/save, /set-able settings, search-profile CRUD
  bot/resume.py           Claude API + PDF generation for the tailored resume/cover letter
  bot/sources/            DOU/Djinni/Jooble/RemoteOK/Work.ua feed providers
  bot/runtime.py          small process-wide constants derived from the environment
  bot/notify.py           formatting + sending a push, and the quiet-hours queue (de)serializer
  bot/collector.py        the job-gathering pipeline (collect/dedup/run_once)
  bot/wizard.py           the interactive /addprofile conversation
  bot/commands.py         /help, /stats, /pending, /seen, /skipped text+keyboards
  bot/background.py       reminders, weekly digest, state backup/restore loops
  bot/resume_handlers.py  the "Tailor resume"/"Cover letter" button handlers
  bot/health.py           the Render health-check HTTP endpoint
"""
import argparse
import os
import sys
import threading
import time

from bot.i18n import t
from bot.logutil import log
from bot.telegram_api import (
    tg_token, is_authorized, send_telegram_plain,
    answer_callback_query, edit_message_reply_markup, get_updates,
)
from bot.matching import job_priority_and_location
from bot.state import (
    load_state, state_update, get_setting, set_setting, build_settings_text,
    delete_profile_by_crc, build_profiles_text, profiles_keyboard,
)
from bot.notify import send_telegram, send_ntfy
from bot.collector import run_once
from bot.wizard import (
    start_profile_wizard, handle_profile_wizard_text, _profile_wizard_set_senior_and_advance,
)
from bot.commands import (
    MAIN_MENU_KEYBOARD, BUTTON_TEXT_TO_COMMAND, set_bot_commands, build_help_text,
    build_stats_text, send_pending_cards, send_pending_checklist, send_skipped_checklist,
    build_seen_text, mark_applied, mark_not_interested, unmark_not_interested,
    toggle_not_interested,
)
from bot.background import (
    reminder_loop, digest_loop, backup_loop, send_state_backup, handle_restore_document,
    restore_from_pinned_backup,
)
from bot.resume_handlers import handle_cv_request, handle_cl_request
from bot.health import start_health_server


# ───────────────────────── POLLING TELEGRAM COMMANDS ─────────────────────────


def poll_telegram_loop():
    if not tg_token():
        log("Telegram token not set — not listening for chat commands")
        return
    log("listening for Telegram commands…")
    while True:
        try:
            offset = load_state().get("tg_offset", 0)
            updates = get_updates(offset)
        except Exception as e:  # noqa: BLE001
            log("✗ getUpdates:", e)
            time.sleep(5)
            continue
        for upd in updates:
            state_update(lambda st: st.__setitem__("tg_offset", upd["update_id"] + 1))
            try:
                if "callback_query" in upd:
                    cq = upd["callback_query"]
                    chat_id = cq["message"]["chat"]["id"]
                    if not is_authorized(chat_id):
                        log(f"⛔ unauthorized callback from chat {chat_id} — ignored")
                        answer_callback_query(cq["id"])
                        continue
                    data = cq.get("data", "")
                    if data.startswith("cvr|"):
                        jid = data.split("|", 1)[1]
                        threading.Thread(target=handle_cv_request,
                                          args=(chat_id, cq["id"], jid), kwargs={"force": True}, daemon=True).start()
                    elif data.startswith("cv|"):
                        jid = data.split("|", 1)[1]
                        threading.Thread(target=handle_cv_request,
                                          args=(chat_id, cq["id"], jid), daemon=True).start()
                    elif data.startswith("clr|"):
                        jid = data.split("|", 1)[1]
                        threading.Thread(target=handle_cl_request,
                                          args=(chat_id, cq["id"], jid), kwargs={"force": True}, daemon=True).start()
                    elif data.startswith("cl|"):
                        jid = data.split("|", 1)[1]
                        threading.Thread(target=handle_cl_request,
                                          args=(chat_id, cq["id"], jid), daemon=True).start()
                    elif data.startswith("applied|"):
                        jid = data.split("|", 1)[1]
                        mark_applied(jid)
                        answer_callback_query(cq["id"], t("toast_marked_applied"))
                    elif data.startswith("skip|"):
                        jid = data.split("|", 1)[1]
                        mark_not_interested(jid)
                        answer_callback_query(cq["id"], t("toast_marked_not_interested"))
                    elif data == "pending_cards":
                        threading.Thread(target=send_pending_cards, args=(chat_id,), daemon=True).start()
                        answer_callback_query(cq["id"])
                    elif data == "pending_checklist":
                        threading.Thread(target=send_pending_checklist, args=(chat_id,), daemon=True).start()
                        answer_callback_query(cq["id"])
                    elif data.startswith("pchk|"):
                        jid = data.split("|", 1)[1]
                        checked = toggle_not_interested(jid)
                        if checked is None:
                            answer_callback_query(cq["id"], t("toast_job_gone"))
                        else:
                            answer_callback_query(cq["id"], t("toast_marked_not_interested") if checked else t("toast_unmarked"))
                            markup = cq["message"].get("reply_markup") or {}
                            kb = markup.get("inline_keyboard", [])
                            for row in kb:
                                for btn in row:
                                    if btn.get("callback_data") == data:
                                        old = btn.get("text", "")
                                        rest = old[2:] if len(old) > 2 else old
                                        btn["text"] = ("✅ " if checked else "⬜ ") + rest
                            threading.Thread(
                                target=edit_message_reply_markup,
                                args=(chat_id, cq["message"]["message_id"], {"inline_keyboard": kb}),
                                daemon=True,
                            ).start()
                    elif data == "pchk_done":
                        answer_callback_query(cq["id"], t("toast_done"))
                        threading.Thread(
                            target=edit_message_reply_markup,
                            args=(chat_id, cq["message"]["message_id"], {"inline_keyboard": []}),
                            daemon=True,
                        ).start()
                    elif data == "noop":
                        # non-clickable group-header rows in the checklist ("— Other —" etc.)
                        answer_callback_query(cq["id"])
                    elif data == "pchk_bulk_other":
                        # "🚫 Dismiss all 'Other'" — marks "not interested" on the whole non-priority
                        # group from the current /pending in one go (Lviv/Remote, iOS, AI stay).
                        st = load_state()
                        jobs = st.get("jobs", {})
                        pending = [(jid, j) for jid, j in jobs.items()
                                   if not j.get("applied") and not j.get("not_interested")]
                        limit = get_setting("pending_cards_limit")
                        pending.sort(key=lambda x: (0 if job_priority_and_location(x[1])[0] else 1,
                                                     -x[1].get("ts", 0)))
                        shown = pending[:limit]
                        others = [jid for jid, j in shown if not job_priority_and_location(j)[0]]
                        for other_jid in others:
                            mark_not_interested(other_jid)
                        answer_callback_query(cq["id"], t("toast_bulk_dismissed", n=len(others)))
                        threading.Thread(
                            target=edit_message_reply_markup,
                            args=(chat_id, cq["message"]["message_id"], {"inline_keyboard": []}),
                            daemon=True,
                        ).start()
                        threading.Thread(target=send_pending_checklist, args=(chat_id,), daemon=True).start()
                    elif data.startswith("pchk_applied|"):
                        # "✅ Цікаво" right from the checklist (/pending or /skipped) — so there's
                        # no need to switch to card mode when applying straight from here.
                        jid = data.split("|", 1)[1]
                        mark_applied(jid)
                        answer_callback_query(cq["id"], t("toast_marked_applied"))
                        markup = cq["message"].get("reply_markup") or {}
                        kb = markup.get("inline_keyboard", [])
                        new_kb = []
                        for row in kb:
                            if any(b.get("callback_data") == data for b in row):
                                # this row (the 3 action buttons) and the previous one (the
                                # non-clickable title row) belong to this job — remove both
                                if new_kb:
                                    new_kb.pop()
                                continue
                            new_kb.append(row)
                        threading.Thread(
                            target=edit_message_reply_markup,
                            args=(chat_id, cq["message"]["message_id"], {"inline_keyboard": new_kb}),
                            daemon=True,
                        ).start()
                    elif data.startswith("pchk_skip|"):
                        # "🚫 Не цікаво" right from the /pending checklist.
                        jid = data.split("|", 1)[1]
                        mark_not_interested(jid)
                        answer_callback_query(cq["id"], t("toast_marked_not_interested"))
                        markup = cq["message"].get("reply_markup") or {}
                        kb = markup.get("inline_keyboard", [])
                        new_kb = []
                        for row in kb:
                            if any(b.get("callback_data") == data for b in row):
                                if new_kb:
                                    new_kb.pop()
                                continue
                            new_kb.append(row)
                        threading.Thread(
                            target=edit_message_reply_markup,
                            args=(chat_id, cq["message"]["message_id"], {"inline_keyboard": new_kb}),
                            daemon=True,
                        ).start()
                    elif data.startswith("pchk_undo|"):
                        # "↩️ Повернути" right from the /skipped checklist — back to /pending.
                        jid = data.split("|", 1)[1]
                        unmark_not_interested(jid)
                        answer_callback_query(cq["id"], t("toast_unmarked"))
                        markup = cq["message"].get("reply_markup") or {}
                        kb = markup.get("inline_keyboard", [])
                        new_kb = []
                        for row in kb:
                            if any(b.get("callback_data") == data for b in row):
                                if new_kb:
                                    new_kb.pop()
                                continue
                            new_kb.append(row)
                        threading.Thread(
                            target=edit_message_reply_markup,
                            args=(chat_id, cq["message"]["message_id"], {"inline_keyboard": new_kb}),
                            daemon=True,
                        ).start()
                    elif data.startswith("pchk_page|"):
                        # "➡️ Next" in /pending — the next page starting right where this one left
                        # off (instead of manually repeating /pending and scrolling past the same start).
                        next_offset = int(data.split("|", 1)[1])
                        answer_callback_query(cq["id"])
                        threading.Thread(
                            target=edit_message_reply_markup,
                            args=(chat_id, cq["message"]["message_id"], {"inline_keyboard": []}),
                            daemon=True,
                        ).start()
                        threading.Thread(target=send_pending_checklist, args=(chat_id,),
                                          kwargs={"offset": next_offset}, daemon=True).start()
                    elif data.startswith("pchk_spage|"):
                        # the same "➡️ Next", but for /skipped.
                        next_offset = int(data.split("|", 1)[1])
                        answer_callback_query(cq["id"])
                        threading.Thread(
                            target=edit_message_reply_markup,
                            args=(chat_id, cq["message"]["message_id"], {"inline_keyboard": []}),
                            daemon=True,
                        ).start()
                        threading.Thread(target=send_skipped_checklist, args=(chat_id,),
                                          kwargs={"offset": next_offset}, daemon=True).start()
                    elif data.startswith("delprof_ask|"):
                        # First tap only arms this one row with a confirm/cancel pair — nothing
                        # is deleted yet (see profiles_keyboard()).
                        crc = data.split("|", 1)[1]
                        answer_callback_query(cq["id"])
                        markup = cq["message"].get("reply_markup") or {}
                        kb = markup.get("inline_keyboard", [])
                        new_kb = []
                        for row in kb:
                            if any(b.get("callback_data") == data for b in row):
                                new_kb.append([
                                    {"text": t("profiles_delete_confirm_btn"),
                                     "callback_data": f"delprof|{crc}"},
                                    {"text": t("profiles_delete_cancel_btn"),
                                     "callback_data": f"delprof_cancel|{crc}"},
                                ])
                            else:
                                new_kb.append(row)
                        threading.Thread(
                            target=edit_message_reply_markup,
                            args=(chat_id, cq["message"]["message_id"], {"inline_keyboard": new_kb}),
                            daemon=True,
                        ).start()
                    elif data.startswith("delprof_cancel|"):
                        answer_callback_query(cq["id"], t("toast_cancelled"))
                        threading.Thread(
                            target=edit_message_reply_markup,
                            args=(chat_id, cq["message"]["message_id"],
                                  profiles_keyboard() or {"inline_keyboard": []}),
                            daemon=True,
                        ).start()
                    elif data.startswith("delprof|"):
                        crc = data.split("|", 1)[1]
                        removed = delete_profile_by_crc(crc)
                        if removed:
                            answer_callback_query(cq["id"], t("profiles_deleted", label=removed))
                        else:
                            answer_callback_query(cq["id"], t("toast_job_gone"))
                        threading.Thread(target=send_telegram_plain,
                                          args=(chat_id, build_profiles_text()),
                                          kwargs={"keyboard": profiles_keyboard()}, daemon=True).start()
                    elif data.startswith("profwiz_senior|"):
                        yes = data.split("|", 1)[1] == "yes"
                        answer_callback_query(cq["id"])
                        _profile_wizard_set_senior_and_advance(chat_id, yes)
                    else:
                        answer_callback_query(cq["id"])
                elif "message" in upd:
                    msg = upd["message"]
                    chat_id = msg["chat"]["id"]
                    if not is_authorized(chat_id):
                        log(f"⛔ unauthorized message from chat {chat_id} — ignored")
                        continue
                    if msg.get("document"):
                        handle_restore_document(chat_id, msg["document"])
                        continue
                    raw_text = (msg.get("text") or "").strip()
                    if handle_profile_wizard_text(chat_id, raw_text):
                        continue
                    text = BUTTON_TEXT_TO_COMMAND.get(raw_text, raw_text.lower())
                    if text in ("/start", "/help"):
                        send_telegram_plain(chat_id, build_help_text(), keyboard=MAIN_MENU_KEYBOARD)
                    elif text == "/stats":
                        send_telegram_plain(chat_id, build_stats_text())
                    elif text == "/pending":
                        send_pending_checklist(chat_id)
                    elif text == "/seen":
                        send_telegram_plain(chat_id, build_seen_text())
                    elif text == "/skipped":
                        send_skipped_checklist(chat_id)
                    elif text == "/backup":
                        send_state_backup(chat_id, note=t("backup_manual_note"))
                    elif text == "/settings":
                        send_telegram_plain(chat_id, build_settings_text())
                    elif text == "/profiles":
                        send_telegram_plain(chat_id, build_profiles_text(), keyboard=profiles_keyboard())
                    elif text == "/addprofile":
                        start_profile_wizard(chat_id)
                    elif text.split(" ", 1)[0] == "/set":
                        parts = raw_text.split(None, 2)
                        if len(parts) != 3:
                            send_telegram_plain(
                                chat_id,
                                t("set_usage", settings=build_settings_text()),
                            )
                        else:
                            _, key, val = parts
                            ok, result = set_setting(key.lower(), val)
                            if ok:
                                msg = t("set_ok", key=key.lower(), value=result)
                                if (key.lower() == "source_jooble" and result
                                        and not os.environ.get("JOOBLE_API_KEY")):
                                    msg += "\n" + t("set_jooble_needs_key")
                                send_telegram_plain(chat_id, msg)
                            else:
                                send_telegram_plain(chat_id, t("set_error", error=result))
            except Exception as e:  # noqa: BLE001
                log("✗ processing update:", e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, metavar="SEC", help="repeat every SEC seconds")
    ap.add_argument("--dry-run", action="store_true", help="just show matches, send and remember nothing")
    ap.add_argument("--test", action="store_true", help="send a test push")
    a = ap.parse_args()

    if a.test:
        ok = send_telegram(t("test_push_text"))
        ok = send_ntfy("jobbot", t("test_ntfy_text"), "https://jobs.dou.ua/") or ok
        print("OK" if ok else "Failed to send — check the token/chat id")
        return
    if a.loop:
        restore_from_pinned_backup()
        start_health_server()
        set_bot_commands()
        threading.Thread(target=poll_telegram_loop, daemon=True).start()
        threading.Thread(target=reminder_loop, daemon=True).start()
        threading.Thread(target=digest_loop, daemon=True).start()
        threading.Thread(target=backup_loop, daemon=True).start()
        while True:
            try:
                run_once(a.dry_run)
            except Exception as e:  # noqa: BLE001
                log("run error:", e)
            time.sleep(a.loop)
    else:
        run_once(a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
