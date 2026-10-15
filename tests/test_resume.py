# -*- coding: utf-8 -*-
"""Unit tests for resume.py's pure markup parser — the only part of the Claude-API/PDF-rendering
module that doesn't need a network call or an ANTHROPIC_API_KEY to exercise."""
from bot import resume


def test_parse_resume_markup_basic_structure():
    text = (
        "# Jane Doe\n"
        "## Python Developer\n"
        "jane@example.com | +1 555 0100\n"
        "\n"
        "### Summary\n"
        "A short summary.\n"
        "\n"
        "### Skills\n"
        "- Python: 5 years\n"
        "- SQL: 3 years\n"
    )
    blocks = resume.parse_resume_markup(text)
    kinds = [k for k, _ in blocks]
    assert kinds[0] == "name"
    assert blocks[0][1] == "Jane Doe"
    assert kinds[1] == "title"
    assert blocks[1][1] == "Python Developer"
    assert ("contact", "jane@example.com | +1 555 0100") in blocks
    assert ("section", "Summary") in blocks
    assert ("bullet", "Python: 5 years") in blocks
    assert ("bullet", "SQL: 3 years") in blocks


def test_parse_resume_markup_jobhead_and_para():
    text = "### Experience\n**Senior Dev | Acme | 2020-2024**\nSome paragraph text.\n"
    blocks = resume.parse_resume_markup(text)
    assert ("jobhead", "Senior Dev | Acme | 2020-2024") in blocks
    assert ("para", "Some paragraph text.") in blocks


def test_parse_resume_markup_blank_lines_become_space_blocks():
    text = "# Name\n\n\n## Title\n"
    blocks = resume.parse_resume_markup(text)
    kinds = [k for k, _ in blocks]
    assert kinds.count("space") == 2
