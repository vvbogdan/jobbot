# -*- coding: utf-8 -*-
"""
net — the one place that talks to the network: a small retrying HTTP client and an HTML-to-text
helper, shared by jobbot.py (Telegram/ntfy calls) and every module under sources/ (fetching job
listings). Kept dependency-free (standard library only) so sources/ doesn't need jobbot.py, and
jobbot.py doesn't need to know how any particular source fetches its data.
"""
import html
import re
import time
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def http(url, data=None, headers=None, timeout=25, retries=2, method=None):
    h = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        h.update(headers)
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=h, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = e
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:500]
            except Exception:  # noqa: BLE001
                pass
            last = RuntimeError(f"HTTP {e.code}: {body or e}")
            if e.code == 429:
                time.sleep(int(e.headers.get("Retry-After", "3")))
            elif e.code in (403, 404):
                break
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def strip_html(s):
    s = html.unescape(s or "")
    s = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"[ \t ]+", " ", s).strip()
