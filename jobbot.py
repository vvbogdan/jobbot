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
"""
import argparse
import html
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import uuid
import zlib
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # noqa: BLE001  (Python < 3.9 — quiet hours just won't apply)
    ZoneInfo = None

try:
    # your own, real resume — gitignored, never committed (see resumes.py for the public example)
    from resumes_local import BASE_RESUMES
except ImportError:
    from resumes import BASE_RESUMES
from i18n import t
from config import (
    PROFILES, GLOBAL_EXCLUDE, SENIOR_WORDS, PRIORITY_TEXT,
    EMBEDDED_PRIORITY_LOCATION_RE, EMBEDDED_KYIV_LOCATION_RE,
    MAX_AGE_DAYS, FIRST_RUN_LIMIT,
)
from net import http, strip_html
from sources import PROVIDERS

# ───────────────────────── SETTINGS ─────────────────────────

STATE_FILE = Path(os.environ.get("JOBBOT_STATE", "state.json"))
STATE_LOCK = threading.Lock()

# MAX_AGE_DAYS, FIRST_RUN_LIMIT — see config.py (profile/preference settings live there now)
JOBS_CACHE_DAYS = 14      # how many days to keep a job's full text for the "resume" button
REMINDER_HOURS = float(os.environ.get("REMINDER_HOURS", "20"))  # 0 = disable reminders
REMINDER_CHECK_SEC = 600  # how often to check who's due for a reminder

TZ_NAME = os.environ.get("TZ_NAME", "Europe/Kyiv")
QUIET_HOURS_START = int(os.environ.get("QUIET_HOURS_START", "1"))   # quiet hours start (inclusive)
QUIET_HOURS_END = int(os.environ.get("QUIET_HOURS_END", "7"))       # quiet hours end (exclusive)

DIGEST_WEEKDAY = int(os.environ.get("DIGEST_WEEKDAY", "6"))  # 0=Monday ... 6=Sunday
DIGEST_HOUR = int(os.environ.get("DIGEST_HOUR", "19"))       # what hour (local time, TZ_NAME)
DIGEST_CHECK_SEC = 300

BACKUP_INTERVAL_HOURS = float(os.environ.get("BACKUP_INTERVAL_HOURS", "24"))  # 0 = disable
BACKUP_CHECK_SEC = 1800

FEED_FAIL_THRESHOLD = int(os.environ.get("FEED_FAIL_THRESHOLD", "5"))  # consecutive runs (0 = disable)

PENDING_LIST_LIMIT = int(os.environ.get("PENDING_LIST_LIMIT", "20"))  # how many to show in /pending
PENDING_CARDS_LIMIT = int(os.environ.get("PENDING_CARDS_LIMIT", "40"))  # guard against a button-spam flood
# Telegram flood control: without a pause between pushes, a batch of new jobs (e.g. after
# Render Free wipes the disk and a "first run" repeats) hits the rate limit and send_telegram()
# silently (previously — with no log at all) returns False for ALL of them in a row.
PUSH_THROTTLE_SEC = float(os.environ.get("PUSH_THROTTLE_SEC", "1.2"))
SEEN_LIST_LIMIT = int(os.environ.get("SEEN_LIST_LIMIT", "20"))  # how many to show in /seen
SEEN_LOG_DAYS = int(os.environ.get("SEEN_LOG_DAYS", "14"))  # how many days to keep the silent-seen log

STATS_PERIOD_DAYS = int(os.environ.get("STATS_PERIOD_DAYS", "14"))  # window for /stats and the digest

SALARY_RE = re.compile(
    r"\$\s?\d+(?:[.,]\d+)?(?:\s?[-–—]\s?\$?\d+(?:[.,]\d+)?)?"
)
DEADLINE_RE = re.compile(
    r"(?:прийом(?:у)?\s*(?:резюме|заявок)?|заявки приймаються|подати резюме|"
    r"дедлайн|deadline|apply by|applications?\s*(?:close|due|are open until)|due date)"
    r"\s*(?:до|by)?\s*[:\-—]?\s*"
    r"(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?"
    r"|\d{1,2}\s+(?:січня|лютого|березня|квітня|травня|червня|липня|серпня|вересня|жовтня|"
    r"листопада|грудня)"
    r"|(?:january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+\d{1,2}(?:st|nd|rd|th)?)",
    re.I,
)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
APPLICANT_NAME = re.sub(r"[^\w\-]+", "", os.environ.get("APPLICANT_NAME", "Resume"))

# Rough heuristic for the company name — better to show nothing than to make one up
COMPANY_AT_RE = re.compile(
    r"\bat\s+([A-ZА-ЯІЇЄҐ][\w&.'’\-]+(?:\s+[A-ZА-ЯІЇЄҐ0-9][\w&.'’\-]*){0,3})\s*$"
)
COMPANY_LABEL_RE = re.compile(
    r"(?:компані[яю]|компанія-замовник|company|client|employer)\s*[:\-—]\s*([A-ZА-ЯІЇЄҐ][^\n,.;|]{1,60})",
    re.I,
)

# EMBEDDED_TEXT, EMBEDDED_PRIORITY_LOCATION_RE, EMBEDDED_KYIV_LOCATION_RE — see config.py
# (profile/preference settings live there now). DOU/Djinni's own URL templates live in
# sources/dou.py and sources/djinni.py.

# DOU/Djinni sometimes leave a closed vacancy in the RSS feed for a while, but mark it in the text
CLOSED_TEXT = (
    r"вакансія закрит|закрито вакансі|вакансія в архіві|прийом (заявок|резюме) закрит|"
    r"більше не актуальн|вакансія неактуальн|posting (is |has been )?closed|"
    r"position (is |has been )?(closed|filled)|vacancy (is )?closed|no longer accepting|"
    r"we('| a)re no longer hiring"
)

# PROFILES — see config.py (this is the file to edit to make jobbot search for your own roles)

# ───────────────────────── HELPERS ─────────────────────────


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


# http(), strip_html(), parse_rss() moved to net.py / sources/_rss.py — imported at the
# top of this file. fetch_jooble()/fetch_remoteok()/fetch_workua() moved to sources/*.py —
# see sources/__init__.py (PROFILES' "keywords" + PROVIDERS drive collect() below).


def normalize_title(title):
    """Rough title normalization for comparing jobs across sites."""
    t = title.lower()
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def job_id(link):
    m = re.search(r"/vacancies/(\d+)", link) or re.search(r"/jobs/(\d+)", link)
    if m:
        if "dou.ua" in link:
            return "dou:" + m.group(1)
        if "work.ua" in link:
            return "workua:" + m.group(1)
        return "dj:" + m.group(1)
    # Jooble/RemoteOK links don't match either pattern — the full link (minus query string) is
    # already unique per source/job, so no extra prefix is needed.
    return link.split("?")[0]



# "Company on the market for 12 years" / "outsourcing company with over 12 years of experience"
# etc. — that's the COMPANY's history, not a requirement for the candidate. years_required()
# must ignore these.
COMPANY_HISTORY_RE = (
    r"company|компані|outsourc|outstaff|on the market|у сфер|на ринку|заснован|"
    r"founded|since (19|20)\d{2}|history|team has|our team|команда має"
)


def years_required(desc):
    """Maximum years of experience mentioned next to the word 'experience/досвід' — and which
    is a requirement for the CANDIDATE, not a mention of the company's own age/history
    ("company with over N years of experience")."""
    best = None
    pat = r"(\d{1,2})\s*\+?\s*(?:years?|yrs?|роки|років|рок|рік)\b"
    for m in re.finditer(pat, desc, flags=re.I):
        before = desc[max(0, m.start() - 70): m.start()]
        after = desc[m.end(): m.end() + 70]
        # a narrow window right before the number, cut at the sentence boundary — so a phrase
        # about the company from the PREVIOUS sentence doesn't "leak" into the next one's evaluation
        before_narrow = desc[max(0, m.start() - 45): m.start()]
        boundary = max(before_narrow.rfind("."), before_narrow.rfind("!"), before_narrow.rfind("\n"))
        if boundary != -1:
            before_narrow = before_narrow[boundary + 1:]
        if re.search(COMPANY_HISTORY_RE, before_narrow, re.I):
            continue  # this is about the company, not the candidate
        ctx = before + after
        if re.search(r"experience|досвід|commercial|комерц|професійн|proficien|development|розробк", ctx, re.I):
            n = int(m.group(1))
            if n <= 15:
                best = n if best is None else max(best, n)
    return best


def is_closed(title, desc):
    return bool(re.search(CLOSED_TEXT, title + " " + desc, re.I))


def extract_company(title, desc):
    """Rough heuristic: 'Job Title at Company' in the title, or 'Company: X' in the description.
    When unsure — better None than showing a wrong name."""
    m = COMPANY_AT_RE.search(title.strip())
    if m:
        return m.group(1).strip(" .")
    m = COMPANY_LABEL_RE.search(desc[:600])
    if m:
        return m.group(1).strip(" .")
    return None


def evaluate(profile, feed_must_text, item):
    title, desc = item["title"], item["desc"]
    if is_closed(title, desc):
        return None
    if re.search(GLOBAL_EXCLUDE, title, re.I):
        return None
    if profile.get("exclude_title") and re.search(profile["exclude_title"], title, re.I):
        return None
    if profile.get("must_title") and not re.search(profile["must_title"], title, re.I):
        return None
    if feed_must_text and not re.search(feed_must_text, title + " " + desc, re.I):
        return None
    yrs = years_required(desc)
    if profile.get("max_years") and yrs and yrs > profile["max_years"]:
        return None
    meta = {"years": yrs, "company": extract_company(title, desc)}
    if profile.get("resume_key") == "Embedded":
        meta["location_tag"] = embedded_location_tag(title, desc)
    return meta


def apply_link(link):
    if "dou.ua" in link:
        base = link.split("?")[0]
        return base + "#reply-btn-id"
    return link


def is_priority(title, desc):
    return bool(re.search(PRIORITY_TEXT, title + " " + desc, re.I))


def embedded_location_tag(title, desc):
    """Embedded profile only: "lviv_remote" (Lviv or remote — priority), "kyiv" (just a badge,
    no priority), or None (location not mentioned / something else)."""
    text = f"{title} {desc[:600]}"
    if re.search(EMBEDDED_PRIORITY_LOCATION_RE, text, re.I):
        return "lviv_remote"
    if re.search(EMBEDDED_KYIV_LOCATION_RE, text, re.I):
        return "kyiv"
    return None


def find_salary(title, desc):
    m = SALARY_RE.search(title) or SALARY_RE.search(desc[:400])
    return m.group(0).strip() if m else None


def find_deadline(desc):
    m = DEADLINE_RE.search(desc[:1500])
    return m.group(1).strip() if m else None


def job_priority_and_location(job):
    """Returns (priority, location_tag) for a cached job (st["jobs"][jid]). New jobs already
    have these fields saved by send_one(); for OLD ones saved before this feature existed (the
    "priority"/"location_tag" keys are simply missing from the dict) — computes them on the fly
    from title+desc+resume_key, so ⭐/🏙 and priority sorting work retroactively too, with no
    separate state migration needed."""
    if "priority" in job:
        return job.get("priority", False), job.get("location_tag")
    title, desc, resume_key = job.get("title") or "", job.get("desc") or "", job.get("resume_key")
    loc_tag = embedded_location_tag(title, desc) if resume_key == "Embedded" else None
    priority = is_priority(title, desc) or loc_tag == "lviv_remote" or resume_key == "iOS"
    return priority, loc_tag


def job_badge(job):
    """⭐ for priority jobs (AI-agentic, iOS, or Embedded Lviv/remote), 🏙 for Embedded Kyiv —
    purely a visual marker in /pending, cards and checklists, doesn't affect filtering."""
    priority, loc_tag = job_priority_and_location(job)
    if priority:
        return "⭐ "
    if loc_tag == "kyiv":
        return "🏙 "
    return ""


