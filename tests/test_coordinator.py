"""Tests for the Healthbox3 DataUpdateCoordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.config_entries import SOURCE_REAUTH

from custom_components.healthbox3 import api as api_mod
from custom_components.healthbox3.const import DOMAIN
from custom_components.healthbox3.coordinator import Healthbox3DataUpdateCoordinator

from .conftest import make_config_entry


async def test_v1_only_polling_skips_v2(hass, v1_data, boost_status):
    entry = make_config_entry(hass, serial=v1_data.serial)
    client = AsyncMock(spec=api_mod.Healthbox3ApiClient)
    client.async_get_v1_data_current.return_value = v1_data
    client.async_get_boost.return_value = boost_status

    coordinator = Healthbox3DataUpdateCoordinator(hass, entry, client, use_v2=False)
    await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    client.async_get_v2_data_current.assert_not_called()
    assert len(coordinator.data.healthbox.rooms) == 7
    assert len(coordinator.data.boost) == 7


async def test_v2_polling_merges_boost_status(hass, v2_data, boost_status):
    entry = make_config_entry(hass, serial=v2_data.serial)
    client = AsyncMock(spec=api_mod.Healthbox3ApiClient)
    client.async_get_v2_data_current.return_value = v2_data
    client.async_get_boost.return_value = boost_status

    coordinator = Healthbox3DataUpdateCoordinator(hass, entry, client, use_v2=True)
    await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    room1 = next(r for r in coordinator.data.healthbox.rooms if r.id == 1)
    assert room1.profile_name == "health"
    assert coordinator.data.boost[1].default_level == 100.0


async def test_connection_error_marks_update_failed(hass, v1_data):
    entry = make_config_entry(hass, serial=v1_data.serial)
    client = AsyncMock(spec=api_mod.Healthbox3ApiClient)
    client.async_get_v1_data_current.side_effect = api_mod.Healthbox3ConnectionError(
        "offline"
    )

    coordinator = Healthbox3DataUpdateCoordinator(hass, entry, client, use_v2=False)
    await coordinator.async_refresh()

    assert coordinator.last_update_success is False


async def test_one_room_boost_failure_does_not_fail_whole_update(hass, v1_data):
    entry = make_config_entry(hass, serial=v1_data.serial)
    client = AsyncMock(spec=api_mod.Healthbox3ApiClient)
    client.async_get_v1_data_current.return_value = v1_data

    async def _boost_side_effect(room_id):
        if room_id == 1:
            raise api_mod.Healthbox3ConnectionError("hiccup")
        return api_mod.BoostStatus(enable=False, level=100.0, timeout=900, remaining=0)

    client.async_get_boost.side_effect = _boost_side_effect

    coordinator = Healthbox3DataUpdateCoordinator(hass, entry, client, use_v2=False)
    await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    assert 1 not in coordinator.data.boost
    assert 2 in coordinator.data.boost


async def test_key_invalid_downgrades_to_v1_and_starts_reauth(
    hass, v1_data, v2_data, boost_status
):
    entry = make_config_entry(hass, serial=v2_data.serial)
    client = AsyncMock(spec=api_mod.Healthbox3ApiClient)
    client.async_get_v2_data_current.side_effect = api_mod.Healthbox3AuthenticationError(
        "expired"
    )
    client.async_get_v1_data_current.return_value = v1_data
    client.async_get_boost.return_value = boost_status

    coordinator = Healthbox3DataUpdateCoordinator(hass, entry, client, use_v2=True)
    await coordinator.async_refresh()

    assert coordinator.use_v2 is False
    assert coordinator.last_update_success is True

    progress = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(f["context"].get("source") == SOURCE_REAUTH for f in progress)


async def test_invalid_response_disambiguated_via_key_status(hass, v2_data):
    """A v2 parse failure while the key is still valid is transient, not a reauth trigger."""
    entry = make_config_entry(hass, serial=v2_data.serial)
    client = AsyncMock(spec=api_mod.Healthbox3ApiClient)
    client.async_get_v2_data_current.side_effect = api_mod.Healthbox3InvalidResponseError(
        "garbled"
    )
    client.async_get_api_key_status.return_value = api_mod.ApiKeyStatus(
        state="valid",
        disable_telemetry_data_allowed=True,
        local_sensor_data_allowed=True,
    )

    coordinator = Healthbox3DataUpdateCoordinator(hass, entry, client, use_v2=True)
    await coordinator.async_refresh()

    assert coordinator.use_v2 is True  # not downgraded - key is still valid
    assert coordinator.last_update_success is False
