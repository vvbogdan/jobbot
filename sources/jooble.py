# -*- coding: utf-8 -*-
"""Jooble — REST API (not RSS), search by keyword + location. Off by default (setting_name) —
needs a free JOOBLE_API_KEY (jooble.org/api/about). The free plan's 500 requests is the key's
WHOLE LIFETIME quota, not per day, so don't poll this aggressively. See README section 15."""
import json
import os
import re
from datetime import datetime, timezone

from net import http, strip_html

from ._base import Provider


class JoobleProvider(Provider):
    name = "Jooble"
    setting_name = "source_jooble"

    def fetch(self, keyword):
        api_key = os.environ.get("JOOBLE_API_KEY")
        if not api_key:
            raise RuntimeError("JOOBLE_API_KEY is not set")
        location = os.environ.get("JOOBLE_LOCATION", "Україна")
        body = json.dumps({"keywords": keyword, "location": location}).encode()
        raw = http(f"https://jooble.org/api/{api_key}", data=body,
                   headers={"Content-Type": "application/json"})
        data = json.loads(raw)
        items = []
        for job in data.get("jobs", []):
            link, title = job.get("link"), job.get("title")
            if not link or not title:
                continue
            pub = None
            if job.get("updated"):
                try:
                    # Jooble sometimes sends more than 6 fractional-second digits, which
                    # datetime.fromisoformat() rejects — trim to microseconds
                    ts = re.sub(r"(\.\d{6})\d*", r"\1", job["updated"])
                    pub = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    pub = None
            extra = [p for p in (job.get("location"), job.get("salary"), job.get("company")) if p]
            desc = " · ".join(extra + [strip_html(job.get("snippet") or "")])
            items.append({"title": title, "link": link, "desc": desc, "pub": pub})
        return items


provider = JoobleProvider()