def format_age(age_h):
    """Renders an age in hours as a short "{N}h"/"{N}d"-style string in the bot's language —
    hours under 48, days otherwise. Shared by /pending, /seen and the card view."""
    return t("age_hours", n=int(age_h)) if age_h < 48 else t("age_days", n=int(age_h / 24))


def fmt_message(labels, src, item, meta, priority=False):
    title = html.escape(item["title"])
    star = "⭐ " if priority else ""
    # labels are profile names (e.g. "🐍 Python (Junior, <2 years)") and may contain "<"/">" —
    # unescaped, Telegram treats that as an unsupported HTML tag and rejects the WHOLE push
    labels_str = html.escape(" · ".join(labels))
    lines = [f"{star}{labels_str}  <i>({src})</i>", f"<b>{title}</b>"]
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


# ───────────────────────── PUSHES ─────────────────────────


def tg_token():
    return os.environ.get("TELEGRAM_BOT_TOKEN")


def tg_chat():
    return os.environ.get("TELEGRAM_CHAT_ID")


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


def notify(jid, labels, src, item, meta, dry, resume_key, priority=False):
    url = apply_link(item["link"])
    text = fmt_message(labels, src, item, meta, priority=priority)
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


# ───────────────────────── STATE (state.json) ─────────────────────────


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:  # noqa: BLE001
        return {"seen": {}, "jobs": {}, "initialized": False, "tg_offset": 0}


