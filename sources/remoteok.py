# -*- coding: utf-8 -*-
"""RemoteOK — public JSON API, no auth needed. Off by default (setting_name) — mostly
international remote jobs in English, not Ukraine-specific. Tags are a fixed RemoteOK
vocabulary (python, javascript, devops, ios, ...), not free text, so an unusual keyword (e.g.
"Embedded") may just return nothing — that's expected, not a failure. See README section 15."""
import json
import re
import urllib.parse
from datetime import datetime

from net import http, strip_html

from ._base import Provider


class RemoteOKProvider(Provider):
    name = "RemoteOK"
    setting_name = "source_remoteok"

    def fetch(self, keyword):
        tag_slug = re.sub(r"[^a-z0-9]+", "", keyword.lower())
        data = json.loads(http(f"https://remoteok.com/api?tag={urllib.parse.quote(tag_slug)}"))
        items = []
        for job in data:
            if not isinstance(job, dict) or not job.get("id") or not job.get("url"):
                continue  # the first element is RemoteOK's own legal notice, not a job
            title = job.get("position") or job.get("title") or ""
            if not title:
                continue
            pub = None
            if job.get("date"):
                try:
                    pub = datetime.fromisoformat(job["date"].replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pub = None
            extra = [p for p in (
                job.get("location"),
                f"${job['salary_min']}-${job['salary_max']}" if job.get("salary_min") else None,
            ) if p]
            desc = " · ".join(extra + [strip_html(job.get("description") or "")])
            items.append({"title": title, "link": job["url"], "desc": desc, "pub": pub})
        return items


provider = RemoteOKProvider()
