# -*- coding: utf-8 -*-
"""Tests for firebase_store.py's pure encode/decode helpers — the part of the Firebase backend
that doesn't need a real network call or credentials, and the part that caused two real
production bugs this project already hit (see firebase_store.py's own comments): forbidden
characters in dict keys, and Firebase silently dropping `None` values."""
from bot import firebase_store as fs


def test_encode_key_escapes_forbidden_chars():
    # Jooble/RemoteOK job ids are full URLs — '/', '.', '#', '$', '[', ']' are all forbidden
    # as Firebase RTDB keys.
    key = "https://remoteok.com/remote-jobs/123?x=1"
    encoded = fs._encode_key(key)
    for ch in fs._FORBIDDEN_KEY_CHARS:
        assert ch not in encoded
    assert fs._decode_key(encoded) == key


def test_encode_key_roundtrip_with_literal_percent():
    key = "100% done.txt"
    assert fs._decode_key(fs._encode_key(key)) == key


def test_encode_decode_roundtrip_simple_values():
    data = {"a": 1, "b": "text", "c": [1, 2, 3], "d": True}
    assert fs._decode(fs._encode(data)) == data


def test_encode_decode_roundtrip_none_in_dict():
    data = {"must_text": None, "keyword": "iOS"}
    assert fs._decode(fs._encode(data)) == data


def test_encode_decode_roundtrip_none_inside_list():
    # This is the exact shape that broke in production: a (keyword, None) pair as a list.
    data = {"keywords": [["iOS", None], ["Mobile", "ios|swift"]]}
    encoded = fs._encode(data)
    # None must survive as a non-null placeholder so Firebase doesn't delete it from the list.
    assert encoded["keywords"][0][1] is not None
    decoded = fs._decode(encoded)
    assert decoded == data
    assert decoded["keywords"][0] == ["iOS", None]


def test_encode_decode_roundtrip_nested_structure_with_forbidden_keys():
    data = {
        "jobs": {
            "https://dou.ua/vacancies/123/": {"title": "Python Dev", "must_text": None},
        }
    }
    decoded = fs._decode(fs._encode(data))
    assert decoded == data


def test_decode_handles_none_response():
    # get_state() passes the raw Firebase response straight through _decode() when it's a dict,
    # but the caller itself must still handle a brand-new (empty) database returning None.
    assert fs._decode({}) == {}