def save_state(st):
    cutoff = time.time() - 45 * 86400
    st["seen"] = {k: v for k, v in st["seen"].items() if v > cutoff}
    jcut = time.time() - JOBS_CACHE_DAYS * 86400
    st["jobs"] = {k: v for k, v in st.get("jobs", {}).items() if v.get("ts", 0) > jcut}
    ecut = time.time() - 60 * 86400
    st["events"] = [e for e in st.get("events", []) if e.get("ts", 0) > ecut]
    scut = time.time() - SEEN_LOG_DAYS * 86400
    st["silent_seen_log"] = [e for e in st.get("silent_seen_log", []) if e.get("ts", 0) > scut]
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False))


def state_update(fn):
    """Atomically: load state, let fn(st) mutate it, save it."""
    with STATE_LOCK:
        st = load_state()
        result = fn(st)
        save_state(st)
        return result


# ───────────────────────── SETTINGS (stored in state.json → included in backups) ─────────────────────────
# These keys can be changed right from Telegram (/set <key> <value>) without redeploying on
# Render — the value is written into state.json under "settings", so it survives a restart and
# is included in backups. The default is the same value that used to come only from an env var
# (which still works as the initial default).
SETTINGS_SCHEMA = {
    "reminder_hours": (float, REMINDER_HOURS, t("setting_desc_reminder_hours")),
    "quiet_hours_start": (int, QUIET_HOURS_START, t("setting_desc_quiet_hours_start")),
    "quiet_hours_end": (int, QUIET_HOURS_END, t("setting_desc_quiet_hours_end")),
    "stats_period_days": (int, STATS_PERIOD_DAYS, t("setting_desc_stats_period_days")),
    "backup_interval_hours": (float, BACKUP_INTERVAL_HOURS, t("setting_desc_backup_interval_hours")),
    "pending_list_limit": (int, PENDING_LIST_LIMIT, t("setting_desc_pending_list_limit")),
    "pending_cards_limit": (int, PENDING_CARDS_LIMIT, t("setting_desc_pending_cards_limit")),
    "seen_list_limit": (int, SEEN_LIST_LIMIT, t("setting_desc_seen_list_limit")),
    "source_jooble": (int, 0, t("setting_desc_source_jooble")),
    "source_remoteok": (int, 0, t("setting_desc_source_remoteok")),
    "source_workua": (int, 0, t("setting_desc_source_workua")),
}

