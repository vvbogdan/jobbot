# -*- coding: utf-8 -*-
"""Ensures the repo root (where jobbot.py/firebase_store.py/config.py live) is on sys.path
during pytest collection, regardless of pytest's rootdir-insertion rules or whether tests/ is
a package — this is what lets `import jobbot` work both locally and in CI."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
