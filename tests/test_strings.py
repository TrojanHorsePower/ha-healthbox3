"""Structural check tying strings.json and translations/en.json together.

Not an entity-behavior test - guards against the two files silently
drifting apart, which nothing else in the test suite would catch.
"""

from __future__ import annotations

from pathlib import Path

_HEALTHBOX3_DIR = Path(__file__).parent.parent / "custom_components" / "healthbox3"
STRINGS_PATH = _HEALTHBOX3_DIR / "strings.json"
TRANSLATIONS_EN_PATH = _HEALTHBOX3_DIR / "translations" / "en.json"


def test_strings_and_translations_en_are_byte_identical():
    """strings.json is what HA validates against the integration's own
    schema; translations/en.json is what actually ships to English-
    speaking users at runtime. This project has no other language yet, so
    the two are meant to always be identical - a change to one without
    the other silently ships stale or missing English text, with nothing
    else in the test suite (or hassfest) catching it.
    """
    assert STRINGS_PATH.read_text() == TRANSLATIONS_EN_PATH.read_text()