# Settings that are strictly on/off (0 or 1), not an arbitrary number — set_setting() below
# rejects anything else for these.
BOOL_SETTINGS = {"source_jooble", "source_remoteok", "source_workua"}


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
    rows = [[{"text": t("profiles_delete_btn", label=label),
              "callback_data": f"delprof|{zlib.crc32(label.encode())}"}]
            for label in profiles]
    return {"inline_keyboard": rows} if rows else None


# In-memory only — an interrupted wizard (bot restart mid-flow) is simply abandoned, which is
# fine for a single-user bot; nothing of value is lost (the profile isn't saved until the final
# confirm step).
PROFILE_WIZARD = {}

PROFILE_WIZARD_STEPS = ["label", "resume_key", "feed_keywords", "must_keywords",
                        "exclude_keywords", "exclude_senior", "max_years"]


def start_profile_wizard(chat_id):
    PROFILE_WIZARD[chat_id] = {"step": 0, "data": {}}
    send_telegram_plain(chat_id, t("profwiz_start") + "\n\n" + t("profwiz_ask_label"))


def cancel_profile_wizard(chat_id):
    PROFILE_WIZARD.pop(chat_id, None)
    send_telegram_plain(chat_id, t("profwiz_cancelled"))


def handle_profile_wizard_text(chat_id, raw_text):
    """Returns True if `raw_text` was consumed as an answer in an ongoing /addprofile wizard for
    this chat (so the normal command dispatch in poll_telegram_loop should skip it)."""
    wiz = PROFILE_WIZARD.get(chat_id)
    if wiz is None:
        return False
    if raw_text.lower() in ("/cancel", "скасувати", "cancel"):
        cancel_profile_wizard(chat_id)
        return True
    step = PROFILE_WIZARD_STEPS[wiz["step"]]
    text = raw_text.strip()

    if step == "label":
        if not text:
            send_telegram_plain(chat_id, t("profwiz_ask_label"))
            return True
        if text in get_profiles():
            send_telegram_plain(chat_id, t("profwiz_label_taken", label=text))
            return True
        wiz["data"]["label"] = text
        wiz["step"] += 1
        send_telegram_plain(chat_id, t("profwiz_ask_resume_key"))
        return True

    if step == "resume_key":
        wiz["data"]["resume_key"] = text or wiz["data"]["label"]
        wiz["step"] += 1
        send_telegram_plain(chat_id, t("profwiz_ask_feed_keywords"))
        return True

    if step == "feed_keywords":
        kws = [k for k in (p.strip() for p in text.split(",")) if k]
        if not kws:
            send_telegram_plain(chat_id, t("profwiz_ask_feed_keywords"))
            return True
        wiz["data"]["feed_keywords"] = kws
        wiz["step"] += 1
        send_telegram_plain(chat_id, t("profwiz_ask_must_keywords"))
        return True

    if step == "must_keywords":
        wiz["data"]["must_keywords"] = [] if text == "-" else [k.strip() for k in text.split(",") if k.strip()]
        wiz["step"] += 1
        send_telegram_plain(chat_id, t("profwiz_ask_exclude_keywords"))
        return True

    if step == "exclude_keywords":
        wiz["data"]["exclude_keywords"] = [] if text == "-" else [k.strip() for k in text.split(",") if k.strip()]
        wiz["step"] += 1
        send_telegram_plain(chat_id, t("profwiz_ask_exclude_senior"),
                             buttons=[[{"text": "✅ " + t("profwiz_yes"), "callback_data": "profwiz_senior|yes"},
                                       {"text": "❌ " + t("profwiz_no"), "callback_data": "profwiz_senior|no"}]])
        return True

    if step == "exclude_senior":
        # handled via inline buttons (profwiz_senior|yes|no callback), not free text — but accept
        # a typed yes/no too, in case someone answers by typing instead of tapping the button.
        yes = text.lower() in ("так", "yes", "y", "т")
        _profile_wizard_set_senior_and_advance(chat_id, yes)
        return True

    if step == "max_years":
        if text == "-":
            wiz["data"]["max_years"] = None
        else:
            try:
                wiz["data"]["max_years"] = int(text)
            except ValueError:
                send_telegram_plain(chat_id, t("profwiz_ask_max_years"))
                return True
        _finish_profile_wizard(chat_id)
        return True

    return True


def _profile_wizard_set_senior_and_advance(chat_id, yes):
    wiz = PROFILE_WIZARD.get(chat_id)
    if wiz is None:
        return
    wiz["data"]["exclude_senior"] = yes
    wiz["step"] += 1
    send_telegram_plain(chat_id, t("profwiz_ask_max_years"))


def _finish_profile_wizard(chat_id):
    wiz = PROFILE_WIZARD.pop(chat_id, None)
    if wiz is None:
        return
    profile = build_profile_from_wizard(wiz["data"])
    add_profile(wiz["data"]["label"], profile)
    send_telegram_plain(chat_id, t("profwiz_saved", label=wiz["data"]["label"],
                                    n_keywords=len(profile["keywords"])))


# ───────────────────────── COLLECTING JOBS ─────────────────────────


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


def _collect_item(found, label, prof, must_text, item, src):
    if not item["link"]:
        return
    meta = evaluate(prof, must_text, item)
    if meta is None:
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
    """Returns {id: {item, src, labels, meta, resume_key}} — jobs matching ≥1 profile. Loops
    every profile's "keywords" against every active provider in sources.PROVIDERS (DOU/Djinni
    are always active; Jooble/RemoteOK/Work.ua only when their /set source_* toggle is on) —
    see sources/__init__.py for what a provider is and how to add one."""
    found = {}
    fetched = {}
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
                    _collect_item(found, label, prof, must_text, item, provider.name)
    return dedup_cross_site(found)


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


