"""Structural checks for icons.json - not entity-behavior tests.

These guard against icons.json silently drifting out of sync with the
actual set of entity translation_keys (e.g. a new sensor type added
without a matching icon entry, or a stale entry left behind after one
is removed) - the kind of thing nothing else in the test suite would
catch, since HA itself only warns rather than fails on this.
"""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.healthbox3.const import PROFILES
from custom_components.healthbox3.sensor import ROOM_SENSOR_META

ICONS_PATH = (
    Path(__file__).parent.parent / "custom_components" / "healthbox3" / "icons.json"
)

# Fixed translation_keys not derived from a shared data structure (see
# sensor.py/select.py/fan.py - room_airflow and global_aqi are their own
# entity classes rather than ROOM_SENSOR_META entries, and fan.py builds
# its two entities directly rather than exposing an importable list).
EXTRA_SENSOR_KEYS = {"room_airflow", "global_aqi"}
SELECT_KEYS = {"room_profile"}
FAN_KEYS = {"room_boost", "boost_all"}


def _load_icons() -> dict:
    with ICONS_PATH.open() as f:
        return json.load(f)


def test_icons_json_is_valid_json():
    icons = _load_icons()
    assert "entity" in icons


def test_sensor_icons_cover_every_translation_key():
    expected = {meta.translation_key for meta in ROOM_SENSOR_META.values()} | EXTRA_SENSOR_KEYS
    actual = set(_load_icons()["entity"]["sensor"])
    assert actual == expected


def test_select_icons_cover_every_translation_key():
    actual = set(_load_icons()["entity"]["select"])
    assert actual == SELECT_KEYS


def test_fan_icons_cover_every_translation_key():
    actual = set(_load_icons()["entity"]["fan"])
    assert actual == FAN_KEYS


def test_every_icon_entry_has_a_default_mdi_icon():
    icons = _load_icons()
    for platform in icons["entity"].values():
        for translation_key, entry in platform.items():
            assert "default" in entry, f"{translation_key} has no default icon"
            assert entry["default"].startswith("mdi:"), (
                f"{translation_key}'s default icon isn't an mdi: icon"
            )
            for state, icon in entry.get("state", {}).items():
                assert icon.startswith("mdi:"), (
                    f"{translation_key}'s {state!r} state icon isn't an mdi: icon"
                )


def test_room_profile_has_an_icon_for_every_profile_value():
    """A profile value added without a matching icon would silently fall
    back to the generic default - this would only ever be noticed visually.
    """
    profile_states = set(_load_icons()["entity"]["select"]["room_profile"]["state"])
    assert profile_states == set(PROFILES)


def test_boost_fans_have_a_distinct_off_icon():
    icons = _load_icons()["entity"]["fan"]
    for translation_key in FAN_KEYS:
        assert "off" in icons[translation_key].get("state", {}), (
            f"{translation_key} has no distinct icon for the off state"
        )
