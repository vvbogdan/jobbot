# -*- coding: utf-8 -*-
"""Djinni — https://djinni.co, public RSS, one feed per primary_keyword, no login required."""
import urllib.parse

from net import http

from ._base import Provider
from ._rss import parse_rss

URL = "https://djinni.co/jobs/rss/?primary_keyword={}"

# Djinni only filters by primary_keyword for a fixed, undocumented set of tags. Give it one it
# doesn't recognize (confirmed for these — checked live, 2026-10-05) and it silently serves its
# full, completely unfiltered "latest jobs" feed instead of an empty result or an error — so
# every job on the site (Sales Manager, SEO, Media Buyer, ...) becomes a candidate, with only the
# profile's must_text regex standing between that firehose and a push. A new unrelated word or
# idiom matching must_text (e.g. "User Acquisition Manager" matching "драйвер" via "драйвер
# росту", or "Product Manager" matching "embedded" via unrelated marketing copy) slips through
# periodically — not a filter bug each time so much as this feed being structurally unsafe to
# query. Keywords confirmed to hit this fallback: don't even ask Djinni for them. (DOU doesn't
# have this problem — its category param returns a real, if sometimes thin, result for all of
# these — so they stay valid keywords there, just skipped here.)
_NOT_A_REAL_DJINNI_TAG = frozenset({"linux", "mobile", "backend", "hardware", "robotics", "iot"})


class DjinniProvider(Provider):
    name = "Djinni"

    def fetch(self, keyword):
        if keyword.strip().lower() in _NOT_A_REAL_DJINNI_TAG:
            return []
        return parse_rss(http(URL.format(urllib.parse.quote(keyword))))


provider = DjinniProvider()
