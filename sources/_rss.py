# -*- coding: utf-8 -*-
"""Shared RSS parsing — used by both dou.py and djinni.py (both are plain RSS feeds)."""
import html
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime

from net import strip_html


def parse_rss(xml_text):
    root = ET.fromstring(xml_text.lstrip("﻿"))
    items = []
    for it in root.iter("item"):
        g = lambda tag: (it.findtext(tag) or "").strip()  # noqa: E731
        link = g("link")
        pub = None
        if g("pubDate"):
            try:
                pub = parsedate_to_datetime(g("pubDate"))
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
            except Exception:  # noqa: BLE001
                pub = None
        items.append({
            "title": html.unescape(g("title")),
            "link": link,
            "desc": strip_html(g("description")),
            "pub": pub,
        })
    return items
