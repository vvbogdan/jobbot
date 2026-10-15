# -*- coding: utf-8 -*-
"""notify — turns a matched job into an actual push: formatting the message text, sending it to
Telegram and/or ntfy, and the bookkeeping (state.json "jobs" cache entry, "seen", desc
fingerprint) that goes with a successful send. Also the (de)serialization used to queue a job
during quiet hours and flush it later as part of the morning digest.

Fifth extraction step of jobbot.py's split into focused modules.
"""
import html
import json
import os
import re
import time
import urllib.parse
from datetime import datetime

try:
    # your own, real resume — gitignored, never committed (see bot/resumes.py for the public example)
    from .resumes_local import BASE_RESUMES
except ImportError:
    from .resumes import BASE_RESUMES
from .i18n import t
from .net import http
from .logutil import log
from .telegram_api import tg_token, tg_chat
from .matching import apply_link, find_salary, find_deadline, desc_fingerprint
from .state import mark_seen


def fmt_message(labels, src, item, meta, priority=False, reopened=False):
    title = html.escape(item["title"])
    star = "⭐ " if priority else ""
    # labels are profile names (e.g. "🐍 Python (Junior, <2 years)") and may contain "<"/">" —
    # unescaped, Telegram treats that as an unsupported HTML tag and rejects the WHOLE push
    labels_str = html.escape(" · ".join(labels))
    lines = [f"{star}{labels_str}  <i>({src})</i>", f"<b>{title}</b>"]
    if reopened:
        lines.append(t("push_reopened"))
    d = item["desc"].replace("\n", " ")
    extra = []
    company = meta.get("company")
    if company:
        extra.append(f"🏢 {html.escape(company)}")
    salary = find_salary(item["title"], d)
    if salary:
        extra.append(f"💰 {html.escape(salary)}")
    deadline = find_deadline(d)
    if deadline:
        extra.append(t("push_deadline", deadline=html.escape(deadline)))
    if meta.get("years"):
        extra.append(t("push_experience", years=meta["years"]))
    loc_tag = meta.get("location_tag")
    if loc_tag == "lviv_remote":
        extra.append(t("push_location_lviv_remote"))
    elif loc_tag == "kyiv":
        extra.append(t("push_location_kyiv"))
    elif re.search(r"remote|віддален|удалён|full remote", item["title"] + " " + d[:600], re.I):
        extra.append(t("push_remote"))
    if re.search(r"бронюван|reservation|бронь", d, re.I):
        extra.append(t("push_reservation"))
    if item["pub"]:
        loc = item["pub"].astimezone()
        extra.append(loc.strftime("%d.%m %H:%M"))
    if extra:
        lines.append("· " + " · ".join(extra))
    snippet = html.escape(d[:220] + ("…" if len(d) > 220 else ""))
    if snippet:
        lines.append(f"<i>{snippet}</i>")
    return "\n".join(lines)


def send_telegram(text, url=None, jid=None, resume_key=None):
    token, chat = tg_token(), tg_chat()
    if not (token and chat):
        return False
    buttons = []
    if url:
        buttons.append([{"text": t("btn_open_apply"), "url": url}])
    if jid and resume_key and resume_key in BASE_RESUMES:
        buttons.append([
            {"text": t("btn_tailor_resume"), "callback_data": f"cv|{jid}"},
            {"text": t("btn_cover_letter"), "callback_data": f"cl|{jid}"},
        ])
    if jid:
        buttons.append([
            {"text": t("btn_applied"), "callback_data": f"applied|{jid}"},
            {"text": t("btn_not_interested"), "callback_data": f"skip|{jid}"},
        ])
    payload = {
        "chat_id": chat,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    last_err = None
    for _ in range(3):
        try:
            http(f"https://api.telegram.org/bot{token}/sendMessage",
                 data=urllib.parse.urlencode(payload).encode(), timeout=20, retries=0)
            return True
        except RuntimeError as e:
            last_err = e
            m = re.search(r"retry_after\D+(\d+)", str(e))
            time.sleep(int(m.group(1)) if m else 2)
    # Does NOT log "no channel configured" — the token/chat ARE set, this is a real network/API
    # error (e.g. Telegram flood control from a burst of pushes), and it needs its own log line.
    log("✗ sendMessage (after 3 attempts):", last_err)
    return False


def send_ntfy(title, text, url):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return False
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
    try:
        http(f"{server}/{topic}", data=text.encode("utf-8"),
             headers={"Title": "New job", "Click": url, "Priority": "high", "Tags": "briefcase"},
             retries=1)
        return True
    except RuntimeError:
        return False


def notify(jid, labels, src, item, meta, dry, resume_key, priority=False, reopened=False):
    url = apply_link(item["link"])
    text = fmt_message(labels, src, item, meta, priority=priority, reopened=reopened)
    if dry:
        print("─" * 60)
        print(re.sub(r"</?[bi]>", "", html.unescape(text)))
        print("→", url)
        return True
    ok_tg = send_telegram(text, url=url, jid=jid, resume_key=resume_key)
    plain = re.sub(r"</?[bi]>", "", html.unescape(text))
    ok_nt = send_ntfy(t("new_job_ntfy_title"), plain + "\n" + url, url)
    if not (ok_tg or ok_nt):
        log("⚠️  no channel configured (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID or NTFY_TOPIC)")
    time.sleep(0.4)  # Telegram rate limits
    return ok_tg or ok_nt


def serialize_rec(jid, rec):
    """rec (with a datetime inside) -> JSON-compatible dict, for the quiet-hours queue in state.json."""
    item = dict(rec["item"])
    item["pub"] = item["pub"].isoformat() if item["pub"] else None
    return {
        "jid": jid, "item": item, "src": rec["src"], "labels": rec["labels"],
        "meta": rec["meta"], "resume_key": rec["resume_key"], "priority": rec["priority"],
        "dup_ids": rec.get("dup_ids", []),
    }


def deserialize_rec(d):
    item = dict(d["item"])
    item["pub"] = datetime.fromisoformat(item["pub"]) if item.get("pub") else None
    rec = {
        "item": item, "src": d["src"], "labels": d["labels"], "meta": d["meta"],
        "resume_key": d["resume_key"], "priority": d["priority"], "dup_ids": d.get("dup_ids", []),
    }
    return d["jid"], rec


def send_one(jid, rec, dry, st):
    """Puts the job into the cache (for the buttons) and actually sends the push. Used both for
    fresh jobs and for flushing the morning digest after quiet hours."""
    st.setdefault("jobs", {})[jid] = {
        "title": rec["item"]["title"],
        "desc": rec["item"]["desc"][:6000],
        "link": rec["item"]["link"],
        "resume_key": rec["resume_key"],
        "ts": time.time(),
        "applied": False,
        "reminded": False,
        "priority": rec["priority"],
        "location_tag": rec["meta"].get("location_tag"),
    }
    ok = notify(jid, rec["labels"], rec["src"], rec["item"], rec["meta"], dry,
                rec["resume_key"], priority=rec["priority"], reopened=rec.get("reopened", False))
    if ok and not dry:
        mark_seen(st, jid, rec)
        st.setdefault("events", []).append({
            "ts": time.time(), "type": "sent", "resume_key": rec["resume_key"],
        })
        fp = desc_fingerprint(rec["item"]["desc"])
        if fp:
            st.setdefault("desc_fingerprints", {})[fp] = {"ts": time.time(), "jid": jid}
    return ok
