# -*- coding: utf-8 -*-
"""telegram_api — thin wrappers around Telegram's Bot API HTTP endpoints. Everything here is a
mechanical "build a request, call it, parse the result" wrapper with no bot-specific decisions
in it (no job formatting, no i18n, no state) — that's deliberate, so this module can be read and
tested on its own. Bot-specific sends that build inline keyboards from job data (send_telegram,
send_ntfy, notify in jobbot.py) stay in jobbot.py, since they depend on i18n/resumes/job
formatting; they call send_telegram_plain-style primitives from here underneath.

First extraction step of jobbot.py's split into focused modules — see README/commit history for
the rest of the plan.
"""
import json
import os
import urllib.parse
import uuid
from pathlib import Path

from logutil import log
from net import http


def tg_token():
    return os.environ.get("TELEGRAM_BOT_TOKEN")


def tg_chat():
    return os.environ.get("TELEGRAM_CHAT_ID")


def is_authorized(chat_id):
    """This bot is personal — it only responds to its owner (TELEGRAM_CHAT_ID); it doesn't react
    at all to any other chat/command (someone messaged the bot directly, knowing its username),
    so no outsider can read the jobs or, worse, upload a file via /restore and overwrite the
    state."""
    owner = tg_chat()
    return bool(owner) and str(chat_id) == str(owner)


def send_telegram_plain(chat_id, text, buttons=None, keyboard=None):
    """Returns the sent message's message_id (int), or None/falsy on failure — deliberately
    compatible with the previous boolean behavior (message_id is always > 0, so code that just
    checked the result as True/False still works), while code that actually needs the
    message_id (e.g. to later edit the keyboard under that same message — see
    edit_message_reply_markup) now has it available."""
    token = tg_token()
    if not token:
        return None
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if keyboard is not None:
        payload["reply_markup"] = json.dumps(keyboard)
    elif buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    try:
        raw = http(f"https://api.telegram.org/bot{token}/sendMessage",
                   data=urllib.parse.urlencode(payload).encode(), timeout=20, retries=1)
        return json.loads(raw).get("result", {}).get("message_id")
    except RuntimeError as e:
        log("✗ sendMessage:", e)
        return None


def multipart_encode(fields, file_field, filename, file_bytes, mime="application/pdf"):
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        )
    parts.append(
        (f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
         f'filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n').encode()
    )
    parts.append(file_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), boundary


def send_telegram_document(chat_id, file_path, filename, caption="", mime="application/pdf", buttons=None):
    """Returns the sent document's message_id (int), or None on failure. message_id is used,
    among other things, to immediately pin the backup (see pin_chat_message)."""
    token = tg_token()
    if not token:
        return None
    file_bytes = Path(file_path).read_bytes()
    fields = {"chat_id": str(chat_id), "caption": caption[:1024]}
    if buttons:
        fields["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    body, boundary = multipart_encode(
        fields, "document", filename, file_bytes, mime=mime,
    )
    try:
        raw = http(f"https://api.telegram.org/bot{token}/sendDocument", data=body,
                    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                    timeout=60, retries=1)
        return json.loads(raw).get("result", {}).get("message_id")
    except RuntimeError as e:
        log("✗ sendDocument:", e)
        return None
    except (ValueError, KeyError) as e:
        log("✗ sendDocument (parse):", e)
        return None


def answer_callback_query(callback_id, text=""):
    token = tg_token()
    if not token:
        return
    try:
        http(f"https://api.telegram.org/bot{token}/answerCallbackQuery",
             data=urllib.parse.urlencode({"callback_query_id": callback_id, "text": text[:190]}).encode(),
             timeout=15, retries=0)
    except RuntimeError:
        pass


def edit_message_reply_markup(chat_id, message_id, keyboard):
    """Reshapes the keyboard of an ALREADY sent message in place (without sending a new one) —
    used by the checklist in /pending so tapping "☑️ not interested" immediately changes just
    that button's appearance instead of spawning new messages."""
    token = tg_token()
    if not token:
        return False
    payload = {"chat_id": chat_id, "message_id": message_id, "reply_markup": json.dumps(keyboard)}
    try:
        http(f"https://api.telegram.org/bot{token}/editMessageReplyMarkup",
             data=urllib.parse.urlencode(payload).encode(), timeout=15, retries=1)
        return True
    except RuntimeError as e:
        log("✗ editMessageReplyMarkup:", e)
        return False


def get_updates(offset, timeout=25):
    token = tg_token()
    if not token:
        return []
    params = {"timeout": timeout, "allowed_updates": json.dumps(["callback_query", "message"])}
    if offset:
        params["offset"] = offset
    raw = http(f"https://api.telegram.org/bot{token}/getUpdates?{urllib.parse.urlencode(params)}",
               timeout=timeout + 10, retries=0)
    return json.loads(raw).get("result", [])


def fetch_telegram_file(file_id):
    """Downloads a file's content from Telegram (getFile + file server) as text."""
    token = tg_token()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задано")
    raw = http(f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}", timeout=20, retries=1)
    info = json.loads(raw)
    file_path = info.get("result", {}).get("file_path")
    if not file_path:
        raise RuntimeError(f"getFile не повернув file_path: {raw[:200]}")
    return http(f"https://api.telegram.org/file/bot{token}/{file_path}", timeout=30, retries=1)


def pin_chat_message(chat_id, message_id):
    """Pins the backup message so the bot can find and restore the state on its own after a
    restart (e.g. Render Free wipes the disk every time) — getChat->pinned_message works even
    when getUpdates has already "swallowed" the old updates and no local memory of them is left."""
    token = tg_token()
    if not token:
        return
    try:
        http(f"https://api.telegram.org/bot{token}/pinChatMessage",
             data=urllib.parse.urlencode({
                 "chat_id": chat_id, "message_id": message_id, "disable_notification": True,
             }).encode(), timeout=15, retries=1)
    except RuntimeError as e:
        log("✗ pinChatMessage:", e)
