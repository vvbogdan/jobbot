# -*- coding: utf-8 -*-
"""Work.ua — no public RSS/API (it had RSS back in 2009; that's gone, /rss/ is a 404 today), so
this is an HTML scraper instead: more fragile than every other source here. Off by default
(setting_name). If work.ua changes its page markup, this can start quietly returning nothing,
without tripping FEED_FAIL_THRESHOLD (the HTTP request itself still succeeds). Keyed off the
job URL pattern (/jobs/<id>/), the most stable part of the page — not any CSS class name.
Needs beautifulsoup4 (see requirements.txt). See README section 15."""
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

from net import http

from ._base import Provider

_JOB_LINK_RE = re.compile(r"/jobs/\d+/?($|[?#])")
_RELATIVE_AGE_RE = re.compile(r"(\d+)\s*(хв|год|дн)\.?\s*тому", re.I)


def _parse_age(text):
    """Work.ua's search-results page only shows a relative age ("19 год. тому"), not an
    absolute date — approximated here so MAX_AGE_DAYS filtering still works roughly; best-effort
    only, not exact."""
    text = text.lower()
    if "щойно" in text or "сьогодні" in text:
        return datetime.now(timezone.utc)
    if "вчора" in text:
        return datetime.now(timezone.utc) - timedelta(days=1)
    m = _RELATIVE_AGE_RE.search(text)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    delta = {"хв": timedelta(minutes=n), "год": timedelta(hours=n), "дн": timedelta(days=n)}[unit]
    return datetime.now(timezone.utc) - delta


def parse_html(html_text):
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise RuntimeError("beautifulsoup4 not installed — pip install -r requirements.txt")
    soup = BeautifulSoup(html_text, "html.parser")
    items, seen_ids = [], set()
    for a in soup.find_all("a", href=_JOB_LINK_RE):
        m = re.search(r"/jobs/(\d+)", a["href"])
        if not m:
            continue
        jid = m.group(1)
        title = a.get_text(strip=True)
        if not title or jid in seen_ids:
            continue
        seen_ids.add(jid)
        # Walk up to the nearest ancestor with enough text to be the whole listing card, not
        # just the title link itself — there's no stable class name to anchor on instead. Stop
        # BEFORE stepping into any ancestor that contains more than one job link: that means
        # we've left this card and would otherwise pull in a neighboring listing's text too.
        card = a
        for _ in range(6):
            parent = card.parent
            if parent is None or len(parent.find_all("a", href=_JOB_LINK_RE)) > 1:
                break
            card = parent
            if len(card.get_text(strip=True)) > len(title) + 60:
                break
        desc = card.get_text(" ", strip=True)
        items.append({
            "title": title,
            "link": f"https://www.work.ua/jobs/{jid}/",
            "desc": desc,
            "pub": _parse_age(desc),
        })
    return items


class WorkUaProvider(Provider):
    name = "Work.ua"
    setting_name = "source_workua"

    def fetch(self, keyword):
        slug = re.sub(r"[^\w]+", "-", keyword.strip().lower()).strip("-")
        return parse_html(http(f"https://www.work.ua/jobs-{urllib.parse.quote(slug)}/"))


provider = WorkUaProvider()
