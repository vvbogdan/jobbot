# -*- coding: utf-8 -*-
"""Unit tests for collector.py's pure/isolable parts: cross-site dedup and the quiet-hours
window check. Deliberately skips collect()/run_once() themselves — those fetch real feeds and
read/write state.json, which belongs in an integration-level check, not a unit test.
"""
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

from bot import collector


def make_rec(title, src="DOU", labels=None, priority=False):
    return {
        "item": {"title": title, "desc": "", "pub": None, "link": f"https://dou.ua/vacancies/{title}/"},
        "src": src, "labels": labels or ["🐍 Python"], "meta": {}, "resume_key": "Python",
        "priority": priority,
    }


# ───────────────────────── dedup_cross_site ─────────────────────────

def test_dedup_cross_site_merges_identical_titles_across_sources():
    found = {
        "dou:1": make_rec("Python Developer", src="DOU", labels=["🐍 Python"]),
        "dj:1": make_rec("Python Developer", src="Djinni", labels=["🟢 Node.js"]),
    }
    merged = collector.dedup_cross_site(found)
    assert len(merged) == 1
    rec = merged["dou:1"]  # DOU kept as primary (has a direct "Apply" button)
    assert sorted(rec["labels"]) == ["🐍 Python", "🟢 Node.js"]
    assert rec["src"] == "DOU + Djinni"
    assert rec["dup_ids"] == ["dj:1"]


def test_dedup_cross_site_prefers_dou_as_primary_regardless_of_order():
    found = {
        "dj:1": make_rec("Backend Engineer", src="Djinni"),
        "dou:1": make_rec("Backend Engineer", src="DOU"),
    }
    merged = collector.dedup_cross_site(found)
    assert "dou:1" in merged
    assert "dj:1" not in merged


def test_dedup_cross_site_leaves_unique_titles_alone():
    found = {
        "dou:1": make_rec("Python Developer"),
        "dou:2": make_rec("Java Developer"),
    }
    merged = collector.dedup_cross_site(found)
    assert len(merged) == 2


def test_dedup_cross_site_merges_priority_with_or():
    found = {
        "dou:1": make_rec("AI Agent Engineer", src="DOU", priority=False),
        "dj:1": make_rec("AI Agent Engineer", src="Djinni", priority=True),
    }
    merged = collector.dedup_cross_site(found)
    assert merged["dou:1"]["priority"] is True


# ───────────────────────── is_quiet_now ─────────────────────────

def test_is_quiet_now_false_when_start_equals_end(monkeypatch):
    monkeypatch.setattr(collector, "get_setting",
                         lambda name: 0 if "hours" in name else None)
    assert collector.is_quiet_now() is False


def test_is_quiet_now_true_inside_window(monkeypatch):
    if ZoneInfo is None:
        return
    now_hour = datetime.now(ZoneInfo(collector.TZ_NAME)).hour
    start, end = now_hour, (now_hour + 1) % 24

    def fake_get_setting(name):
        return {"quiet_hours_start": start, "quiet_hours_end": end}[name]

    monkeypatch.setattr(collector, "get_setting", fake_get_setting)
    assert collector.is_quiet_now() is True


def test_is_quiet_now_false_outside_window(monkeypatch):
    if ZoneInfo is None:
        return
    now_hour = datetime.now(ZoneInfo(collector.TZ_NAME)).hour
    # a 1-hour window starting 2 hours from now — guaranteed not to contain "now"
    start = (now_hour + 2) % 24
    end = (now_hour + 3) % 24

    def fake_get_setting(name):
        return {"quiet_hours_start": start, "quiet_hours_end": end}[name]

    monkeypatch.setattr(collector, "get_setting", fake_get_setting)
    assert collector.is_quiet_now() is False
