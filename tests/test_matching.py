# -*- coding: utf-8 -*-
"""Unit tests for matching.py — the pure, side-effect-free job-filtering/scoring logic
(job id/fingerprint, years-required parsing, closed-posting detection, salary/deadline
extraction, and evaluate()'s per-profile filter pipeline). Deliberately skips anything that
talks to Telegram, Anthropic, Firebase, or the job feeds — those aren't exercised by this
suite, only the regex/logic helpers that decide which jobs get through.
"""
from bot import matching
from bot.config import PROFILES


def make_item(title="", desc="", pub=None, link="https://dou.ua/vacancies/123/"):
    return {"title": title, "desc": desc, "pub": pub, "link": link}


# ───────────────────────── job_id ─────────────────────────

def test_job_id_dou():
    assert matching.job_id("https://jobs.dou.ua/vacancies/123456/") == "dou:123456"


def test_job_id_djinni():
    assert matching.job_id("https://djinni.co/jobs/987654-python-developer/") == "dj:987654"


def test_job_id_workua():
    assert matching.job_id("https://www.work.ua/jobs/4567890/") == "workua:4567890"


def test_job_id_falls_back_to_full_link_for_jooble_remoteok():
    link = "https://remoteok.com/remote-jobs/123-python-dev?ref=abc"
    assert matching.job_id(link) == "https://remoteok.com/remote-jobs/123-python-dev"


# ───────────────────────── normalize_title / desc_fingerprint ─────────────────────────

def test_normalize_title_strips_punctuation_and_case():
    assert matching.normalize_title("Python Developer (Middle)!") == "python developer middle"


def test_desc_fingerprint_none_for_short_text():
    assert matching.desc_fingerprint("too short") is None


def test_desc_fingerprint_same_for_near_identical_text():
    base = "We are looking for a Python developer. " * 10
    assert matching.desc_fingerprint(base) == matching.desc_fingerprint(base.upper())


def test_desc_fingerprint_differs_for_different_text():
    a = "We are looking for a Python developer. " * 10
    b = "We are looking for a Java developer. " * 10
    assert matching.desc_fingerprint(a) != matching.desc_fingerprint(b)


def test_find_duplicate_posting_none_without_prior_fingerprint():
    assert matching.find_duplicate_posting({}, "Some short description.") is None


# ───────────────────────── years_required ─────────────────────────

def test_years_required_finds_candidate_requirement():
    desc = "We expect 3+ years of commercial development experience with Python."
    assert matching.years_required(desc) == 3


def test_years_required_ignores_company_history():
    desc = "Our company has been on the market for 12 years. No experience required from you."
    assert matching.years_required(desc) is None


def test_years_required_none_when_not_mentioned():
    assert matching.years_required("Great team, flexible hours.") is None


# ───────────────────────── is_closed ─────────────────────────

def test_is_closed_detects_closed_phrase():
    assert matching.is_closed("Python Developer", "Вакансія закрита, дякуємо за відгуки.")


def test_is_closed_false_for_open_posting():
    assert not matching.is_closed("Python Developer", "We are hiring now, apply today.")


# ───────────────────────── find_salary / find_deadline ─────────────────────────

def test_find_salary_detects_range():
    assert matching.find_salary("Python Developer", "Salary: $2000 - $3000") == "$2000 - $3000"


def test_find_salary_none_when_absent():
    assert matching.find_salary("Python Developer", "Great team and projects.") is None


def test_find_deadline_detects_date():
    assert matching.find_deadline("Applications close by 10/20/2026.") is not None


# ───────────────────────── apply_link ─────────────────────────

def test_apply_link_adds_dou_reply_anchor():
    link = matching.apply_link("https://jobs.dou.ua/companies/acme/vacancies/1/?from=search")
    assert link == "https://jobs.dou.ua/companies/acme/vacancies/1/#reply-btn-id"


def test_apply_link_leaves_other_links_untouched():
    link = "https://djinni.co/jobs/987654-python-developer/"
    assert matching.apply_link(link) == link


# ───────────────────────── evaluate (uses config.PROFILES) ─────────────────────────

def test_evaluate_rejects_closed_job():
    profile = PROFILES["🐍 Python (Junior, до 2 років)"]
    item = make_item(title="Python Developer", desc="Вакансія закрита.")
    meta, reason = matching.evaluate(profile, None, item)
    assert meta is None
    assert reason == "closed"


def test_evaluate_rejects_global_exclude_title():
    profile = PROFILES["🐍 Python (Junior, до 2 років)"]
    item = make_item(title="QA Engineer (Python)", desc="Manual testing, Python scripts.")
    meta, reason = matching.evaluate(profile, None, item)
    assert meta is None
    assert reason == "global_exclude"


def test_evaluate_rejects_senior_for_python_profile():
    profile = PROFILES["🐍 Python (Junior, до 2 років)"]
    item = make_item(title="Senior Python Developer", desc="5+ years required.")
    meta, reason = matching.evaluate(profile, None, item)
    assert meta is None
    assert reason == "exclude_title"


def test_evaluate_rejects_too_many_years_for_python_profile():
    profile = PROFILES["🐍 Python (Junior, до 2 років)"]
    item = make_item(title="Python Developer", desc="3+ years of commercial experience required.")
    meta, reason = matching.evaluate(profile, None, item)
    assert meta is None
    assert reason == "max_years"


def test_evaluate_accepts_matching_job():
    profile = PROFILES["🐍 Python (Junior, до 2 років)"]
    item = make_item(title="Python Developer", desc="A great opportunity for a junior.")
    meta, reason = matching.evaluate(profile, None, item)
    assert reason is None
    assert meta is not None


def test_evaluate_ios_requires_must_title_keyword():
    profile = PROFILES["🍎 iOS (Senior)"]
    item = make_item(title="Backend Developer", desc="Python and Django.")
    meta, reason = matching.evaluate(profile, None, item)
    assert reason == "must_title"


# ───────────────────────── priority / badges ─────────────────────────

def test_is_priority_detects_agentic_keyword():
    assert matching.is_priority("AI Agent Engineer", "build agentic workflows")


def test_embedded_location_tag_lviv_is_priority_remote():
    assert matching.embedded_location_tag("Embedded Developer", "Location: Lviv") == "lviv_remote"


def test_embedded_location_tag_kyiv_is_not_priority():
    assert matching.embedded_location_tag("Embedded Developer", "Location: Kyiv") == "kyiv"


def test_job_badge_star_for_priority_job():
    job = {"priority": True, "location_tag": None}
    assert matching.job_badge(job) == "⭐ "


def test_job_badge_city_mark_for_embedded_kyiv():
    job = {"priority": False, "location_tag": "kyiv"}
    assert matching.job_badge(job) == "🏙 "


def test_job_badge_empty_when_neither():
    job = {"priority": False, "location_tag": None}
    assert matching.job_badge(job) == ""
