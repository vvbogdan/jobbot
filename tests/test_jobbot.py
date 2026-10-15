# -*- coding: utf-8 -*-
"""Unit tests for the pure, side-effect-free helpers that stayed in jobbot.py after the
matching/telegram_api/logutil split: "seen" bookkeeping (used for reopen-detection) and the
Firebase null-truncation self-heal. Job-filtering/scoring logic itself now lives in matching.py
— see tests/test_matching.py. Deliberately skips anything that talks to Telegram, Anthropic,
Firebase, or the job feeds (network calls).
"""
from datetime import datetime, timezone

import jobbot


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