def mark_seen(st, jid, rec=None):
    st["seen"][jid] = time.time()
    for other in (rec or {}).get("dup_ids", []):
        st["seen"][other] = time.time()


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
                rec["resume_key"], priority=rec["priority"])
    if ok and not dry:
        mark_seen(st, jid, rec)
        st.setdefault("events", []).append({
            "ts": time.time(), "type": "sent", "resume_key": rec["resume_key"],
        })
    return ok


def run_once(dry=False):
    st = load_state()
    found = collect()
    now = datetime.now(timezone.utc)
    fresh = []
    for jid, rec in found.items():
        pub = rec["item"]["pub"]
        if pub and now - pub > timedelta(days=MAX_AGE_DAYS):
            if jid not in st["seen"]:
                mark_seen_silent(st, jid, rec, t("reason_too_old", days=MAX_AGE_DAYS))
            continue
        if jid not in st["seen"]:
            fresh.append((jid, rec))
    # priority jobs (AI agentic / Claude Code etc.) go first in the batch; within a group — oldest to newest
    fresh.sort(key=lambda x: (0 if x[1]["priority"] else 1, x[1]["item"]["pub"] or now))

    first_run = not st.get("initialized")
    if first_run and len(fresh) > FIRST_RUN_LIMIT:
        for jid, rec in fresh[:-FIRST_RUN_LIMIT]:
            mark_seen_silent(st, jid, rec, t("reason_first_run_limit", limit=FIRST_RUN_LIMIT))
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


# ───────────────────────── RESUME TAILORING (Claude API + PDF) ─────────────────────────

RESUME_SYSTEM_PROMPT = """Ти допомагаєш адаптувати резюме кандидата під конкретну вакансію.

СУВОРІ ПРАВИЛА:
- Нічого не вигадуй: не додавай компаній, дат, посад, технологій чи цифр, яких нема в базовому
  резюме. Можна лише переформульовувати, підсвічувати релевантне, змінювати порядок і скорочувати.
- Контакти (email/телефон/локацію) залишай без змін.
- Заголовок (## Title) — переформулюй під назву вакансії, але чесно, без брехні про рівень.
- Якщо в базовому резюме є прямий застережний коментар (наприклад, що досвід переважно з
  pet-проєкту, а не production) — обов'язково збережи цю чесність, не приховуй і не применшуй.
- Пиши резюме англійською, якщо вакансія англійською; українською — якщо вакансія українською.
- Обсяг — приблизно як в оригіналі (одна сторінка A4), без води.

ФОРМАТ ВИВОДУ — ЛИШЕ ось такий плейн-текст з розміткою, без жодних інших коментарів до чи після:

# <Ім'я Прізвище>
## <Заголовок під вакансію>
<email> | <телефон, якщо є> | <локація>

### Summary
<2-4 речення>

### Skills
- <навичка>: <короткий деталь>
- <навичка>: <короткий деталь>

### Experience
**<Посада> | <Компанія> | <Дати>**
- <буллет>
- <буллет>

**<Посада> | <Компанія> | <Дати>**
- <буллет>

### Education
- <ступінь> | <навчальний заклад> | <дати>
"""


def call_claude(system_prompt, user_prompt, max_tokens=1600):
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY не задано")
    body = json.dumps({
        "model": ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }).encode()
    raw = http(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        timeout=60, retries=1,
    )
    data = json.loads(raw)
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    text = "".join(parts).strip()
    if not text:
        raise RuntimeError(f"Порожня відповідь Claude API: {raw[:300]}")
    return text


def adapt_resume(resume_key, job_title, job_desc):
    base = BASE_RESUMES.get(resume_key)
    if not base:
        raise RuntimeError(f"Немає базового резюме для профілю {resume_key}")
    user_prompt = (
        f"ВАКАНСІЯ:\nНазва: {job_title}\n\nОпис:\n{job_desc[:5000]}\n\n"
        f"БАЗОВЕ РЕЗЮМЕ КАНДИДАТА:\n{base}\n\n"
        "Адаптуй базове резюме під цю вакансію за форматом і правилами з системного промпту."
    )
    return call_claude(RESUME_SYSTEM_PROMPT, user_prompt)


def parse_resume_markup(text):
    """Lightweight markdown-like markup -> list of blocks for reportlab."""
    blocks = []
    section = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            blocks.append(("space", None))
            continue
        if line.startswith("# "):
            blocks.append(("name", line[2:].strip()))
        elif line.startswith("## "):
            blocks.append(("title", line[3:].strip()))
        elif line.startswith("### "):
            section = line[4:].strip().lower()
            blocks.append(("section", line[4:].strip()))
        elif line.startswith("- "):
            blocks.append(("bullet", line[2:].strip()))
        elif line.startswith("**") and line.endswith("**") and len(line) > 4:
            blocks.append(("jobhead", line.strip("*").strip()))
        elif section is None:
            blocks.append(("contact", line))
        else:
            blocks.append(("para", line))
    return blocks


