"""Tests for boost control: per-room and boost-all fan entities."""

from __future__ import annotations

import copy
import logging
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import State
from homeassistant.exceptions import HomeAssistantError

from pytest_homeassistant_custom_component.common import mock_restore_cache

from custom_components.healthbox3 import api as api_mod
from custom_components.healthbox3.fan import (
    _level_to_percentage,
    _percentage_to_level,
    _preset_mode_for_timeout,
    _timeout_for_preset_mode,
)

from .conftest import setup_integration

# The device name ("Healthbox 3.0" in both fixtures) becomes an entity_id
# slug prefix once has_entity_name groups every entity under one device.
_PREFIX = "healthbox_3_0"
_ROOM1_ENTITY = f"fan.{_PREFIX}_toilet_boost"
_ALL_ENTITY = f"fan.{_PREFIX}_boost_all"


def _boost(
    enable: bool,
    *,
    level: float = 100.0,
    timeout: int = 900,
    remaining: int = 0,
    default_level: float = 100.0,
    default_timeout: int = 900,
) -> api_mod.BoostStatus:
    return api_mod.BoostStatus(
        enable=enable,
        level=level,
        timeout=timeout,
        remaining=remaining,
        default_level=default_level,
        default_timeout=default_timeout,
    )


# --- pure rescale/preset function tests ---


@pytest.mark.parametrize(
    ("level", "expected_percentage"),
    [
        (10.0, 0),
        (200.0, 100),
        (29.0, 10),
        (105.0, 50),
        (100.0, 47),  # (100-10)/190*100 = 47.368... -> rounds to 47
    ],
)
def test_level_to_percentage(level, expected_percentage):
    assert _level_to_percentage(level) == expected_percentage


@pytest.mark.parametrize(
    ("percentage", "expected_level"),
    [
        (0, 10.0),
        (100, 200.0),
        (10, 29.0),
        (50, 105.0),
    ],
)
def test_percentage_to_level(percentage, expected_level):
    assert _percentage_to_level(percentage) == pytest.approx(expected_level)


@pytest.mark.parametrize(
    ("timeout", "expected_preset"),
    [
        (900, "15 min"),
        (1800, "30 min"),
        (3600, "1 hour"),
        (7200, "2 hours"),
        (10800, "3 hours"),
        (1000, "15 min"),  # nearest to 900, not 1800
        (5000, "1 hour"),  # nearest to 3600, not 7200
    ],
)
def test_preset_mode_for_timeout_snaps_to_nearest(timeout, expected_preset):
    assert _preset_mode_for_timeout(timeout) == expected_preset


@pytest.mark.parametrize(
    ("preset", "expected_timeout"),
    [
        ("15 min", 900),
        ("30 min", 1800),
        ("1 hour", 3600),
        ("2 hours", 7200),
        ("3 hours", 10800),
    ],
)
def test_timeout_for_preset_mode(preset, expected_timeout):
    assert _timeout_for_preset_mode(preset) == expected_timeout


# --- entity behavior ---


async def test_boost_fan_seeded_from_device_defaults(hass, mock_api_client, v1_data, boost_status):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        api_key=None,
        healthbox_data=v1_data,
        boost_status=boost_status,
    )

    state = hass.states.get(_ROOM1_ENTITY)
    assert state is not None
    assert state.state == "off"
    assert state.attributes["percentage"] == 0  # off, regardless of staged level
    assert state.attributes["preset_mode"] == "15 min"
    assert state.attributes["level"] == "100%"


async def test_boost_fan_reports_on_with_rescaled_percentage(hass, mock_api_client, v1_data):
    active = _boost(True, default_level=105.0, default_timeout=900, remaining=300)
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        api_key=None,
        healthbox_data=v1_data,
        boost_status=active,
    )

    state = hass.states.get(_ROOM1_ENTITY)
    assert state.state == "on"
    assert state.attributes["percentage"] == 50
    assert state.attributes["remaining"] == 300


