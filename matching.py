# -*- coding: utf-8 -*-
"""matching — pure, side-effect-free job-filtering/scoring logic: deciding whether a job passes
a profile's filters (evaluate), spotting the same posting reposted elsewhere (job_id,
desc_fingerprint, find_duplicate_posting), and the small cosmetic extras shown in a push/list
(salary, deadline, company name, priority badge, age). Nothing here touches the network, Telegram,
or state.json directly — it only takes plain dicts/strings in and returns plain values out, which
is exactly what tests/test_jobbot.py exercises directly.

Second extraction step of jobbot.py's split into focused modules (after telegram_api.py/
logutil.py) — see README/commit history for the rest of the plan.
"""
import hashlib
import re
import time
from datetime import datetime

from i18n import t
from config import (
    GLOBAL_EXCLUDE, PRIORITY_TEXT, EMBEDDED_PRIORITY_LOCATION_RE, EMBEDDED_KYIV_LOCATION_RE,
)

# remember a sent job's description this long, to catch the same company reposting
# near-identical text under a new vacancy id
DEDUP_FINGERPRINT_DAYS = 120

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

# Rough heuristic for the company name — better to show nothing than to make one up
COMPANY_AT_RE = re.compile(
    r"\bat\s+([A-ZА-ЯІЇЄҐ][\w&.'’\-]+(?:\s+[A-ZА-ЯІЇЄҐ0-9][\w&.'’\-]*){0,3})\s*$"
)
COMPANY_LABEL_RE = re.compile(
    r"(?:компані[яю]|компанія-замовник|company|client|employer)\s*[:\-—]\s*([A-ZА-ЯІЇЄҐ][^\n,.;|]{1,60})",
    re.I,
)

# DOU/Djinni sometimes leave a closed vacancy in the RSS feed for a while, but mark it in the text
CLOSED_TEXT = (
    r"вакансія закрит|закрито вакансі|вакансія в архіві|прийом (заявок|резюме) закрит|"
    r"більше не актуальн|вакансія неактуальн|posting (is |has been )?closed|"
    r"position (is |has been )?(closed|filled)|vacancy (is )?closed|no longer accepting|"
    r"we('| a)re no longer hiring"
)

# "Company on the market for 12 years" / "outsourcing company with over 12 years of experience"
# etc. — that's the COMPANY's history, not a requirement for the candidate. years_required()
# must ignore these.
COMPANY_HISTORY_RE = (
    r"company|компані|outsourc|outstaff|on the market|у сфер|на ринку|заснован|"
    r"founded|since (19|20)\d{2}|history|team has|our team|команда має"
)


def normalize_title(title):
    """Rough title normalization for comparing jobs across sites."""
    t_ = title.lower()
    t_ = re.sub(r"[^\w\s]", " ", t_, flags=re.UNICODE)
    t_ = re.sub(r"\s+", " ", t_).strip()
    return t_


def desc_fingerprint(desc):
    """Normalized hash of a job's description — used to catch the same company reposting
    near-identical text under a brand-new vacancy ID (title/location tweaked, body unchanged).
    Returns None for descriptions too short to fingerprint reliably (avoids false matches on
    thin/partial text from some sources)."""
    norm = re.sub(r"[^\w\s]", "", desc.lower(), flags=re.UNICODE)
    norm = re.sub(r"\s+", " ", norm).strip()
    if len(norm) < 200:
        return None
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def find_duplicate_posting(st, desc):
    """If this description's fingerprint was already sent (within DEDUP_FINGERPRINT_DAYS),
    return a human-readable date string of when; otherwise None."""
    fp = desc_fingerprint(desc)
    if not fp:
        return None
    seen = st.get("desc_fingerprints", {}).get(fp)
    if not seen:
        return None
    cutoff = time.time() - DEDUP_FINGERPRINT_DAYS * 86400
    if seen.get("ts", 0) < cutoff:
        return None
    return datetime.fromtimestamp(seen["ts"]).strftime("%d.%m")


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
    """Returns (meta, None) if the job passes every filter for this profile/keyword, or
    (None, reason) naming which filter rejected it — the reason feeds the per-run breakdown in
    /stats (section "last run") so "190 matches, 0 new" has an actual explanation instead of
    being a black box."""
    title, desc = item["title"], item["desc"]
    if is_closed(title, desc):
        return None, "closed"
    if re.search(GLOBAL_EXCLUDE, title, re.I):
        return None, "global_exclude"
    if profile.get("exclude_title") and re.search(profile["exclude_title"], title, re.I):
        return None, "exclude_title"
    if profile.get("must_title") and not re.search(profile["must_title"], title, re.I):
        return None, "must_title"
    if feed_must_text and not re.search(feed_must_text, title + " " + desc, re.I):
        return None, "must_text"
    yrs = years_required(desc)
    if profile.get("max_years") and yrs and yrs > profile["max_years"]:
        return None, "max_years"
    meta = {"years": yrs, "company": extract_company(title, desc)}
    if profile.get("resume_key") == "Embedded":
        meta["location_tag"] = embedded_location_tag(title, desc)
    return meta, None


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
