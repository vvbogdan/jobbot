# -*- coding: utf-8 -*-
"""
sources — one module per job source. Each exposes a `provider` object implementing the
Provider interface (see _base.py): `.name`, `.setting_name`, `.fetch(keyword)`.

jobbot.py's collect() loops over PROVIDERS and treats all sources identically — adding a 6th
source means adding one file here and one line below, not touching collect() or config.py's
shape. This package exists because the bot started as DOU+Djinni only; once Jooble/RemoteOK/
Work.ua joined as keyword-based sources (as opposed to DOU/Djinni's original one-feed-per-
category shape), the fetch/parse logic for all five no longer fit comfortably in jobbot.py
alongside the Telegram/state/PDF code that's the bot's actual job.

To add a new source: copy any existing module here as a template, give it a `name`, a
`setting_name` (or leave it None to make it always-on, like DOU/Djinni), implement `fetch()`
to return a list of {"title", "link", "desc", "pub"} dicts, add it to PROVIDERS below, and —
if it's optional — add its setting to SETTINGS_SCHEMA in jobbot.py and its description to
i18n.py. Nothing else needs to change.
"""
from ._base import Provider
from . import dou, djinni, jooble, remoteok, workua

# Each submodule exposes a `provider` instance — collected here so jobbot.py's collect() can
# just loop over PROVIDERS without knowing about any individual source module. (Deliberately
# not `from .dou import provider as dou` etc.: that would rebind the name `dou` in this
# package's namespace to the provider instance, shadowing the actual `sources.dou` submodule —
# a real bug this project hit once already, while testing this very refactor.)
PROVIDERS = [dou.provider, djinni.provider, jooble.provider, remoteok.provider, workua.provider]

__all__ = ["Provider", "PROVIDERS"]
