# -*- coding: utf-8 -*-
"""Provider — the interface every job source implements. See sources/__init__.py for the list
of active providers and how jobbot.py uses them."""


class Provider:
    name = ""            # shown in pushes and feed-health messages, e.g. "DOU", "Jooble"
    setting_name = None  # the /set key that turns this source on/off (SETTINGS_SCHEMA in
                          # jobbot.py), or None if the source is always on (DOU, Djinni)

    def fetch(self, keyword):
        """Returns a list of {"title", "link", "desc", "pub"} dicts for this keyword — "pub" is
        a timezone-aware datetime or None if the source doesn't give one (or only a rough
        relative age). Let any failure (network, parsing, missing credentials) raise — jobbot.py's
        collect() catches it, logs it, and counts it toward the FEED_FAIL_THRESHOLD warning."""
        raise NotImplementedError