def render_resume_pdf(markup_text, out_path):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem

    ACCENT = colors.HexColor("#1f4e79")
    GRAY = colors.HexColor("#444444")

    styles = {
        "name": ParagraphStyle("name", fontSize=20, leading=24, fontName="Helvetica-Bold",
                                textColor=ACCENT, spaceAfter=2),
        "title": ParagraphStyle("title", fontSize=12.5, leading=16, fontName="Helvetica-Oblique",
                                 textColor=GRAY, spaceAfter=2),
        "contact": ParagraphStyle("contact", fontSize=9.5, leading=13, textColor=GRAY, spaceAfter=8),
        "section": ParagraphStyle("section", fontSize=12, leading=16, fontName="Helvetica-Bold",
                                   textColor=ACCENT, spaceBefore=10, spaceAfter=4,
                                   borderColor=ACCENT, borderWidth=0, alignment=TA_LEFT),
        "jobhead": ParagraphStyle("jobhead", fontSize=10.5, leading=14, fontName="Helvetica-Bold",
                                   spaceBefore=6, spaceAfter=2),
        "para": ParagraphStyle("para", fontSize=10, leading=14, spaceAfter=4),
        "bullet": ParagraphStyle("bullet", fontSize=10, leading=13.5),
    }

    doc = SimpleDocTemplate(str(out_path), pagesize=A4,
                             topMargin=16 * mm, bottomMargin=14 * mm,
                             leftMargin=16 * mm, rightMargin=16 * mm)
    story = []
    bullet_buf = []

    def flush_bullets():
        nonlocal bullet_buf
        if bullet_buf:
            story.append(ListFlowable(
                [ListItem(Paragraph(html.escape(b), styles["bullet"]), leftIndent=6) for b in bullet_buf],
                bulletType="bullet", start="•", leftIndent=12, spaceAfter=4,
            ))
            bullet_buf = []

    for kind, val in parse_resume_markup(markup_text):
        if kind == "bullet":
            bullet_buf.append(val)
            continue
        flush_bullets()
        if kind == "space":
            story.append(Spacer(1, 4))
        elif kind == "name":
            story.append(Paragraph(html.escape(val), styles["name"]))
        elif kind == "title":
            story.append(Paragraph(html.escape(val), styles["title"]))
        elif kind == "contact":
            story.append(Paragraph(html.escape(val), styles["contact"]))
        elif kind == "section":
            story.append(Paragraph(html.escape(val.upper()), styles["section"]))
        elif kind == "jobhead":
            story.append(Paragraph(html.escape(val), styles["jobhead"]))
        elif kind == "para":
            story.append(Paragraph(html.escape(val), styles["para"]))
    flush_bullets()

    doc.build(story)


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


def handle_cv_request(chat_id, callback_id, jid, force=False):
    answer_callback_query(callback_id, t("toast_regenerating_resume") if force else t("toast_preparing_resume"))
    st = load_state()
    job = st.get("jobs", {}).get(jid)
    if not job:
        send_telegram_plain(chat_id, t("job_stale_in_cache"))
        return
    cached = job.get("cv_cache")
    note = ""
    if cached and not force:
        markup = cached["markup"]
        note = t("note_from_cache_no_api_call")
    else:
        if not ANTHROPIC_API_KEY:
            send_telegram_plain(chat_id, t("anthropic_key_missing_resume"))
            return
        send_telegram_plain(chat_id, t("tailoring_resume_for", title=job["title"][:80]))
        try:
            markup = adapt_resume(job["resume_key"], job["title"], job["desc"])
        except Exception as e:  # noqa: BLE001
            log("✗ handle_cv_request (adapt):", e)
            send_telegram_plain(chat_id, t("resume_adapt_error", error=e))
            return

        def _cache(st, jid=jid, markup=markup):
            j = st.get("jobs", {}).get(jid)
            if j:
                j["cv_cache"] = {"markup": markup, "ts": time.time()}
        state_update(_cache)
    try:
        tmp_pdf = Path(f"/tmp/cv_{jid.replace(':', '_')}_{int(time.time())}.pdf")
        render_resume_pdf(markup, tmp_pdf)
        safe_title = re.sub(r"[^\w\-]+", "_", job["title"])[:40]
        ok = send_telegram_document(
            chat_id, tmp_pdf, f"{APPLICANT_NAME}_CV_{safe_title}.pdf",
            caption=t("resume_caption", title=job["title"][:150], note=note),
            buttons=[[{"text": t("btn_regenerate"), "callback_data": f"cvr|{jid}"}]],
        )
        tmp_pdf.unlink(missing_ok=True)
        if not ok:
            send_telegram_plain(chat_id, t("resume_send_failed"))
    except Exception as e:  # noqa: BLE001
        log("✗ handle_cv_request (render):", e)
        send_telegram_plain(chat_id, t("resume_render_error", error=e))


COVER_LETTER_SYSTEM_PROMPT = """Ти пишеш короткий супровідний лист (cover letter) кандидата під
конкретну вакансію.

СУВОРІ ПРАВИЛА:
- Нічого не вигадуй: спирайся лише на факти з базового резюме кандидата (компанії, технології,
  роки досвіду). Не додавай того, чого нема в резюме.
- 3-4 короткі абзаци: чому кандидат підходить, 1-2 конкретні релевантні навички/досягнення з
  резюме, коротке ввічливе завершення. Без канцеляриту й порожніх кліше.
- Пиши тією мовою, якою написана вакансія (англійська → англійською, українська → українською).
- Обсяг — 120-200 слів.
- Формат виводу — лише текст листа плейн-текстом, без markdown-розмітки і без жодних коментарів
  до чи після.
"""


