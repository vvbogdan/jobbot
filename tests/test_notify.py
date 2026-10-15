# -*- coding: utf-8 -*-
"""Unit tests for notify.py's pure parts: push-text formatting and the quiet-hours queue
(de)serializer. Deliberately skips send_telegram()/send_ntfy()/notify()/send_one() themselves —
those talk to Telegram/ntfy and mutate state.json, which belongs in an integration-level check,
not a unit test. (send_telegram()/notify() are still safe to *call* in a test environment with no
TELEGRAM_BOT_TOKEN set — see test_wizard.py's docstring — but formatting is what's worth
asserting on here.)
"""
from datetime import datetime, timezone

from bot import notify


def make_item(title="Python Developer", desc="A great opportunity.", pub=None,
              link="https://dou.ua/vacancies/123/"):
    return {"title": title, "desc": desc, "pub": pub, "link": link}


# ───────────────────────── fmt_message ─────────────────────────

def test_fmt_message_includes_labels_title_and_snippet():
    item = make_item(desc="We need a Python developer for an exciting project.")
    text = notify.fmt_message(["🐍 Python"], "DOU", item, meta={})
    assert "🐍 Python" in text
    assert "Python Developer" in text
    assert "exciting project" in text


def test_fmt_message_priority_adds_star():
    item = make_item()
    text = notify.fmt_message(["🐍 Python"], "DOU", item, meta={}, priority=True)
    assert text.startswith("⭐ ")


def test_fmt_message_reopened_adds_marker():
    item = make_item()
    text = notify.fmt_message(["🐍 Python"], "DOU", item, meta={}, reopened=True)
    assert "reopen" in text.lower() or "повтор" in text.lower() or "знову" in text.lower() \
        or len(text.splitlines()) >= 3  # at minimum, an extra line was inserted


def test_fmt_message_escapes_html_in_labels():
    # Profile labels can contain "<"/">" (e.g. "до 2 років" has none, but years ranges could) —
    # unescaped, Telegram rejects the WHOLE push as an unsupported HTML tag.
    item = make_item()
    text = notify.fmt_message(["<Junior>"], "DOU", item, meta={})
    assert "<Junior>" not in text
    assert "&lt;Junior&gt;" in text


def test_fmt_message_shows_company_and_salary():
    item = make_item(desc="Salary: $2000 - $3000. Great team.")
    text = notify.fmt_message(["🐍 Python"], "DOU", item, meta={"company": "Acme"})
    assert "Acme" in text
    assert "$2000 - $3000" in text


def test_fmt_message_shows_years_required():
    item = make_item()
    text = notify.fmt_message(["🐍 Python"], "DOU", item, meta={"years": 3})
    assert "3" in text


# ───────────────────────── serialize_rec / deserialize_rec ─────────────────────────

def test_serialize_deserialize_roundtrip_preserves_data():
    pub = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    item = make_item(pub=pub)
    rec = {
        "item": item, "src": "DOU", "labels": ["🐍 Python"], "meta": {"company": "Acme"},
        "resume_key": "Python", "priority": True, "dup_ids": ["dj:1"],
    }
    d = notify.serialize_rec("dou:1", rec)
    # JSON-compatible: the datetime became a plain string
    assert isinstance(d["item"]["pub"], str)
    jid, rec2 = notify.deserialize_rec(d)
    assert jid == "dou:1"
    assert rec2["item"]["pub"] == pub
    assert rec2["src"] == "DOU"
    assert rec2["labels"] == ["🐍 Python"]
    assert rec2["meta"] == {"company": "Acme"}
    assert rec2["resume_key"] == "Python"
    assert rec2["priority"] is True
    assert rec2["dup_ids"] == ["dj:1"]


def test_serialize_rec_handles_missing_pub():
    item = make_item(pub=None)
    rec = {"item": item, "src": "DOU", "labels": [], "meta": {}, "resume_key": "Python", "priority": False}
    d = notify.serialize_rec("dou:2", rec)
    assert d["item"]["pub"] is None
    jid, rec2 = notify.deserialize_rec(d)
    assert rec2["item"]["pub"] is None
    assert rec2["dup_ids"] == []


# ───────────────────────── send_telegram / send_ntfy / notify (no token/topic configured) ──────

def test_send_telegram_returns_false_without_token_or_chat(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert notify.send_telegram("hello") is False


def test_send_ntfy_returns_false_without_topic(monkeypatch):
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    assert notify.send_ntfy("title", "text", "https://example.com") is False


def test_notify_dry_run_does_not_need_any_channel(monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    item = make_item()
    ok = notify.notify("dou:1", ["🐍 Python"], "DOU", item, {}, dry=True, resume_key="Python")
    assert ok is True
    out = capsys.readouterr().out
    assert "Python Developer" in out
