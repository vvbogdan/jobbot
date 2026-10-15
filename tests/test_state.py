# -*- coding: utf-8 -*-
"""Unit tests for the parts of state.py that don't touch state.json/Firebase directly: seen
bookkeeping, the Firebase null-truncation self-heal, profile-keyword migration/sync helpers, and
the /addprofile wizard's pure data-shaping function. Deliberately skips load_state()/save_state()/
state_update() themselves — those read/write a process-wide cache and the actual state file/
Firebase, which belongs in an integration-level check, not a unit test.
"""
from datetime import datetime, timezone

from bot import state


# ───────────────────────── seen/reopen bookkeeping ─────────────────────────

def test_seen_ts_and_pub_support_new_dict_shape():
    entry = {"ts": 1000.0, "pub": 2000.0}
    assert state._seen_ts(entry) == 1000.0
    assert state._seen_pub(entry) == 2000.0


def test_seen_ts_supports_legacy_float_shape():
    # Before the "reopened" feature, st["seen"][jid] was a bare float (time.time()).
    assert state._seen_ts(1234.5) == 1234.5
    assert state._seen_pub(1234.5) is None


def test_mark_seen_stores_pub_epoch():
    st = {"seen": {}}
    pub_dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rec = {"item": {"pub": pub_dt}}
    state.mark_seen(st, "dou:1", rec)
    entry = st["seen"]["dou:1"]
    assert entry["pub"] == pub_dt.timestamp()


def test_mark_seen_without_rec_leaves_pub_none():
    st = {"seen": {}}
    state.mark_seen(st, "dou:1")
    assert st["seen"]["dou:1"]["pub"] is None


def test_mark_seen_also_marks_dup_ids():
    st = {"seen": {}}
    rec = {"item": {"pub": None}, "dup_ids": ["dj:2"]}
    state.mark_seen(st, "dou:1", rec)
    assert "dou:1" in st["seen"]
    assert "dj:2" in st["seen"]


def test_mark_seen_silent_appends_to_log():
    st = {"seen": {}}
    rec = {"item": {"pub": None, "title": "Python Dev", "link": "https://dou.ua/x"}}
    state.mark_seen_silent(st, "dou:1", rec, "too_old")
    assert "dou:1" in st["seen"]
    assert st["silent_seen_log"][0]["reason"] == "too_old"
    assert st["silent_seen_log"][0]["title"] == "Python Dev"


# ───────────────────────── Firebase null-truncation self-heal ─────────────────────────

def test_repair_truncated_keyword_pairs_fixes_1element_lists():
    profiles = {"iOS": {"keywords": [["iOS"], ["Mobile", None]]}}
    changed = state._repair_truncated_keyword_pairs(profiles)
    assert changed is True
    assert profiles["iOS"]["keywords"][0] == ["iOS", None]


def test_repair_truncated_keyword_pairs_noop_on_healthy_data():
    profiles = {"iOS": {"keywords": [["iOS", None], ["Mobile", "ios|swift"]]}}
    changed = state._repair_truncated_keyword_pairs(profiles)
    assert changed is False


# ───────────────────────── keyword migration/sync helpers ─────────────────────────

def test_derive_keywords_from_old_feeds_prefers_feed_keywords():
    prof = {"feed_keywords": ["Python", "Django"]}
    assert state._derive_keywords_from_old_feeds(prof) == [("Python", None), ("Django", None)]


def test_derive_keywords_from_old_feeds_recovers_from_feed_urls():
    prof = {
        "feeds": [
            ("dou", "https://jobs.dou.ua/vacancies/feeds/?category=Python", None),
            ("djinni", "https://djinni.co/jobs/rss/?primary_keyword=Python", "django"),
        ]
    }
    recovered = dict(state._derive_keywords_from_old_feeds(prof))
    assert recovered == {"Python": "django"}


def test_sync_keywords_from_config_adds_missing_keyword():
    profiles = {"🐍 Python (Junior, до 2 років)": {"keywords": [["Python", None]]}}
    # config.PROFILES already has this exact profile name/keyword — nothing new to add, so this
    # just confirms a no-op doesn't crash and returns False.
    changed = state._sync_keywords_from_config(profiles)
    assert changed is False


def test_sync_keywords_from_config_ignores_unknown_profile():
    profiles = {"My Custom Profile": {"keywords": [["Rust", None]]}}
    changed = state._sync_keywords_from_config(profiles)
    assert changed is False
    assert profiles["My Custom Profile"]["keywords"] == [["Rust", None]]


# ───────────────────────── /addprofile wizard data shaping ─────────────────────────

def test_build_profile_from_wizard_basic_shape():
    data = {
        "resume_key": "Frontend",
        "feed_keywords": ["Frontend", "React"],
        "must_keywords": [],
        "exclude_keywords": ["backend"],
        "exclude_senior": False,
        "max_years": 3,
    }
    prof = state.build_profile_from_wizard(data)
    assert prof["resume_key"] == "Frontend"
    assert prof["keywords"] == [("Frontend", None), ("React", None)]
    assert prof["max_years"] == 3
    assert "backend" in prof["exclude_title"]


def test_build_profile_from_wizard_exclude_senior_adds_senior_words():
    data = {
        "resume_key": "Java",
        "feed_keywords": ["Java"],
        "must_keywords": [],
        "exclude_keywords": [],
        "exclude_senior": True,
        "max_years": None,
    }
    prof = state.build_profile_from_wizard(data)
    assert "senior" in prof["exclude_title"].lower()


# ───────────────────────── settings schema sanity ─────────────────────────

def test_settings_schema_has_expected_keys():
    expected = {
        "reminder_hours", "quiet_hours_start", "quiet_hours_end", "stats_period_days",
        "backup_interval_hours", "pending_list_limit", "pending_cards_limit",
        "seen_list_limit", "source_jooble", "source_remoteok", "source_workua", "use_firebase",
    }
    assert expected <= set(state.SETTINGS_SCHEMA)


def test_bool_settings_are_a_subset_of_schema():
    assert state.BOOL_SETTINGS <= set(state.SETTINGS_SCHEMA)