async def test_boost_fan_turn_on_uses_current_settings(hass, mock_api_client, v1_data, boost_status):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        api_key=None,
        healthbox_data=v1_data,
        boost_status=boost_status,
    )

    await hass.services.async_call(
        "fan", "turn_on", {"entity_id": _ROOM1_ENTITY}, blocking=True
    )

    mock_api_client.async_set_boost.assert_awaited_once_with(
        1, enable=True, level=100.0, timeout=900
    )


async def test_boost_fan_set_percentage_zero_turns_off(hass, mock_api_client, v1_data):
    active = _boost(True, remaining=300)
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        api_key=None,
        healthbox_data=v1_data,
        boost_status=active,
    )

    await hass.services.async_call(
        "fan",
        "set_percentage",
        {"entity_id": _ROOM1_ENTITY, "percentage": 0},
        blocking=True,
    )

    mock_api_client.async_set_boost.assert_awaited_once_with(
        1, enable=False, level=100.0, timeout=900
    )


async def test_boost_fan_set_percentage_while_off_turns_on_at_new_level(
    hass, mock_api_client, v1_data, boost_status
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        api_key=None,
        healthbox_data=v1_data,
        boost_status=boost_status,
    )

    await hass.services.async_call(
        "fan",
        "set_percentage",
        {"entity_id": _ROOM1_ENTITY, "percentage": 75},
        blocking=True,
    )

    mock_api_client.async_set_boost.assert_awaited_once_with(
        1, enable=True, level=_percentage_to_level(75), timeout=900
    )


async def test_boost_fan_set_percentage_while_active_restarts_and_logs(
    hass, mock_api_client, v1_data, caplog
):
    active = _boost(True, level=100.0, timeout=900, remaining=279)
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        api_key=None,
        healthbox_data=v1_data,
        boost_status=active,
    )

    with caplog.at_level(logging.INFO, logger="custom_components.healthbox3.fan"):
        await hass.services.async_call(
            "fan",
            "set_percentage",
            {"entity_id": _ROOM1_ENTITY, "percentage": 75},
            blocking=True,
        )

    mock_api_client.async_set_boost.assert_awaited_once_with(
        1, enable=True, level=_percentage_to_level(75), timeout=900
    )
    assert any("Restarting active boost" in r.message for r in caplog.records)


async def test_boost_fan_set_preset_mode_while_inactive_only_stages(
    hass, mock_api_client, v1_data, boost_status
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        api_key=None,
        healthbox_data=v1_data,
        boost_status=boost_status,
    )

    await hass.services.async_call(
        "fan",
        "set_preset_mode",
        {"entity_id": _ROOM1_ENTITY, "preset_mode": "1 hour"},
        blocking=True,
    )

    mock_api_client.async_set_boost.assert_not_awaited()
    assert hass.states.get(_ROOM1_ENTITY).attributes["preset_mode"] == "1 hour"


async def test_boost_fan_set_preset_mode_while_active_restarts(hass, mock_api_client, v1_data):
    active = _boost(True, level=100.0, timeout=900, remaining=300)
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        api_key=None,
        healthbox_data=v1_data,
        boost_status=active,
    )

    await hass.services.async_call(
        "fan",
        "set_preset_mode",
        {"entity_id": _ROOM1_ENTITY, "preset_mode": "1 hour"},
        blocking=True,
    )

    mock_api_client.async_set_boost.assert_awaited_once_with(
        1, enable=True, level=100.0, timeout=3600
    )


async def test_boost_fan_restores_percentage_and_preset_mode_across_restart(
    hass, mock_api_client, v1_data, boost_status
):
    mock_restore_cache(
        hass,
        [State(_ROOM1_ENTITY, "off", {"percentage": 50, "preset_mode": "1 hour"})],
    )

    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        api_key=None,
        healthbox_data=v1_data,
        boost_status=boost_status,
    )

    state = hass.states.get(_ROOM1_ENTITY)
    assert state.attributes["preset_mode"] == "1 hour"
    assert state.attributes["level"] == "105%"  # restored 50% -> level 105.0

    await hass.services.async_call(
        "fan", "turn_on", {"entity_id": _ROOM1_ENTITY}, blocking=True
    )
    mock_api_client.async_set_boost.assert_awaited_once_with(
        1, enable=True, level=105.0, timeout=3600
    )


