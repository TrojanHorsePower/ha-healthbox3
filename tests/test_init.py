"""Tests for Healthbox3 config entry setup/unload."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigEntryState, SOURCE_REAUTH

from custom_components.healthbox3 import api as api_mod
from custom_components.healthbox3.const import DOMAIN

from .conftest import make_config_entry, setup_integration


async def test_setup_entry_without_api_key_uses_v1(hass, mock_api_client, v1_data, boost_status):
    entry = await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        api_key=None,
        healthbox_data=v1_data,
        boost_status=boost_status,
    )

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.use_v2 is False
    # The device is always asked, even with no key on file - see
    # test_setup_entry_detects_externally_activated_key below.
    mock_api_client.async_get_api_key_status.assert_awaited_once()


async def test_setup_entry_detects_externally_activated_key(
    hass, mock_api_client, v2_data, boost_status
):
    """A key POSTed directly to the device (bypassing our config flow
    entirely, e.g. via curl per Renson's docs) must still be picked up,
    since activation lives on the device, not in what this config entry
    remembers.
    """
    entry = await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        api_key=None,
        api_key_valid=True,
        healthbox_data=v2_data,
        boost_status=boost_status,
    )

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.use_v2 is True


async def test_setup_entry_with_valid_api_key_uses_v2(hass, mock_api_client, v2_data, boost_status):
    entry = await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
    )

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.use_v2 is True


async def test_setup_entry_with_already_invalid_key_triggers_reauth(hass, mock_api_client, v2_data):
    mock_api_client.async_get_api_key_status = AsyncMock(
        return_value=api_mod.ApiKeyStatus(
            state="empty",
            disable_telemetry_data_allowed=False,
            local_sensor_data_allowed=False,
        )
    )
    entry = make_config_entry(hass, serial=v2_data.serial)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    progress = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(f["context"].get("source") == SOURCE_REAUTH for f in progress)


async def test_setup_entry_connection_error_retries(hass, mock_api_client, v2_data):
    mock_api_client.async_get_api_key_status = AsyncMock(
        side_effect=api_mod.Healthbox3ConnectionError("offline")
    )
    entry = make_config_entry(hass, serial=v2_data.serial)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload_entry(hass, mock_api_client, v1_data, boost_status):
    entry = await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        api_key=None,
        healthbox_data=v1_data,
        boost_status=boost_status,
    )

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
