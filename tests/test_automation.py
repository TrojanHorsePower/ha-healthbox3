"""End-to-end tests driving the boost fan entities through a real Home
Assistant automation, not by calling entity methods or services directly.

This exercises the full automation stack (trigger -> script engine ->
service call -> entity action -> state update) to confirm the fan entities
are genuinely automatable with no custom services, and that the
restart-while-active and room-existence-guard behaviors still hold when
triggered this way.
"""

from __future__ import annotations

import copy
import logging
from unittest.mock import AsyncMock

from homeassistant.setup import async_setup_component

from custom_components.healthbox3 import api as api_mod
from custom_components.healthbox3.fan import _percentage_to_level

from .conftest import setup_integration
from .test_boost import _ALL_ENTITY, _PREFIX, _ROOM1_ENTITY, _boost

_TRIGGER_EVENT = "healthbox3_test_trigger"


def _install_stateful_boost_mock(mock_api_client, room_ids: list[int]) -> dict:
    """Wire async_get_boost/async_set_boost to a shared in-memory store.

    A static mock (a fixed `return_value`) can't reflect a PUT it just
    received, so a test asserting the resulting *state* (not just the call
    arguments) needs the mock to actually remember what was set - this
    simulates that, standing in for the real device.
    """
    store = {room_id: _boost(False) for room_id in room_ids}

    async def _get_boost(room_id: int):
        return store[room_id]

    async def _set_boost(room_id: int, *, enable: bool, level: float, timeout: int):
        store[room_id] = _boost(
            enable, level=level, timeout=timeout, remaining=timeout if enable else 0
        )

    mock_api_client.async_get_boost = AsyncMock(side_effect=_get_boost)
    mock_api_client.async_set_boost = AsyncMock(side_effect=_set_boost)
    return store


async def _fire_automation(hass, action: dict) -> None:
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "alias": "healthbox3 boost test automation",
                "trigger": {"platform": "event", "event_type": _TRIGGER_EVENT},
                "action": action,
            }
        },
    )
    await hass.async_block_till_done()

    hass.bus.async_fire(_TRIGGER_EVENT)
    await hass.async_block_till_done()


async def test_automation_turns_on_room_boost_with_percentage(
    hass, mock_api_client, v1_data
):
    _install_stateful_boost_mock(mock_api_client, [r.id for r in v1_data.rooms])
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        api_key=None,
        healthbox_data=v1_data,
    )

    await _fire_automation(
        hass,
        {
            "service": "fan.turn_on",
            "target": {"entity_id": _ROOM1_ENTITY},
            "data": {"percentage": 75},
        },
    )

    mock_api_client.async_set_boost.assert_awaited_once_with(
        1, enable=True, level=_percentage_to_level(75), timeout=900
    )
    state = hass.states.get(_ROOM1_ENTITY)
    assert state.state == "on"
    assert state.attributes["percentage"] == 75


async def test_automation_sets_preset_mode_on_room_boost(
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

    await _fire_automation(
        hass,
        {
            "service": "fan.set_preset_mode",
            "target": {"entity_id": _ROOM1_ENTITY},
            "data": {"preset_mode": "1 hour"},
        },
    )

    # boost was off, so this only stages the new duration - no device call.
    mock_api_client.async_set_boost.assert_not_awaited()
    assert hass.states.get(_ROOM1_ENTITY).attributes["preset_mode"] == "1 hour"


async def test_automation_restarts_active_boost_and_logs(
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
        await _fire_automation(
            hass,
            {
                "service": "fan.set_percentage",
                "target": {"entity_id": _ROOM1_ENTITY},
                "data": {"percentage": 50},
            },
        )

    mock_api_client.async_set_boost.assert_awaited_once_with(
        1, enable=True, level=_percentage_to_level(50), timeout=900
    )
    assert any("Restarting active boost" in r.message for r in caplog.records)


async def test_automation_turns_off_room_boost(hass, mock_api_client, v1_data):
    active = _boost(True, remaining=300)
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        api_key=None,
        healthbox_data=v1_data,
        boost_status=active,
    )

    await _fire_automation(
        hass,
        {"service": "fan.turn_off", "target": {"entity_id": _ROOM1_ENTITY}},
    )

    mock_api_client.async_set_boost.assert_awaited_once_with(
        1, enable=False, level=100.0, timeout=900
    )


async def test_automation_hitting_removed_room_logs_error_and_does_not_call_device(
    hass, mock_api_client, v2_data, boost_status, caplog
):
    """The room-existence guard must still apply when triggered via a real
    automation, not just via a direct service call. Automations catch and
    log exceptions raised by their actions rather than propagating them,
    so this asserts the error surfaces in the log instead of via
    pytest.raises.
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

    with caplog.at_level(logging.ERROR):
        await _fire_automation(
            hass,
            {"service": "fan.turn_on", "target": {"entity_id": entity_id}},
        )

    mock_api_client.async_set_boost.assert_not_awaited()
    assert any(
        "no longer present on this Healthbox device" in r.message
        for r in caplog.records
    )


async def test_automation_turns_on_boost_all_with_preset_mode(
    hass, mock_api_client, v1_data
):
    _install_stateful_boost_mock(mock_api_client, [r.id for r in v1_data.rooms])
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        api_key=None,
        healthbox_data=v1_data,
    )

    await _fire_automation(
        hass,
        {
            "service": "fan.turn_on",
            "target": {"entity_id": _ALL_ENTITY},
            "data": {"preset_mode": "2 hours"},
        },
    )

    room_ids = {room.id for room in v1_data.rooms}
    called_ids = {
        call.args[0] for call in mock_api_client.async_set_boost.await_args_list
    }
    assert called_ids == room_ids
    for call in mock_api_client.async_set_boost.await_args_list:
        assert call.kwargs == {"enable": True, "level": 100.0, "timeout": 7200}
    assert hass.states.get(_ALL_ENTITY).state == "on"


async def test_automation_boost_all_partial_failure_logs_error(
    hass, mock_api_client, v1_data, boost_status, caplog
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

    with caplog.at_level(logging.ERROR):
        await _fire_automation(
            hass,
            {"service": "fan.turn_on", "target": {"entity_id": _ALL_ENTITY}},
        )

    assert any("Failed to start boost for rooms" in r.message for r in caplog.records)
