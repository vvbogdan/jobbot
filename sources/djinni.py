# -*- coding: utf-8 -*-
"""Djinni — https://djinni.co, public RSS, one feed per primary_keyword, no login required."""
import urllib.parse

from net import http

from ._base import Provider
from ._rss import parse_rss

URL = "https://djinni.co/jobs/rss/?primary_keyword={}"


class DjinniProvider(Provider):
    name = "Djinni"

    def fetch(self, keyword):
        return parse_rss(http(URL.format(urllib.parse.quote(keyword))))


provider = DjinniProvider()
