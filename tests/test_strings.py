"""Structural checks tying strings.json and every translations/*.json
file together.

Not entity-behavior tests - guard against the files silently drifting
apart (a new key added to one but not the others), which nothing else
in the test suite would catch.

Translation status: Dutch (nl.json) has been reviewed by a native
speaker. French (fr.json) has not - it's a best-effort translation
only, produced without a native French speaker's review, and should be
treated as less trustworthy than the English/Dutch text until someone
fluent checks it. If you're a native French speaker, corrections are
very welcome.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_HEALTHBOX3_DIR = Path(__file__).parent.parent / "custom_components" / "healthbox3"
STRINGS_PATH = _HEALTHBOX3_DIR / "strings.json"
TRANSLATIONS_DIR = _HEALTHBOX3_DIR / "translations"
TRANSLATIONS_EN_PATH = TRANSLATIONS_DIR / "en.json"
TRANSLATIONS_NL_PATH = TRANSLATIONS_DIR / "nl.json"
TRANSLATIONS_FR_PATH = TRANSLATIONS_DIR / "fr.json"


def test_strings_and_translations_en_are_byte_identical():
    """strings.json is what HA validates against the integration's own
    schema; translations/en.json is what actually ships to English-
    speaking users at runtime. These two are meant to always be
    identical - a change to one without the other silently ships stale
    or missing English text, with nothing else in the test suite (or
    hassfest) catching it.
    """
    assert STRINGS_PATH.read_text() == TRANSLATIONS_EN_PATH.read_text()


def _key_shape(data: Any) -> Any:
    """Return the structural shape of a translations dict - same keys and
    nesting as the input, with every leaf value collapsed to None so only
    the structure (which keys exist, not what they say) is compared.
    """
    if isinstance(data, dict):
        return {key: _key_shape(value) for key, value in data.items()}
    return None


def _load_json(path: Path) -> Any:
    with path.open() as f:
        return json.load(f)


def test_translations_nl_matches_en_key_structure():
    """nl.json's actual text is necessarily different from en.json's -
    only the shape (every key present, same nesting, nothing extra or
    missing) is expected to match.
    """
    assert _key_shape(_load_json(TRANSLATIONS_NL_PATH)) == _key_shape(
        _load_json(TRANSLATIONS_EN_PATH)
    )


def test_translations_fr_matches_en_key_structure():
    """Same structural check as Dutch - see this module's docstring for
    fr.json's translation-quality caveat, which this test doesn't (and
    can't) verify.
    """
    assert _key_shape(_load_json(TRANSLATIONS_FR_PATH)) == _key_shape(
        _load_json(TRANSLATIONS_EN_PATH)
    )
