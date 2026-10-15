# -*- coding: utf-8 -*-
"""Tiny shared logging helper — one place so jobbot.py and telegram_api.py (and anything else
later split out of jobbot.py) don't each define their own copy of the same one-liner."""
from datetime import datetime


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)