def generate_cover_letter(resume_key, job_title, job_desc):
    base = BASE_RESUMES.get(resume_key)
    if not base:
        raise RuntimeError(f"Немає базового резюме для профілю {resume_key}")
    user_prompt = (
        f"ВАКАНСІЯ:\nНазва: {job_title}\n\nОпис:\n{job_desc[:5000]}\n\n"
        f"БАЗОВЕ РЕЗЮМЕ КАНДИДАТА:\n{base}\n\n"
        "Напиши супровідний лист під цю вакансію за правилами із системного промпту."
    )
    return call_claude(COVER_LETTER_SYSTEM_PROMPT, user_prompt, max_tokens=500)


def handle_cl_request(chat_id, callback_id, jid, force=False):
    answer_callback_query(callback_id, t("toast_regenerating_letter") if force else t("toast_preparing_letter"))
    st = load_state()
    job = st.get("jobs", {}).get(jid)
    if not job:
        send_telegram_plain(chat_id, t("job_stale_in_cache"))
        return
    cached = job.get("cl_cache")
    note = ""
    if cached and not force:
        letter = cached["text"]
        note = t("note_from_cache")
    else:
        if not ANTHROPIC_API_KEY:
            send_telegram_plain(chat_id, t("anthropic_key_missing_letter"))
            return
        send_telegram_plain(chat_id, t("writing_letter_for", title=job["title"][:80]))
        try:
            letter = generate_cover_letter(job["resume_key"], job["title"], job["desc"])
        except Exception as e:  # noqa: BLE001
            log("✗ handle_cl_request:", e)
            send_telegram_plain(chat_id, t("letter_generate_error", error=e))
            return

        def _cache(st, jid=jid, letter=letter):
            j = st.get("jobs", {}).get(jid)
            if j:
                j["cl_cache"] = {"text": letter, "ts": time.time()}
        state_update(_cache)
    text = t("cover_letter_text", note=note, title=html.escape(job["title"][:120]), letter=html.escape(letter))
    if not send_telegram_plain(chat_id, text, buttons=[[{"text": t("btn_regenerate"), "callback_data": f"clr|{jid}"}]]):
        send_telegram_plain(chat_id, t("letter_send_failed"))


# ───────────────────────── POLLING TELEGRAM COMMANDS ─────────────────────────

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


