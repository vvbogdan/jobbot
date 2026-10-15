# -*- coding: utf-8 -*-
"""background — the bot's long-running background threads: application reminders, the weekly
/stats digest, periodic state.json backups into the chat, and restoring state.json from a
backup (either one forwarded into the chat, or found pinned there at startup).

Ninth extraction step of jobbot.py's split into focused modules.

NOTE on a bug fixed during this extraction: the two restore functions used to do
`global _cached_state, _last_saved_json` and assign them directly, back when they lived in
jobbot.py. That created two module-level globals IN JOBBOT.PY's OWN NAMESPACE — unrelated to
bot.state's real in-memory cache of the same name — so a restore persisted correctly to disk/
Firebase (save_state() takes the dict as an argument) but the running process kept serving the
OLD state from bot.state._cached_state until the next restart. Now they call
bot.state.restore_state(data), which updates the real cache.
"""
import html
import json
import time
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # noqa: BLE001  (Python < 3.9)
    ZoneInfo = None

from .i18n import t
from .net import http
from .logutil import log
from .matching import apply_link
from .telegram_api import (
    tg_token, tg_chat, send_telegram_plain, send_telegram_document,
    fetch_telegram_file, pin_chat_message,
)
from .state import load_state, state_update, get_setting, STATE_FILE, restore_state
from .runtime import (
    TZ_NAME, REMINDER_CHECK_SEC, DIGEST_WEEKDAY, DIGEST_HOUR, DIGEST_CHECK_SEC,
    BACKUP_CHECK_SEC, BACKUP_STARTUP_DELAY_SEC,
)
from . import commands  # build_stats_text() — for the weekly digest

# ───────────────────────── APPLICATION REMINDERS ─────────────────────────


def check_reminders():
    st = load_state()
    now = time.time()
    chat = tg_chat()
    if not chat:
        return
    reminder_hours = get_setting("reminder_hours")
    if reminder_hours <= 0:
        return
    to_remind = []
    for jid, j in st.get("jobs", {}).items():
        if j.get("applied") or j.get("reminded") or j.get("not_interested"):
            continue
        age_h = (now - j.get("ts", now)) / 3600
        if age_h >= reminder_hours:
            to_remind.append(jid)
    for jid in to_remind:
        j = st["jobs"][jid]
        text = t("reminder_text", hours=int(reminder_hours),
                 title=html.escape(j['title']), link=apply_link(j['link']))
        buttons = [[
            {"text": t("btn_applied"), "callback_data": f"applied|{jid}"},
            {"text": t("btn_not_interested"), "callback_data": f"skip|{jid}"},
        ]]
        if send_telegram_plain(chat, text, buttons=buttons):
            def _mark(st, jid=jid):
                jj = st.get("jobs", {}).get(jid)
                if jj:
                    jj["reminded"] = True
            state_update(_mark)


def reminder_loop():
    # Doesn't exit early even if REMINDER_HOURS=0 at startup — /set reminder_hours can turn
    # reminders on later without a restart; check_reminders() itself checks on/off on every tick.
    log(f"application reminders: after {get_setting('reminder_hours'):g} h (0 = off; change with /set reminder_hours N)")
    while True:
        time.sleep(REMINDER_CHECK_SEC)
        try:
            check_reminders()
        except Exception as e:  # noqa: BLE001
            log("✗ check_reminders:", e)


# ───────────────────────── WEEKLY DIGEST ─────────────────────────


def maybe_send_weekly_digest():
    """Once a week (by default Sunday evening) sends /stats on its own, without waiting for the command."""
    chat = tg_chat()
    if not chat:
        return
    if ZoneInfo is not None:
        try:
            tz = ZoneInfo(TZ_NAME)
        except Exception:  # noqa: BLE001
            tz = timezone.utc
    else:
        tz = timezone.utc
    now_local = datetime.now(tz)
    if now_local.weekday() != DIGEST_WEEKDAY or now_local.hour != DIGEST_HOUR:
        return
    today_key = now_local.strftime("%Y-%m-%d")
    if load_state().get("last_digest_date") == today_key:
        return  # already sent today at this hour
    text = t("weekly_digest_header") + commands.build_stats_text()
    if send_telegram_plain(chat, text):
        def _mark(st):
            st["last_digest_date"] = today_key
        state_update(_mark)


def digest_loop():
    log(f"weekly digest: weekday={DIGEST_WEEKDAY} (0=Mon..6=Sun), {DIGEST_HOUR}:00 ({TZ_NAME})")
    while True:
        time.sleep(DIGEST_CHECK_SEC)
        try:
            maybe_send_weekly_digest()
        except Exception as e:  # noqa: BLE001
            log("✗ maybe_send_weekly_digest:", e)


# ───────────────────────── STATE BACKUP/RESTORE ─────────────────────────
# Render (and similar) without a paid plan can wipe the disk on every deploy/restart — without
# a backup that's losing the whole "seen"/"jobs"/"events" history and re-spamming old jobs.


