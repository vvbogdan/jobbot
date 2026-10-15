# -*- coding: utf-8 -*-
"""Unit tests for the pure, side-effect-free helpers in jobbot.py — filtering, id/fingerprint
logic, and the "seen" bookkeeping used for reopen-detection. Deliberately skips anything that
talks to Telegram, Anthropic, Firebase, or the job feeds (network calls) — those aren't
exercised by this suite, only the regex/logic helpers that decide which jobs get through.
"""
from datetime import datetime, timedelta, timezone

import jobbot


def make_item(title="", desc="", pub=None, link="https://dou.ua/vacancies/123/"):
    return {"title": title, "desc": desc, "pub": pub, "link": link}


# ───────────────────────── job_id ─────────────────────────

def test_job_id_dou():
    assert jobbot.job_id("https://jobs.dou.ua/vacancies/123456/") == "dou:123456"


def test_job_id_djinni():
    assert jobbot.job_id("https://djinni.co/jobs/987654-python-developer/") == "dj:987654"


def test_job_id_workua():
    assert jobbot.job_id("https://www.work.ua/jobs/4567890/") == "workua:4567890"


def test_job_id_falls_back_to_full_link_for_jooble_remoteok():
    link = "https://remoteok.com/remote-jobs/123-python-dev?ref=abc"
    assert jobbot.job_id(link) == "https://remoteok.com/remote-jobs/123-python-dev"


# ───────────────────────── normalize_title / desc_fingerprint ─────────────────────────

def test_normalize_title_strips_punctuation_and_case():
    assert jobbot.normalize_title("Python Developer (Middle)!") == "python developer middle"


def test_desc_fingerprint_none_for_short_text():
    assert jobbot.desc_fingerprint("too short") is None


def test_desc_fingerprint_same_for_near_identical_text():
    base = "We are looking for a Python developer. " * 10
    assert jobbot.desc_fingerprint(base) == jobbot.desc_fingerprint(base.upper())


def test_desc_fingerprint_differs_for_different_text():
    a = "We are looking for a Python developer. " * 10
    b = "We are looking for a Java developer. " * 10
    assert jobbot.desc_fingerprint(a) != jobbot.desc_fingerprint(b)


# ───────────────────────── years_required ─────────────────────────

def test_years_required_finds_candidate_requirement():
    desc = "We expect 3+ years of commercial development experience with Python."
    assert jobbot.years_required(desc) == 3


def test_years_required_ignores_company_history():
    desc = "Our company has been on the market for 12 years. No experience required from you."
    assert jobbot.years_required(desc) is None


def test_years_required_none_when_not_mentioned():
    assert jobbot.years_required("Great team, flexible hours.") is None


# ───────────────────────── is_closed ─────────────────────────

def test_is_closed_detects_closed_phrase():
    assert jobbot.is_closed("Python Developer", "Вакансія закрита, дякуємо за відгуки.")


def test_is_closed_false_for_open_posting():
    assert not jobbot.is_closed("Python Developer", "We are hiring now, apply today.")


# ───────────────────────── find_salary / find_deadline ─────────────────────────

def test_find_salary_detects_range():
    assert jobbot.find_salary("Python Developer", "Salary: $2000 - $3000") == "$2000 - $3000"


def test_find_salary_none_when_absent():
    assert jobbot.find_salary("Python Developer", "Great team and projects.") is None


def test_find_deadline_detects_date():
    assert jobbot.find_deadline("Applications close by 10/20/2026.") is not None


# ───────────────────────── evaluate (uses config.PROFILES) ─────────────────────────

def test_evaluate_rejects_closed_job():
    profile = jobbot.PROFILES["🐍 Python (Junior, до 2 років)"]
    item = make_item(title="Python Developer", desc="Вакансія закрита.")
    meta, reason = jobbot.evaluate(profile, None, item)
    assert meta is None
    assert reason == "closed"


def test_evaluate_rejects_global_exclude_title():
    profile = jobbot.PROFILES["🐍 Python (Junior, до 2 років)"]
    item = make_item(title="QA Engineer (Python)", desc="Manual testing, Python scripts.")
    meta, reason = jobbot.evaluate(profile, None, item)
    assert meta is None
    assert reason == "global_exclude"


def test_evaluate_rejects_senior_for_python_profile():
    profile = jobbot.PROFILES["🐍 Python (Junior, до 2 років)"]
    item = make_item(title="Senior Python Developer", desc="5+ years required.")
    meta, reason = jobbot.evaluate(profile, None, item)
    assert meta is None
    assert reason == "exclude_title"


def test_evaluate_rejects_too_many_years_for_python_profile():
    profile = jobbot.PROFILES["🐍 Python (Junior, до 2 років)"]
    item = make_item(title="Python Developer", desc="3+ years of commercial experience required.")
    meta, reason = jobbot.evaluate(profile, None, item)
    assert meta is None
    assert reason == "max_years"


def test_evaluate_accepts_matching_job():
    profile = jobbot.PROFILES["🐍 Python (Junior, до 2 років)"]
    item = make_item(title="Python Developer", desc="A great opportunity for a junior.")
    meta, reason = jobbot.evaluate(profile, None, item)
    assert reason is None
    assert meta is not None


def test_evaluate_ios_requires_must_title_keyword():
    profile = jobbot.PROFILES["🍎 iOS (Senior)"]
    item = make_item(title="Backend Developer", desc="Python and Django.")
    meta, reason = jobbot.evaluate(profile, None, item)
    assert reason == "must_title"


# ───────────────────────── seen/reopen bookkeeping ─────────────────────────

def test_seen_ts_and_pub_support_new_dict_shape():
    entry = {"ts": 1000.0, "pub": 2000.0}
    assert jobbot._seen_ts(entry) == 1000.0
    assert jobbot._seen_pub(entry) == 2000.0


def test_seen_ts_supports_legacy_float_shape():
    # Before the "reopened" feature, st["seen"][jid] was a bare float (time.time()).
    assert jobbot._seen_ts(1234.5) == 1234.5
    assert jobbot._seen_pub(1234.5) is None


def test_mark_seen_stores_pub_epoch():
    st = {"seen": {}}
    pub_dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rec = {"item": {"pub": pub_dt}}
    jobbot.mark_seen(st, "dou:1", rec)
    entry = st["seen"]["dou:1"]
    assert entry["pub"] == pub_dt.timestamp()


def test_mark_seen_without_rec_leaves_pub_none():
    st = {"seen": {}}
    jobbot.mark_seen(st, "dou:1")
    assert st["seen"]["dou:1"]["pub"] is None


# ───────────────────────── Firebase null-truncation self-heal ─────────────────────────

def test_repair_truncated_keyword_pairs_fixes_1element_lists():
    profiles = {"iOS": {"keywords": [["iOS"], ["Mobile", None]]}}
    changed = jobbot._repair_truncated_keyword_pairs(profiles)
    assert changed is True
    assert profiles["iOS"]["keywords"][0] == ["iOS", None]


def test_repair_truncated_keyword_pairs_noop_on_healthy_data():
    profiles = {"iOS": {"keywords": [["iOS", None], ["Mobile", "ios|swift"]]}}
    changed = jobbot._repair_truncated_keyword_pairs(profiles)
    assert changed is False
