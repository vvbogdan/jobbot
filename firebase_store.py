# -*- coding: utf-8 -*-
"""Optional Firebase Realtime Database backend for state persistence — so the bot's state
survives Render Free's disk wipe on every restart/redeploy without the old pinned-backup/manual
restore dance (see restore_from_pinned_backup in jobbot.py, kept as a last-resort fallback).

Enabled only when both FIREBASE_DB_URL and FIREBASE_SERVICE_ACCOUNT_JSON are set as env vars;
otherwise jobbot.py's load_state()/save_state() fall back to the plain local file they always
used. See README for how to set these two up (a free Firebase Spark project — no credit card,
Google just throttles you at the free quota rather than billing past it).

FIREBASE_SERVICE_ACCOUNT_JSON is the *entire contents* of the service-account key file Firebase
Console gives you (Project settings -> Service accounts -> Generate new private key), pasted as
one env var value. google-auth (not the full firebase-admin SDK — it's much heavier) turns that
into short-lived OAuth2 tokens for plain REST calls, which keeps this module's only extra
dependency small.
"""
import json
import os

_session = None
_db_url = None


def enabled():
    return bool(os.environ.get("FIREBASE_DB_URL") and os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON"))


def _get_session():
    global _session, _db_url
    if _session is not None:
        return _session
    # Imported lazily — so a deployment that never sets the two env vars above doesn't need
    # google-auth installed at all, and jobbot.py never pays an import cost for a feature it isn't using.
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession

    info = json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT_JSON"])
    creds = service_account.Credentials.from_service_account_info(
        info,
        scopes=[
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/firebase.database",
        ],
    )
    _session = AuthorizedSession(creds)
    _db_url = os.environ["FIREBASE_DB_URL"].rstrip("/")
    return _session


def get_state(timeout=20):
    """Fetches the whole state tree from /state.json. Returns None if the path is empty (brand
    new database) or the request fails — either way the caller falls back to the local file."""
    session = _get_session()
    resp = session.get(f"{_db_url}/state.json", timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def put_state(data, timeout=20):
    """Overwrites the whole state tree at /state.json. Raises on failure (network error, bad
    auth, quota) — the caller decides what to do (jobbot.py logs it and keeps the in-memory
    state so nothing is lost, just not yet persisted remotely; it retries on the next change)."""
    session = _get_session()
    resp = session.put(
        f"{_db_url}/state.json",
        data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        timeout=timeout,
    )
    resp.raise_for_status()