def send_state_backup(chat_id, note=""):
    # With Firebase configured, save_state() normally doesn't touch the local file at all — so
    # write the CURRENT in-memory state there first, otherwise this would back up a stale or
    # missing file instead of what's actually live.
    st = load_state()
    if not (st.get("jobs") or st.get("seen")):
        send_telegram_plain(chat_id, t("no_state_to_backup"))
        return False
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False))
    caption = t("backup_caption", date=datetime.now().strftime('%d.%m.%Y %H:%M'))
    if note:
        caption += f"\n{note}"
    msg_id = send_telegram_document(chat_id, STATE_FILE, "state_backup.json",
                                     caption=caption, mime="application/json")
    if msg_id:
        pin_chat_message(chat_id, msg_id)
    return bool(msg_id)


def maybe_send_backup():
    backup_interval_hours = get_setting("backup_interval_hours")
    chat = tg_chat()
    if not chat or backup_interval_hours <= 0:
        return
    st = load_state()
    last = st.get("last_backup_ts", 0)
    if time.time() - last < backup_interval_hours * 3600:
        return
    if send_state_backup(chat):
        def _mark(st):
            st["last_backup_ts"] = time.time()
        state_update(_mark)


def backup_loop():
    log(f"state backup: every {get_setting('backup_interval_hours'):g} h (0 = off; change with /set backup_interval_hours N)")
    # An initial attempt shortly after startup (rather than waiting the full BACKUP_CHECK_SEC), so
    # that on Render Free — where the disk is wiped on every restart and there may not yet be a
    # pinned backup to auto-restore from — a pinned backup appears as soon as possible, not after
    # 30+ minutes or (worst case) a whole day.
    time.sleep(BACKUP_STARTUP_DELAY_SEC)
    try:
        maybe_send_backup()
    except Exception as e:  # noqa: BLE001
        log("✗ maybe_send_backup (startup):", e)
    while True:
        time.sleep(BACKUP_CHECK_SEC)
        try:
            maybe_send_backup()
        except Exception as e:  # noqa: BLE001
            log("✗ maybe_send_backup:", e)


def handle_restore_document(chat_id, document):
    """If a file that looks like one of our own backups (name starts with 'state' and ends in
    .json) is sent into the chat — restores state.json (in memory, and Firebase if configured)
    from it."""
    filename = (document.get("file_name") or "").lower()
    if not (filename.startswith("state") and filename.endswith(".json")):
        return  # not one of our backups — ignore silently
    send_telegram_plain(chat_id, t("restoring_state_from", filename=document.get('file_name')))
    try:
        raw = fetch_telegram_file(document["file_id"])
        data = json.loads(raw)
        if not isinstance(data, dict) or "jobs" not in data or "seen" not in data:
            raise ValueError(t("restore_invalid_file"))
        restore_state(data)  # push the restored data to Firebase (or local file) right away
        send_telegram_plain(
            chat_id,
            t("state_restored", jobs=len(data.get('jobs', {})), seen=len(data.get('seen', {}))),
        )
    except Exception as e:  # noqa: BLE001
        log("✗ handle_restore_document:", e)
        send_telegram_plain(chat_id, t("restore_failed", error=e))


def restore_from_pinned_backup():
    """Called once at startup (--loop). With Firebase configured, load_state() already pulled
    real persisted state from there, so this is now a last-resort fallback (Firebase misconfigured,
    down, or not set up at all) — if the state we have is empty (typical for Render Free without
    Firebase: the disk isn't persistent and gets wiped on every restart/redeploy), looks for the
    latest pinned backup in the chat on its own (getChat -> pinned_message, which survives a bot
    restart, unlike getUpdates) and restores the state from it — no need to manually forward the
    file every time."""
    token, chat = tg_token(), tg_chat()
    if not (token and chat):
        return
    st = load_state()
    if st.get("jobs") or st.get("seen"):
        return  # already have real state (from Firebase or local disk) — nothing to restore
    try:
        raw = http(f"https://api.telegram.org/bot{token}/getChat?chat_id={chat}", timeout=15, retries=1)
        info = json.loads(raw)
        pinned = info.get("result", {}).get("pinned_message")
        if not pinned or not pinned.get("document"):
            log("auto-restore: no pinned backup found in the chat")
            return
        doc = pinned["document"]
        filename = (doc.get("file_name") or "").lower()
        if not (filename.startswith("state") and filename.endswith(".json")):
            log("auto-restore: the pinned message isn't a jobbot backup, skipping")
            return
        backup_raw = fetch_telegram_file(doc["file_id"])
        data = json.loads(backup_raw)
        if not isinstance(data, dict) or "jobs" not in data or "seen" not in data:
            raise ValueError(t("restore_invalid_file"))
        restore_state(data)  # push the restored data to Firebase (or local file) right away
        log(f"auto-restore: state restored from the pinned backup "
            f"({len(data.get('jobs', {}))} jobs, {len(data.get('seen', {}))} seen)")
        send_telegram_plain(
            chat,
            t("auto_restored", jobs=len(data.get('jobs', {})), seen=len(data.get('seen', {}))),
        )
    except Exception as e:  # noqa: BLE001
        log("✗ restore_from_pinned_backup:", e)
