"""The system health page: what it shows, and what it must never show."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from homeassistant.components import system_health
from homeassistant.config_entries import ConfigEntryState
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import get_system_health_info

from custom_components.healthbox3 import api as api_mod
from custom_components.healthbox3.const import DOMAIN

from .conftest import make_config_entry, setup_integration

_SERIAL = "SERIAL123"


async def _info(hass):
    # The page is registered by the integration; the helper reads it back.
    assert await async_setup_component(hass, "system_health", {})
    return await get_system_health_info(hass, DOMAIN)


async def test_single_unit_page_shows_device_state(hass, mock_api_client, v1_data, boost_status):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        healthbox_data=v1_data,
        boost_status=boost_status,
        global_info=api_mod.GlobalInfo(firmware_version="2.6.9"),
    )

    with patch.object(
        system_health, "async_check_can_reach_url", AsyncMock(return_value="ok")
    ):
        info = await _info(hass)

    assert info["firmware_version"] == "2.6.9"
    assert info["api_key_active"] == "yes"
    assert info["poll_interval_seconds"] == 30
    assert info["last_poll_successful"] == "yes"
    assert info["rooms"] == len(v1_data.rooms)
    # Left as a coroutine on purpose: the frontend awaits the check itself.
    assert await info["can_reach_device"] == "ok"


async def test_no_loaded_unit_gives_an_empty_page(hass, mock_api_client):
    # The device cannot be reached, so the entry is configured but not loaded.
    mock_api_client.async_get_api_key_status.side_effect = api_mod.Healthbox3ConnectionError(
        "offline"
    )
    entry = make_config_entry(hass, serial=_SERIAL)
    await hass.config_entries.async_setup(entry.entry_id)

    assert entry.state is not ConfigEntryState.LOADED
    assert await _info(hass) == {}


async def test_several_units_share_numbered_rows(hass, mock_api_client, v1_data, boost_status):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        healthbox_data=v1_data,
        boost_status=boost_status,
        global_info=api_mod.GlobalInfo(firmware_version="2.6.9"),
    )
    entry = next(iter(hass.config_entries.async_loaded_entries(DOMAIN)))

    with patch.object(
        system_health,
        "async_check_can_reach_url",
        AsyncMock(side_effect=["ok", {"type": "failed", "error": "timeout"}]),
    ), patch.object(
        type(hass.config_entries),
        "async_loaded_entries",
        lambda self, domain: [entry, entry],
    ):
        # Two units, simulated by listing the one loaded entry twice.
        info = await _info(hass)

    assert info["can_reach_device"] == "#1: ok; #2: failed (timeout)"
    assert info["firmware_version"] == "#1: 2.6.9; #2: 2.6.9"


async def test_page_never_contains_identifying_values(hass, mock_api_client, v1_data, boost_status):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        healthbox_data=v1_data,
        boost_status=boost_status,
        global_info=api_mod.GlobalInfo(
            firmware_version="2.6.9", mac="00:11:22:33:44:55", ip="192.0.2.10"
        ),
    )

    with patch.object(
        system_health, "async_check_can_reach_url", AsyncMock(return_value="ok")
    ):
        info = await _info(hass)
        await info["can_reach_device"]
    text = json.dumps(info, default=str)

    for forbidden in (v1_data.serial, "00:11:22:33:44:55", "192.0.2.10", "Healthbox 3 ("):
        assert forbidden not in text
