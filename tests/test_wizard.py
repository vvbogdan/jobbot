# -*- coding: utf-8 -*-
"""Unit tests for wizard.py's /addprofile conversation state machine. Monkeypatches
get_profiles()/add_profile() so these tests never touch state.json (get_profiles() seeds
state.json with config.PROFILES on first real use — exactly the kind of file-system side effect
a unit test shouldn't have), and monkeypatches PROFILE_WIZARD to a fresh dict per test so tests
can't see each other's in-progress wizards. send_telegram_plain is safe to call for real here: with
no TELEGRAM_BOT_TOKEN set (the case in this test environment), it returns None without attempting
any network call.
"""
import pytest

from bot import wizard

CHAT = 12345


@pytest.fixture(autouse=True)
def fresh_wizard_state(monkeypatch):
    monkeypatch.setattr(wizard, "PROFILE_WIZARD", {})
    monkeypatch.setattr(wizard, "get_profiles", lambda: {})


def test_start_profile_wizard_sets_step_zero():
    wizard.start_profile_wizard(CHAT)
    assert wizard.PROFILE_WIZARD[CHAT] == {"step": 0, "data": {}}


def test_cancel_profile_wizard_clears_entry():
    wizard.start_profile_wizard(CHAT)
    wizard.cancel_profile_wizard(CHAT)
    assert CHAT not in wizard.PROFILE_WIZARD


def test_handle_profile_wizard_text_ignores_chat_with_no_active_wizard():
    assert wizard.handle_profile_wizard_text(CHAT, "anything") is False


def test_handle_profile_wizard_text_cancel_keyword_stops_wizard():
    wizard.start_profile_wizard(CHAT)
    consumed = wizard.handle_profile_wizard_text(CHAT, "/cancel")
    assert consumed is True
    assert CHAT not in wizard.PROFILE_WIZARD


def test_label_step_rejects_empty_text():
    wizard.start_profile_wizard(CHAT)
    wizard.handle_profile_wizard_text(CHAT, "   ")
    assert wizard.PROFILE_WIZARD[CHAT]["step"] == 0  # didn't advance


def test_label_step_rejects_taken_label(monkeypatch):
    monkeypatch.setattr(wizard, "get_profiles", lambda: {"🐍 Python (Junior)": {}})
    wizard.start_profile_wizard(CHAT)
    wizard.handle_profile_wizard_text(CHAT, "🐍 Python (Junior)")
    assert wizard.PROFILE_WIZARD[CHAT]["step"] == 0  # didn't advance
    assert "label" not in wizard.PROFILE_WIZARD[CHAT]["data"]


def test_label_step_accepts_new_label_and_advances():
    wizard.start_profile_wizard(CHAT)
    wizard.handle_profile_wizard_text(CHAT, "My New Profile")
    wiz = wizard.PROFILE_WIZARD[CHAT]
    assert wiz["step"] == 1
    assert wiz["data"]["label"] == "My New Profile"


def test_resume_key_step_defaults_to_label_when_blank():
    wizard.start_profile_wizard(CHAT)
    wizard.handle_profile_wizard_text(CHAT, "My New Profile")
    wizard.handle_profile_wizard_text(CHAT, "")
    assert wizard.PROFILE_WIZARD[CHAT]["data"]["resume_key"] == "My New Profile"


def test_feed_keywords_step_rejects_empty_and_splits_on_comma():
    wizard.start_profile_wizard(CHAT)
    wizard.handle_profile_wizard_text(CHAT, "My New Profile")
    wizard.handle_profile_wizard_text(CHAT, "MyResume")
    wizard.handle_profile_wizard_text(CHAT, "   ")
    assert wizard.PROFILE_WIZARD[CHAT]["step"] == 2  # still waiting for feed_keywords
    wizard.handle_profile_wizard_text(CHAT, "Rust, Go")
    wiz = wizard.PROFILE_WIZARD[CHAT]
    assert wiz["data"]["feed_keywords"] == ["Rust", "Go"]
    assert wiz["step"] == 3


def test_must_and_exclude_keywords_accept_dash_as_empty():
    wizard.start_profile_wizard(CHAT)
    wizard.handle_profile_wizard_text(CHAT, "My New Profile")
    wizard.handle_profile_wizard_text(CHAT, "MyResume")
    wizard.handle_profile_wizard_text(CHAT, "Rust")
    wizard.handle_profile_wizard_text(CHAT, "-")
    wizard.handle_profile_wizard_text(CHAT, "-")
    wiz = wizard.PROFILE_WIZARD[CHAT]
    assert wiz["data"]["must_keywords"] == []
    assert wiz["data"]["exclude_keywords"] == []
    assert wiz["step"] == 5  # now waiting on exclude_senior (via buttons)


def test_full_flow_calls_add_profile_and_clears_wizard(monkeypatch):
    saved = {}
    monkeypatch.setattr(wizard, "add_profile", lambda label, profile: saved.update(
        {"label": label, "profile": profile}))

    wizard.start_profile_wizard(CHAT)
    wizard.handle_profile_wizard_text(CHAT, "My New Profile")
    wizard.handle_profile_wizard_text(CHAT, "MyResume")
    wizard.handle_profile_wizard_text(CHAT, "Rust")
    wizard.handle_profile_wizard_text(CHAT, "-")
    wizard.handle_profile_wizard_text(CHAT, "-")
    wizard.handle_profile_wizard_text(CHAT, "так")   # exclude_senior = True
    wizard.handle_profile_wizard_text(CHAT, "3")      # max_years

    assert CHAT not in wizard.PROFILE_WIZARD  # wizard finished and cleared itself
    assert saved["label"] == "My New Profile"
    assert saved["profile"]["resume_key"] == "MyResume"
    assert saved["profile"]["max_years"] == 3
    assert "senior" in saved["profile"]["exclude_title"].lower()


def test_max_years_step_rejects_non_numeric(monkeypatch):
    monkeypatch.setattr(wizard, "add_profile", lambda label, profile: None)
    wizard.start_profile_wizard(CHAT)
    wizard.handle_profile_wizard_text(CHAT, "My New Profile")
    wizard.handle_profile_wizard_text(CHAT, "MyResume")
    wizard.handle_profile_wizard_text(CHAT, "Rust")
    wizard.handle_profile_wizard_text(CHAT, "-")
    wizard.handle_profile_wizard_text(CHAT, "-")
    wizard.handle_profile_wizard_text(CHAT, "ні")  # exclude_senior = False
    wizard.handle_profile_wizard_text(CHAT, "not-a-number")
    # still in the wizard, same step — didn't crash, didn't advance/finish
    assert CHAT in wizard.PROFILE_WIZARD
    assert wizard.PROFILE_WIZARD[CHAT]["step"] == 6
