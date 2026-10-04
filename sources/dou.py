# -*- coding: utf-8 -*-
"""DOU — https://jobs.dou.ua, public RSS, one feed per category, no login required."""
import urllib.parse

from net import http

from ._base import Provider
from ._rss import parse_rss

URL = "https://jobs.dou.ua/vacancies/feeds/?category={}"


class DouProvider(Provider):
    name = "DOU"

    def fetch(self, keyword):
        return parse_rss(http(URL.format(urllib.parse.quote(keyword))))


provider = DouProvider()