def checklist_keyboard_rows(items):
    """items: a list of (jid, job-dict), ALREADY sorted by priority (job_priority_and_location)
    descending — the same way send_pending_checklist and send_skipped_checklist do. Builds TWO
    rows per job: a ✅/⬜ checkbox button spanning the full width (so the title doesn't get cut
    in half the way it did when "🔗 Open" split the row in two) and, below it, a row with
    "🔗 Open" and "✅ Applied" side by side (both short, so they don't squeeze the title, which
    is already on its own row). "✅ Applied" here lets you mark an application right away
    without switching to card mode, if that's where you decided to apply from. The checkbox
    shows ✅ if the job is CURRENTLY marked "not interested", otherwise ⬜ (+ a ⭐/🏙 badge).
    Before the priority group and before the rest, it inserts a non-clickable
    (callback_data "noop") header row — so the priority group (Lviv/remote, iOS, AI) is visually
    separated from the rest, and you can immediately see whether there's anything there before
    going through the rest. Shared by /pending (where everything starts ⬜) and /skipped (where
    everything starts ✅, since that's exactly the "not interested" list) — so the same button
    (callback_data "pchk|<jid>") works the same way in both directions: mark or unmark."""
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
        mark = "✅ " if j.get("not_interested") else "⬜ "
        badge = "⭐ " if priority else ("🏙 " if loc_tag == "kyiv" else "")
        title = (mark + badge + (j.get("title") or "?"))[:60]
        rows.append([{"text": title, "callback_data": f"pchk|{jid}"}])
        rows.append([
            {"text": t("checklist_btn_open"), "url": apply_link(j.get("link", ""))},
            {"text": t("checklist_btn_applied"), "callback_data": f"pchk_applied|{jid}"},
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


def fit_checklist_to_telegram_limit(items, extra_rows_fn):
    """Builds checklist_keyboard_rows(items) + extra_rows_fn(items) (buttons that depend on the
    current set — e.g. "Dismiss all 'Other'" (N)) + "Done" at the end. If the serialized
    keyboard is too big for Telegram, it progressively drops jobs from the END of the list
    (items is already sorted priority-first, so the least-priority ones go first) and rebuilds,
    until it fits — so the user always sees a working list, just a shorter one, rather than an
    error. Returns (shown, rows) — shown can be shorter than items even if items was already
    within pending_cards_limit."""
    shown = list(items)
    while True:
        rows = checklist_keyboard_rows(shown)
        done_row = rows.pop()
        full_rows = rows + extra_rows_fn(shown) + [done_row]
        size = len(json.dumps({"inline_keyboard": full_rows}, ensure_ascii=False).encode("utf-8"))
        if size <= MAX_KEYBOARD_BYTES or len(shown) <= 1:
            return shown, full_rows
        shown = shown[:-1]


def send_pending_checklist(chat_id, limit=None, offset=0):
    """The main /pending view: a single list with checkbox buttons (⬜/✅) and a direct link —
    one row per job — to mark "not interested" right in the same message, instead of a separate
    step through /pending -> "Mark not interested". Tapping a button toggles just its own state
    in place (editMessageReplyMarkup in the dispatch code), without resending the whole list.
    `offset` — which position in the sorted (priority-first) list this page starts from; when
    there are more jobs than fit in one message (the count limit or Telegram's byte limit), a
    "➡️ Next" button shows up at the bottom asking for the next page starting right where this
    one left off — without it you'd have to manually repeat /pending and scroll past the same
    start of the list every time. The last row switches to "card" mode (a separate message per
    job with "Applied"/"Not interested"), since the checkboxes here can only mark "not
    interested"."""
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

    shown, rows = fit_checklist_to_telegram_limit(candidates, extra_rows)
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
    """List of jobs marked "not interested" (and not yet "Applied") — with the same ⬜/✅ buttons
    as /pending, only reversed: here everything starts ✅, and you tap to UNMARK it. For the case
    where the same job got reopened (the company reposted it) and you want to apply again —
    unmarking it here immediately returns the job to "Pending" in /pending. `offset`/"➡️ Next" —
    the same pagination as in /pending, for a long "not interested" list."""
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
    shown, rows = fit_checklist_to_telegram_limit(candidates, lambda cur_shown: [])
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


def is_authorized(chat_id):
    """This bot is personal — it only responds to its owner (TELEGRAM_CHAT_ID); it doesn't react
    at all to any other chat/command (someone messaged the bot directly, knowing its username),
    so no outsider can read the jobs or, worse, upload a file via /restore and overwrite the
    state."""
    owner = tg_chat()
    return bool(owner) and str(chat_id) == str(owner)


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
                        # "✅ Applied" right from the checklist (/pending or /skipped) — so there's
                        # no need to switch to card mode when applying straight from here.
                        jid = data.split("|", 1)[1]
                        mark_applied(jid)
                        answer_callback_query(cq["id"], t("toast_marked_applied"))
                        markup = cq["message"].get("reply_markup") or {}
                        kb = markup.get("inline_keyboard", [])
                        new_kb = []
                        for row in kb:
                            if any(b.get("callback_data") == data for b in row):
                                # this row ("🔗 Open" + "✅ Applied") and the previous one (the
                                # checkbox row with the title) belong to this job — remove both
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
        if send_telegram_plain(chat, text):
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
    text = t("weekly_digest_header") + build_stats_text()
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


def send_state_backup(chat_id, note=""):
    if not STATE_FILE.exists():
        send_telegram_plain(chat_id, t("no_state_to_backup"))
        return False
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


BACKUP_STARTUP_DELAY_SEC = 90  # give the first run_once time to fill state.json before backing up

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
    .json) is sent into the chat — restores state.json from it."""
    filename = (document.get("file_name") or "").lower()
    if not (filename.startswith("state") and filename.endswith(".json")):
        return  # not one of our backups — ignore silently
    send_telegram_plain(chat_id, t("restoring_state_from", filename=document.get('file_name')))
    try:
        raw = fetch_telegram_file(document["file_id"])
        data = json.loads(raw)
        if not isinstance(data, dict) or "jobs" not in data or "seen" not in data:
            raise ValueError(t("restore_invalid_file"))
        with STATE_LOCK:
            STATE_FILE.write_text(raw)
        send_telegram_plain(
            chat_id,
            t("state_restored", jobs=len(data.get('jobs', {})), seen=len(data.get('seen', {}))),
        )
    except Exception as e:  # noqa: BLE001
        log("✗ handle_restore_document:", e)
        send_telegram_plain(chat_id, t("restore_failed", error=e))


def restore_from_pinned_backup():
    """Called once at startup (--loop). If the local state.json is empty (typical for Render
    Free — the disk isn't persistent and gets wiped on every restart/redeploy), looks for the
    latest pinned backup in the chat on its own (getChat -> pinned_message, which survives a bot
    restart, unlike getUpdates) and restores the state from it — no need to manually forward the
    file every time."""
    token, chat = tg_token(), tg_chat()
    if not (token and chat):
        return
    st = load_state()
    if st.get("jobs") or st.get("seen"):
        return  # local state isn't empty — the disk wasn't wiped, nothing to restore
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
        with STATE_LOCK:
            STATE_FILE.write_text(backup_raw)
        log(f"auto-restore: state restored from the pinned backup "
            f"({len(data.get('jobs', {}))} jobs, {len(data.get('seen', {}))} seen)")
        send_telegram_plain(
            chat,
            t("auto_restored", jobs=len(data.get('jobs', {})), seen=len(data.get('seen', {}))),
        )
    except Exception as e:  # noqa: BLE001
        log("✗ restore_from_pinned_backup:", e)


# ───────────────────────── HEALTH SERVER (Render) ─────────────────────────


def start_health_server():
    """Minimal HTTP endpoint for a Render Web Service (PORT) + UptimeRobot pings."""
    port = os.environ.get("PORT")
    if not port:
        return

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"jobbot ok")

        do_HEAD = do_GET  # noqa: N815

        def log_message(self, *a):
            pass

    srv = HTTPServer(("0.0.0.0", int(port)), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log(f"health server on port {port}")


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
