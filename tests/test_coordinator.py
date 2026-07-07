"""Tests for the Healthbox3 DataUpdateCoordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_REAUTH

from custom_components.healthbox3 import api as api_mod
from custom_components.healthbox3.const import DOMAIN
from custom_components.healthbox3.coordinator import Healthbox3DataUpdateCoordinator

from .conftest import make_config_entry


def _discovery_info(*, ip: str, serial: str) -> api_mod.DiscoveryInfo:
    return api_mod.DiscoveryInfo(
        device="HEALTHBOX3",
        firmware_version="2.6.9",
        ip=ip,
        mac="00:11:22:33:44:55",
        serial=serial,
        warranty_number="warranty-123",
        scope="HEALTHBOX3",
        description="Healthbox 3.0",
    )


def _patch_discover_broadcast(return_value=None, side_effect=None):
    return patch(
        "custom_components.healthbox3.coordinator.async_discover_broadcast",
        AsyncMock(return_value=return_value, side_effect=side_effect),
    )


def _patch_create_flow():
    return patch("custom_components.healthbox3.coordinator.discovery_flow.async_create_flow")


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


async def test_relocate_triggered_when_broadcast_finds_device_at_new_ip(hass, v1_data):
    """A connection error, plus a broadcast reply with this entry's own
    serial at a different IP than currently stored, must trigger a
    relocate flow with the new host.
    """
    entry = make_config_entry(hass, serial=v1_data.serial)
    client = AsyncMock(spec=api_mod.Healthbox3ApiClient)
    client.async_get_v1_data_current.side_effect = api_mod.Healthbox3ConnectionError(
        "offline"
    )

    with (
        _patch_discover_broadcast(
            return_value=[_discovery_info(ip="192.0.2.99", serial=v1_data.serial)]
        ),
        _patch_create_flow() as mock_create_flow,
    ):
        coordinator = Healthbox3DataUpdateCoordinator(hass, entry, client, use_v2=False)
        await coordinator.async_refresh()

    mock_create_flow.assert_called_once()
    _hass, domain = mock_create_flow.call_args.args
    assert domain == DOMAIN
    assert mock_create_flow.call_args.kwargs["context"] == {
        "source": "integration_discovery"
    }
    assert mock_create_flow.call_args.kwargs["data"] == {"host": "192.0.2.99"}


async def test_relocate_not_triggered_when_broadcast_finds_same_ip(hass, v1_data):
    """The device answering at the same IP it's already configured with
    is not a relocation - nothing to do.
    """
    entry = make_config_entry(hass, serial=v1_data.serial)
    client = AsyncMock(spec=api_mod.Healthbox3ApiClient)
    client.async_get_v1_data_current.side_effect = api_mod.Healthbox3ConnectionError(
        "offline"
    )

    with (
        _patch_discover_broadcast(
            return_value=[_discovery_info(ip="192.0.2.1", serial=v1_data.serial)]
        ),
        _patch_create_flow() as mock_create_flow,
    ):
        coordinator = Healthbox3DataUpdateCoordinator(hass, entry, client, use_v2=False)
        await coordinator.async_refresh()

    mock_create_flow.assert_not_called()


async def test_relocate_not_triggered_when_no_serial_match(hass, v1_data):
    """A broadcast reply from an unrelated device must not trigger a relocate."""
    entry = make_config_entry(hass, serial=v1_data.serial)
    client = AsyncMock(spec=api_mod.Healthbox3ApiClient)
    client.async_get_v1_data_current.side_effect = api_mod.Healthbox3ConnectionError(
        "offline"
    )

    with (
        _patch_discover_broadcast(
            return_value=[_discovery_info(ip="192.0.2.99", serial="some-other-serial")]
        ),
        _patch_create_flow() as mock_create_flow,
    ):
        coordinator = Healthbox3DataUpdateCoordinator(hass, entry, client, use_v2=False)
        await coordinator.async_refresh()

    mock_create_flow.assert_not_called()


async def test_relocate_swallows_broadcast_socket_error(hass, v1_data):
    """A real socket-creation failure during the relocate probe must not
    raise past the coordinator's own connection-error handling.
    """
    entry = make_config_entry(hass, serial=v1_data.serial)
    client = AsyncMock(spec=api_mod.Healthbox3ApiClient)
    client.async_get_v1_data_current.side_effect = api_mod.Healthbox3ConnectionError(
        "offline"
    )

    with (
        _patch_discover_broadcast(side_effect=OSError("network unreachable")),
        _patch_create_flow() as mock_create_flow,
    ):
        coordinator = Healthbox3DataUpdateCoordinator(hass, entry, client, use_v2=False)
        await coordinator.async_refresh()

    assert coordinator.last_update_success is False
    mock_create_flow.assert_not_called()


async def test_relocate_attempted_once_per_outage_then_reset_on_success(hass, v1_data):
    """Must not re-probe on every failed poll while the outage continues -
    only once, until a poll succeeds again.
    """
    entry = make_config_entry(hass, serial=v1_data.serial)
    client = AsyncMock(spec=api_mod.Healthbox3ApiClient)
    client.async_get_v1_data_current.side_effect = api_mod.Healthbox3ConnectionError(
        "offline"
    )

    with (
        _patch_discover_broadcast(return_value=[]) as mock_discover,
        _patch_create_flow(),
    ):
        coordinator = Healthbox3DataUpdateCoordinator(hass, entry, client, use_v2=False)
        await coordinator.async_refresh()
        await coordinator.async_refresh()

    assert mock_discover.await_count == 1

    # A successful poll resets the flag, so the next failure probes again.
    client.async_get_v1_data_current.side_effect = None
    client.async_get_v1_data_current.return_value = v1_data
    await coordinator.async_refresh()

    client.async_get_v1_data_current.side_effect = api_mod.Healthbox3ConnectionError(
        "offline again"
    )
    with (
        _patch_discover_broadcast(return_value=[]) as mock_discover,
        _patch_create_flow(),
    ):
        await coordinator.async_refresh()

    assert mock_discover.await_count == 1


async def test_relocate_triggered_on_v2_connection_error(hass, v2_data):
    """The v2 polling path hits a different except-branch than v1's own
    _async_get_v1_data - must trigger a relocate too.
    """
    entry = make_config_entry(hass, serial=v2_data.serial)
    client = AsyncMock(spec=api_mod.Healthbox3ApiClient)
    client.async_get_v2_data_current.side_effect = api_mod.Healthbox3ConnectionError(
        "offline"
    )

    with (
        _patch_discover_broadcast(
            return_value=[_discovery_info(ip="192.0.2.99", serial=v2_data.serial)]
        ),
        _patch_create_flow() as mock_create_flow,
    ):
        coordinator = Healthbox3DataUpdateCoordinator(hass, entry, client, use_v2=True)
        await coordinator.async_refresh()

    mock_create_flow.assert_called_once()


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