async def test_boost_fan_guards_against_a_room_removed_from_the_device(
    hass, mock_api_client, v2_data, boost_status
):
    """Confirmed on real hardware: acting on an unknown room id returns a bare
    500 with an empty body. The boost fan must check the room still exists
    before ever making that call.
    """
    entry = await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
    )
    coordinator = entry.runtime_data

    shrunk = copy.deepcopy(v2_data)
    shrunk.rooms = [r for r in shrunk.rooms if r.id != 1]
    coordinator.data.healthbox = shrunk
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    entity_id = f"fan.{_PREFIX}_toilet_boost"
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "fan", "turn_on", {"entity_id": entity_id}, blocking=True
        )


async def test_boost_all_fan_reflects_all_rooms_enabled(hass, mock_api_client, v1_data):
    statuses = {room.id: _boost(False) for room in v1_data.rooms}

    async def _get_boost(room_id: int) -> api_mod.BoostStatus:
        return statuses[room_id]

    mock_api_client.async_get_boost = AsyncMock(side_effect=_get_boost)

    entry = await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        api_key=None,
        healthbox_data=v1_data,
    )
    coordinator = entry.runtime_data

    assert hass.states.get(_ALL_ENTITY).state == "off"

    for room_id in statuses:
        statuses[room_id] = _boost(True)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(_ALL_ENTITY).state == "on"

    some_room_id = next(iter(statuses))
    statuses[some_room_id] = _boost(False)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(_ALL_ENTITY).state == "off"


async def test_boost_all_fan_turn_on_calls_every_room_with_shared_params(
    hass, mock_api_client, v1_data, boost_status
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        api_key=None,
        healthbox_data=v1_data,
        boost_status=boost_status,
    )

    await hass.services.async_call(
        "fan", "turn_on", {"entity_id": _ALL_ENTITY}, blocking=True
    )

    room_ids = {room.id for room in v1_data.rooms}
    called_ids = {
        call.args[0] for call in mock_api_client.async_set_boost.await_args_list
    }
    assert called_ids == room_ids
    for call in mock_api_client.async_set_boost.await_args_list:
        assert call.kwargs == {"enable": True, "level": 100.0, "timeout": 900}


async def test_boost_all_fan_set_percentage_pushes_every_room(
    hass, mock_api_client, v1_data, boost_status
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        api_key=None,
        healthbox_data=v1_data,
        boost_status=boost_status,
    )

    await hass.services.async_call(
        "fan",
        "set_percentage",
        {"entity_id": _ALL_ENTITY, "percentage": 75},
        blocking=True,
    )

    room_ids = {room.id for room in v1_data.rooms}
    called_ids = {
        call.args[0] for call in mock_api_client.async_set_boost.await_args_list
    }
    assert called_ids == room_ids
    for call in mock_api_client.async_set_boost.await_args_list:
        assert call.kwargs == {
            "enable": True,
            "level": _percentage_to_level(75),
            "timeout": 900,
        }


async def test_boost_all_fan_turn_on_raises_if_any_room_fails(
    hass, mock_api_client, v1_data, boost_status
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        api_key=None,
        healthbox_data=v1_data,
        boost_status=boost_status,
    )

    failing_room_id = v1_data.rooms[0].id

    async def _set_boost(room_id: int, *, enable: bool, level: float, timeout: int):
        if room_id == failing_room_id:
            raise api_mod.Healthbox3ConnectionError("boom")

    mock_api_client.async_set_boost = AsyncMock(side_effect=_set_boost)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "fan", "turn_on", {"entity_id": _ALL_ENTITY}, blocking=True
        )
