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
import re

_session = None
_db_url = None

# Firebase RTDB keys can't contain '.', '#', '$', '[', ']', '/' — but jobbot.py's own job IDs
# can (Jooble/RemoteOK fall back to the *full URL* as their id, slashes and all — see job_id()
# in jobbot.py). Rather than touch job_id() (its format is relied on elsewhere: callback_data,
# notification text, the local-file state format), escape just the forbidden characters in any
# dict key on the way in/out of Firebase, transparently, so the rest of the bot never knows.
_FORBIDDEN_KEY_CHARS = ".#$[]/"

# Firebase RTDB treats *any* null value as "delete this path" — including a null that's an
# element of a list, e.g. the ("iOS", None) keyword/must_text pairs in a profile's "keywords".
# A PUT of ["iOS", None] is stored (and read back) as the single-element ["iOS"], silently
# shortening the pair and breaking every "for keyword, must_text in ..." unpack in jobbot.py.
# Swap None for this sentinel on the way in, and back on the way out, so it survives intact.
_NULL_SENTINEL = {"__jobbot_null__": True}


def enabled():
    return bool(os.environ.get("FIREBASE_DB_URL") and os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON"))


def _encode_key(k):
    return "".join(
        "%{:02X}".format(ord(ch)) if ch == "%" or ch in _FORBIDDEN_KEY_CHARS else ch
        for ch in k
    )


def _decode_key(k):
    return re.sub(r"%([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), k)


def _encode(obj):
    if obj is None:
        return dict(_NULL_SENTINEL)
    if isinstance(obj, dict):
        return {_encode_key(k): _encode(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_encode(v) for v in obj]
    return obj


def _decode(obj):
    if isinstance(obj, dict):
        if obj == _NULL_SENTINEL:
            return None
        return {_decode_key(k): _decode(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decode(v) for v in obj]
    return obj


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


def _raise_with_body(resp):
    # resp.raise_for_status() alone drops the response body, which is exactly where Firebase
    # explains *why* a request was bad (invalid key, invalid value, bad path) — surface it so
    # the caller's log line is actionable instead of a bare "400 Client Error".
    try:
        resp.raise_for_status()
    except Exception as e:  # noqa: BLE001
        body = (resp.text or "").strip()[:500]
        raise RuntimeError(f"{e} | body: {body}") from None


def get_state(timeout=20):
    """Fetches the whole state tree from /state.json. Returns None if the path is empty (brand
    new database) or the request fails — either way the caller falls back to the local file."""
    session = _get_session()
    resp = session.get(f"{_db_url}/state.json", timeout=timeout)
    _raise_with_body(resp)
    data = resp.json()
    return _decode(data) if data is not None else data


def put_state(data, timeout=20):
    """Overwrites the whole state tree at /state.json. Raises on failure (network error, bad
    auth, quota) — the caller decides what to do (jobbot.py logs it and keeps the in-memory
    state so nothing is lost, just not yet persisted remotely; it retries on the next change)."""
    session = _get_session()
    # allow_nan=False: a NaN/Infinity anywhere in the state makes json.dumps emit non-standard
    # JSON that Firebase's REST API rejects with a bare 400 and no useful body — catch it here
    # with a clear local error instead of a mystery HTTP failure.
    payload = json.dumps(_encode(data), ensure_ascii=False, allow_nan=False).encode("utf-8")
    resp = session.put(
        f"{_db_url}/state.json",
        data=payload,
        headers={"Content-Type": "application/json"},
        timeout=timeout,
    )
    _raise_with_body(resp)
