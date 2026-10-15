# -*- coding: utf-8 -*-
"""Unit tests for commands.py's pure/isolable parts: the checklist keyboard builder (and its
Telegram-byte-limit fitting), and the text builders that only need get_setting()/load_state()
monkeypatched rather than a real state.json. Deliberately skips send_pending_cards()/
send_pending_checklist()/send_skipped_checklist()/set_bot_commands() themselves — those talk to
Telegram directly.
"""
import pytest

from bot import commands


def make_job(jid, title, priority=False, location_tag=None, link="https://dou.ua/vacancies/1/"):
    return jid, {
        "title": title, "link": link, "priority": priority, "location_tag": location_tag,
        "ts": 0,
    }


# ───────────────────────── checklist_keyboard_rows ─────────────────────────

def test_checklist_keyboard_rows_has_header_and_action_rows_per_job():
    items = [make_job("dou:1", "AI Agent Engineer", priority=True)]
    rows = commands.checklist_keyboard_rows(items, mode="pending")
    texts = [btn["text"] for row in rows for btn in row]
    assert any("⭐" in txt for txt in texts) or any("AI Agent Engineer" in txt for txt in texts)
    # title row + action row + done row = 3 rows minimum (plus the header)
    assert len(rows) >= 3


def test_checklist_keyboard_rows_pending_mode_has_not_interested_button():
    items = [make_job("dou:1", "Python Developer")]
    rows = commands.checklist_keyboard_rows(items, mode="pending")
    callback_data = [btn.get("callback_data") for row in rows for btn in row]
    assert any(cd and cd.startswith("pchk_skip|") for cd in callback_data)


def test_checklist_keyboard_rows_skipped_mode_has_undo_button():
    items = [make_job("dou:1", "Python Developer")]
    rows = commands.checklist_keyboard_rows(items, mode="skipped")
    callback_data = [btn.get("callback_data") for row in rows for btn in row]
    assert any(cd and cd.startswith("pchk_undo|") for cd in callback_data)


def test_checklist_keyboard_rows_ends_with_done_button():
    items = [make_job("dou:1", "Python Developer")]
    rows = commands.checklist_keyboard_rows(items, mode="pending")
    assert rows[-1][0]["callback_data"] == "pchk_done"


def test_checklist_keyboard_rows_separates_priority_and_other_groups():
    items = [
        make_job("dou:1", "AI Agent Engineer", priority=True),
        make_job("dou:2", "Java Developer", priority=False),
    ]
    rows = commands.checklist_keyboard_rows(items, mode="pending")
    texts = [row[0]["text"] for row in rows]
    assert commands.t("checklist_priority_header") in texts
    assert commands.t("checklist_other_header") in texts


# ───────────────────────── fit_checklist_to_telegram_limit ─────────────────────────

def test_fit_checklist_keeps_everything_when_small():
    items = [make_job(f"dou:{i}", f"Job {i}") for i in range(3)]
    shown, rows = commands.fit_checklist_to_telegram_limit(items, lambda cur: [], mode="pending")
    assert len(shown) == 3


def test_fit_checklist_drops_from_the_end_when_oversized(monkeypatch):
    monkeypatch.setattr(commands, "MAX_KEYBOARD_BYTES", 400)
    items = [make_job(f"dou:{i}", f"Job number {i} with a fairly long title to pad bytes out")
             for i in range(30)]
    shown, rows = commands.fit_checklist_to_telegram_limit(items, lambda cur: [], mode="pending")
    assert len(shown) < len(items)
    assert len(shown) >= 1


def test_fit_checklist_includes_extra_rows():
    items = [make_job("dou:1", "Job 1")]
    extra = [[{"text": "Extra button", "callback_data": "extra"}]]
    shown, rows = commands.fit_checklist_to_telegram_limit(items, lambda cur: extra, mode="pending")
    texts = [btn["text"] for row in rows for btn in row]
    assert "Extra button" in texts


# ───────────────────────── text builders (get_setting/load_state monkeypatched) ─────────────────

@pytest.fixture
def fake_settings(monkeypatch):
    settings = {"reminder_hours": 20, "stats_period_days": 14, "pending_list_limit": 10,
                "pending_cards_limit": 10, "seen_list_limit": 10}
    monkeypatch.setattr(commands, "get_setting", lambda name: settings[name])
    return settings


def test_build_help_text_mentions_reminder_hours(fake_settings):
    text = commands.build_help_text()
    assert "20" in text


def test_build_stats_text_with_no_run_yet(monkeypatch, fake_settings):
    monkeypatch.setattr(commands, "load_state", lambda: {"events": {}, "jobs": {}})
    monkeypatch.setattr(commands.collector, "LAST_RUN_STATS", None)
    text = commands.build_stats_text()
    assert isinstance(text, str) and len(text) > 0


def test_build_stats_text_counts_events_by_type(monkeypatch, fake_settings):
    events = [
        {"ts": __import__("time").time(), "type": "sent", "resume_key": "Python"},
        {"ts": __import__("time").time(), "type": "sent", "resume_key": "Python"},
        {"ts": __import__("time").time(), "type": "applied", "resume_key": "Python"},
    ]
    monkeypatch.setattr(commands, "load_state", lambda: {"events": events, "jobs": {}})
    monkeypatch.setattr(commands.collector, "LAST_RUN_STATS", None)
    text = commands.build_stats_text()
    assert "2" in text  # 2 sent


def test_build_pending_text_empty(monkeypatch, fake_settings):
    monkeypatch.setattr(commands, "load_state", lambda: {"jobs": {}})
    text = commands.build_pending_text()
    assert text == commands.t("no_pending")


def test_build_pending_text_lists_pending_jobs(monkeypatch, fake_settings):
    jobs = {"dou:1": {"title": "Python Developer", "link": "https://dou.ua/vacancies/1/",
                       "ts": 0, "applied": False, "not_interested": False, "priority": False,
                       "location_tag": None}}
    monkeypatch.setattr(commands, "load_state", lambda: {"jobs": jobs})
    text = commands.build_pending_text()
    assert "Python Developer" in text


def test_build_seen_text_empty(monkeypatch, fake_settings):
    monkeypatch.setattr(commands, "load_state", lambda: {"silent_seen_log": []})
    text = commands.build_seen_text()
    assert text == commands.t("seen_empty", days=commands.SEEN_LOG_DAYS)
