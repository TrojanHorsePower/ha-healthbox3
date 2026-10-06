"""Network information: connection type, Wi-Fi status, and the unit's MAC and
address on its device entry.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.healthbox3 import api as api_mod
from custom_components.healthbox3.const import DOMAIN
from custom_components.healthbox3.diagnostics import async_get_config_entry_diagnostics

from .conftest import setup_integration

_PREFIX = "healthbox_3_0"
_CONNECTION_ENTITY = f"sensor.{_PREFIX}_connection_type"
_INTERNET_ENTITY = f"binary_sensor.{_PREFIX}_internet_access"

_MAC = "00:11:22:33:44:55"
_IP = "192.0.2.10"


def _global(interface: str | None, *, ip: str | None = _IP) -> api_mod.GlobalInfo:
    return api_mod.GlobalInfo(
        firmware_version="2.6.9", mac=_MAC, ip=ip, interface_type=interface
    )


def _wifi(*, internet: bool | None, ssid: str = "home-net") -> api_mod.WifiStatus:
    return api_mod.WifiStatus(
        status="connected", ssid=ssid, internet_connection=internet, connection_error=None
    )


# --- API parsing, against the real captured responses ---


def test_global_info_parses_real_shape(renson_core_global_raw):
    info = api_mod._parse_global_info(renson_core_global_raw)

    assert info.firmware_version == "2.6.9"
    assert info.interface_type == "WIFI"


def test_global_info_rejects_missing_firmware():
    with pytest.raises(api_mod.Healthbox3InvalidResponseError):
        api_mod._parse_global_info({"MAC": _MAC})


def test_wifi_status_parses_real_shape(wifi_status_raw):
    status = api_mod._parse_wifi_status(wifi_status_raw)

    assert status.status == "connected"
    assert status.internet_connection is True
    assert status.connection_error is None


# --- entities ---


async def test_wifi_unit_gets_connection_type_and_internet_entities(
    hass, mock_api_client, v1_data, boost_status
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        healthbox_data=v1_data,
        boost_status=boost_status,
        global_info=_global("WIFI"),
        wifi_status=_wifi(internet=True),
    )

    assert hass.states.get(_CONNECTION_ENTITY).state == "WIFI"
    assert hass.states.get(_INTERNET_ENTITY).state == "on"


async def test_ssid_entity_is_created_disabled_by_default(
    hass, mock_api_client, v1_data, boost_status
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        healthbox_data=v1_data,
        boost_status=boost_status,
        global_info=_global("WIFI"),
        wifi_status=_wifi(internet=True, ssid="home-net"),
    )

    # Looked up by unique ID: HA slugifies "Wi-Fi" to "wi_fi" in the entity ID.
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{v1_data.serial}_wifi_network")
    assert entity_id is not None
    assert er.async_get(hass).async_get(entity_id).disabled
    assert hass.states.get(entity_id) is None


async def test_wired_unit_gets_no_wifi_entities_and_makes_no_wifi_request(
    hass, mock_api_client, v1_data, boost_status
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        healthbox_data=v1_data,
        boost_status=boost_status,
        global_info=_global("ETHERNET"),
    )

    assert hass.states.get(_CONNECTION_ENTITY).state == "ETHERNET"
    assert hass.states.get(_INTERNET_ENTITY) is None
    assert er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{v1_data.serial}_wifi_network") is None
    mock_api_client.async_get_wifi_status.assert_not_awaited()


# --- Wi-Fi status cache ---


async def test_wifi_status_is_read_once_per_cache_ttl(
    hass, mock_api_client, v1_data, boost_status, freezer
):
    freezer.move_to("2026-10-06T12:00:00+00:00")
    entry = await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        healthbox_data=v1_data,
        boost_status=boost_status,
        global_info=_global("WIFI"),
        wifi_status=_wifi(internet=True),
    )
    coordinator = entry.runtime_data

    freezer.move_to("2026-10-06T12:04:00+00:00")
    await coordinator.async_refresh()
    assert mock_api_client.async_get_wifi_status.await_count == 1

    freezer.move_to("2026-10-06T12:06:00+00:00")
    await coordinator.async_refresh()
    assert mock_api_client.async_get_wifi_status.await_count == 2


async def test_failed_wifi_read_is_unknown_and_not_retried_until_ttl(
    hass, mock_api_client, v1_data, boost_status, freezer
):
    freezer.move_to("2026-10-06T12:00:00+00:00")
    mock_api_client.async_get_wifi_status = AsyncMock(
        side_effect=api_mod.Healthbox3ConnectionError("offline")
    )
    entry = await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        healthbox_data=v1_data,
        boost_status=boost_status,
        global_info=_global("WIFI"),
    )
    assert hass.states.get(_INTERNET_ENTITY).state == "unknown"

    freezer.move_to("2026-10-06T12:01:00+00:00")
    await entry.runtime_data.async_refresh()
    assert mock_api_client.async_get_wifi_status.await_count == 1


# --- device entry: MAC and address, kept current ---


async def test_unit_device_carries_mac_and_web_address(
    hass, mock_api_client, v1_data, boost_status
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        healthbox_data=v1_data,
        boost_status=boost_status,
        global_info=_global("WIFI"),
        wifi_status=_wifi(internet=True),
    )

    unit = next(
        iter(dr.async_get(hass).async_get_devices(identifiers={(DOMAIN, v1_data.serial)}))
    )
    assert (dr.CONNECTION_NETWORK_MAC, "00:11:22:33:44:55") in unit.connections
    assert unit.configuration_url == f"http://{_IP}"


async def test_unit_device_address_follows_an_ip_change(
    hass, mock_api_client, v1_data, boost_status
):
    entry = await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        healthbox_data=v1_data,
        boost_status=boost_status,
        global_info=_global("ETHERNET"),
    )

    mock_api_client.async_get_global_info = AsyncMock(
        return_value=_global("ETHERNET", ip="192.0.2.99")
    )
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    unit = next(
        iter(dr.async_get(hass).async_get_devices(identifiers={(DOMAIN, v1_data.serial)}))
    )
    assert unit.configuration_url == "http://192.0.2.99"


# --- diagnostics ---


async def test_diagnostics_redact_mac_ip_and_ssid(
    hass, mock_api_client, v1_data, boost_status
):
    entry = await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        healthbox_data=v1_data,
        boost_status=boost_status,
        global_info=_global("WIFI"),
        wifi_status=_wifi(internet=True, ssid="home-net"),
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["global_info"]["mac"] != _MAC
    assert diagnostics["global_info"]["ip"] != _IP
    assert diagnostics["wifi"]["ssid"] != "home-net"
    assert diagnostics["global_info"]["firmware_version"] == "2.6.9"
