"""Tests for the Healthbox3 config flow."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import (
    SOURCE_INTEGRATION_DISCOVERY,
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    SOURCE_USER,
)
from homeassistant.const import CONF_API_KEY, CONF_HOST
from homeassistant.data_entry_flow import FlowResultType

from custom_components.healthbox3 import api as api_mod
from custom_components.healthbox3.const import DOMAIN

from .conftest import make_config_entry


@contextmanager
def _patch_client():
    """autospec=True so autodetected async methods (e.g. async_discover,
    added for the post-manual-entry unicast enrichment probe) become
    AsyncMocks instead of plain MagicMocks that raise TypeError when
    awaited - same reasoning as conftest.py's mock_api_client fixture.

    Defaults async_discover to "no reply" (None) so tests that don't care
    about the unicast enrichment probe keep going straight to api_key,
    exactly as they did before that probe existed; tests that do care
    override it explicitly.
    """
    with patch(
        "custom_components.healthbox3.config_flow.Healthbox3ApiClient",
        autospec=True,
    ) as mock_cls:
        mock_cls.return_value.async_discover = AsyncMock(return_value=None)
        yield mock_cls


def _discovery_info(
    *, ip: str, serial: str, description: str = "Healthbox 3.0"
) -> api_mod.DiscoveryInfo:
    return api_mod.DiscoveryInfo(
        device="HEALTHBOX3",
        firmware_version="2.6.9",
        ip=ip,
        mac="00:11:22:33:44:55",
        serial=serial,
        warranty_number="warranty-123",
        scope="HEALTHBOX3",
        description=description,
    )


async def test_user_flow_single_discovered_device_skips_to_confirm(
    hass, mock_discover_broadcast, mock_api_client, v1_data, boost_status
):
    mock_discover_broadcast.return_value = [
        _discovery_info(ip="192.0.2.1", serial=v1_data.serial)
    ]
    mock_api_client.async_get_api_key_status = AsyncMock(
        return_value=api_mod.ApiKeyStatus(
            state="empty",
            disable_telemetry_data_allowed=False,
            local_sensor_data_allowed=False,
        )
    )
    mock_api_client.async_get_v1_data_current = AsyncMock(return_value=v1_data)
    mock_api_client.async_get_boost = AsyncMock(return_value=boost_status)

    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_get_v1_data_current = AsyncMock(return_value=v1_data)

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "discovery_confirm"
        assert result["description_placeholders"]["ip"] == "192.0.2.1"

        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "api_key"

        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_HOST] == "192.0.2.1"
    await hass.async_block_till_done()


async def test_user_flow_multiple_discovered_devices_offers_selection(
    hass, mock_discover_broadcast, mock_api_client, v1_data, boost_status
):
    mock_discover_broadcast.return_value = [
        _discovery_info(
            ip="192.0.2.1", serial="serial-1", description="Healthbox 3.0 (kitchen)"
        ),
        _discovery_info(
            ip="192.0.2.2", serial="serial-2", description="Healthbox 3.0 (garage)"
        ),
    ]
    mock_api_client.async_get_api_key_status = AsyncMock(
        return_value=api_mod.ApiKeyStatus(
            state="empty",
            disable_telemetry_data_allowed=False,
            local_sensor_data_allowed=False,
        )
    )
    mock_api_client.async_get_v1_data_current = AsyncMock(return_value=v1_data)
    mock_api_client.async_get_boost = AsyncMock(return_value=boost_status)

    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_get_v1_data_current = AsyncMock(return_value=v1_data)

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "discovery_select"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.0.2.2"}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "api_key"

        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_HOST] == "192.0.2.2"
    await hass.async_block_till_done()


async def test_user_flow_no_devices_discovered_falls_back_to_manual_entry(
    hass, mock_discover_broadcast
):
    """mock_discover_broadcast defaults to returning no devices - this test
    just makes that fallback-to-manual-entry behavior explicit and named,
    rather than relying on it as an implicit side effect of every other
    user-flow test in this file.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    mock_discover_broadcast.assert_awaited_once()


async def test_user_flow_discovery_socket_error_falls_back_to_manual_entry(
    hass, mock_discover_broadcast
):
    """A real socket-creation failure (distinct from the normal "nobody
    answered" case) must be swallowed the same way - never raised into the
    flow or left hanging.
    """
    mock_discover_broadcast.side_effect = OSError("network unreachable")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_user_flow_filters_already_configured_device_from_discovery(
    hass, mock_discover_broadcast, v1_data
):
    """A network with exactly one device that's already configured must
    behave like the "0 new devices found" case (manual entry form), not
    "1 device found" (discovery_confirm) - otherwise the user would be
    routed into a dead end that just aborts as already_configured.
    """
    make_config_entry(hass, serial=v1_data.serial)
    mock_discover_broadcast.return_value = [
        _discovery_info(ip="192.0.2.1", serial=v1_data.serial)
    ]

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_user_flow_filters_already_configured_device_out_of_multiple(
    hass, mock_discover_broadcast, mock_api_client, v1_data, boost_status
):
    """Filtering can also demote a multi-device discovery down to exactly
    one new device - which must then skip straight to discovery_confirm,
    not discovery_select.
    """
    make_config_entry(hass, serial=v1_data.serial)
    new_device_data = replace(v1_data, serial="new-serial")
    mock_discover_broadcast.return_value = [
        _discovery_info(ip="192.0.2.1", serial=v1_data.serial),  # already configured
        _discovery_info(ip="192.0.2.2", serial="new-serial"),
    ]
    mock_api_client.async_get_api_key_status = AsyncMock(
        return_value=api_mod.ApiKeyStatus(
            state="empty",
            disable_telemetry_data_allowed=False,
            local_sensor_data_allowed=False,
        )
    )
    mock_api_client.async_get_v1_data_current = AsyncMock(return_value=new_device_data)
    mock_api_client.async_get_boost = AsyncMock(return_value=boost_status)

    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_get_v1_data_current = AsyncMock(return_value=new_device_data)

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "discovery_confirm"
        assert result["description_placeholders"]["ip"] == "192.0.2.2"
    await hass.async_block_till_done()


async def test_manual_entry_unicast_probe_responds_shows_discovery_confirm(
    hass, mock_discover_broadcast, mock_api_client, v1_data, boost_status
):
    """After manual entry passes the required HTTP validation, a
    responding unicast probe routes to discovery_confirm for display
    enrichment - and confirming it must NOT re-run that HTTP validation.
    """
    discovered = _discovery_info(ip="192.0.2.1", serial=v1_data.serial)
    mock_api_client.async_get_api_key_status = AsyncMock(
        return_value=api_mod.ApiKeyStatus(
            state="empty",
            disable_telemetry_data_allowed=False,
            local_sensor_data_allowed=False,
        )
    )
    mock_api_client.async_get_v1_data_current = AsyncMock(return_value=v1_data)
    mock_api_client.async_get_boost = AsyncMock(return_value=boost_status)

    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_get_v1_data_current = AsyncMock(return_value=v1_data)
        instance.async_discover = AsyncMock(return_value=discovered)

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["step_id"] == "user"  # mock_discover_broadcast defaults to []

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.0.2.1"}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "discovery_confirm"
        assert result["description_placeholders"]["ip"] == "192.0.2.1"
        assert result["description_placeholders"]["serial"] == v1_data.serial

        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "api_key"
        instance.async_get_v1_data_current.assert_awaited_once()

        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_HOST] == "192.0.2.1"
    await hass.async_block_till_done()


async def test_manual_entry_unicast_probe_no_reply_skips_to_api_key(
    hass, mock_discover_broadcast, v1_data
):
    """The confirmed real no-reply exception (Healthbox3ConnectionError -
    _async_udp_discover wraps asyncio.wait_for's TimeoutError into this
    before it ever reaches async_discover's caller) must be swallowed and
    routed straight to api_key, exactly like today's behavior - no error,
    no hang. The device was already verified reachable via the required
    HTTP call; a failed unicast probe just means less display detail.
    """
    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_get_v1_data_current = AsyncMock(return_value=v1_data)
        instance.async_discover = AsyncMock(
            side_effect=api_mod.Healthbox3ConnectionError("no discovery reply")
        )

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.0.2.1"}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "api_key"


async def test_user_flow_success_without_api_key(
    hass, mock_api_client, v1_data, boost_status
):
    # Completing the flow triggers a real async_setup_entry via the __init__.py
    # client (a different patch target than config_flow's), so it needs its
    # own mocked responses or it would try to open a real socket.
    # __init__.py always checks api_key/status regardless of whether a key
    # was provided, so that needs mocking too even for the no-key path.
    mock_api_client.async_get_api_key_status = AsyncMock(
        return_value=api_mod.ApiKeyStatus(
            state="empty",
            disable_telemetry_data_allowed=False,
            local_sensor_data_allowed=False,
        )
    )
    mock_api_client.async_get_v1_data_current = AsyncMock(return_value=v1_data)
    mock_api_client.async_get_boost = AsyncMock(return_value=boost_status)

    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_get_v1_data_current = AsyncMock(return_value=v1_data)

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.0.2.1"}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "api_key"

        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"] == {CONF_HOST: "192.0.2.1", CONF_API_KEY: None}
    await hass.async_block_till_done()


async def test_user_flow_success_with_valid_api_key(
    hass, mock_api_client, v1_data, boost_status
):
    mock_api_client.async_get_api_key_status = AsyncMock(
        return_value=api_mod.ApiKeyStatus(
            state="valid",
            disable_telemetry_data_allowed=True,
            local_sensor_data_allowed=True,
        )
    )
    mock_api_client.async_get_v2_data_current = AsyncMock(return_value=v1_data)
    mock_api_client.async_get_boost = AsyncMock(return_value=boost_status)

    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_get_v1_data_current = AsyncMock(return_value=v1_data)
        instance.async_activate_api_key = AsyncMock(return_value=None)
        instance.async_get_api_key_status = AsyncMock(
            return_value=api_mod.ApiKeyStatus(
                state="valid",
                disable_telemetry_data_allowed=True,
                local_sensor_data_allowed=True,
            )
        )

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.0.2.1"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "goodkey"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_API_KEY] == "goodkey"
    await hass.async_block_till_done()


async def test_user_flow_cannot_connect(hass):
    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_get_v1_data_current = AsyncMock(
            side_effect=api_mod.Healthbox3ConnectionError("no route")
        )

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "10.0.0.1"}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_unknown_error(hass):
    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_get_v1_data_current = AsyncMock(
            side_effect=api_mod.Healthbox3InvalidResponseError("garbled")
        )

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "10.0.0.1"}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "unknown"}


async def test_api_key_step_invalid_key(hass, v1_data):
    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_get_v1_data_current = AsyncMock(return_value=v1_data)
        instance.async_activate_api_key = AsyncMock(
            side_effect=api_mod.Healthbox3AuthenticationError("bad key")
        )

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.0.2.1"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "badkey"}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "api_key"
        assert result["errors"] == {"base": "invalid_api_key"}


async def test_api_key_step_activation_succeeds_but_status_reports_invalid(
    hass, v1_data
):
    """Activation itself doesn't raise, but the device still reports the
    key as not valid - a different failure mode than activation raising,
    and one config_flow.py checks separately (`if not status.is_valid`).
    """
    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_get_v1_data_current = AsyncMock(return_value=v1_data)
        instance.async_activate_api_key = AsyncMock(return_value=None)
        instance.async_get_api_key_status = AsyncMock(
            return_value=api_mod.ApiKeyStatus(
                state="empty",
                disable_telemetry_data_allowed=False,
                local_sensor_data_allowed=False,
            )
        )

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.0.2.1"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "notactuallyvalid"}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "api_key"
        assert result["errors"] == {"base": "invalid_api_key"}


async def test_duplicate_device_aborts(hass, v1_data):
    make_config_entry(hass, serial=v1_data.serial)

    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_get_v1_data_current = AsyncMock(return_value=v1_data)

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.0.2.1"}
        )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"


async def test_integration_discovery_relocates_existing_entry(hass, v1_data):
    """Triggered internally by the coordinator - never shown to the user
    as a form, always resolves on the first step.
    """
    entry = make_config_entry(hass, serial=v1_data.serial)
    assert entry.data[CONF_HOST] == "192.0.2.1"

    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_get_v1_data_current = AsyncMock(return_value=v1_data)

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_INTEGRATION_DISCOVERY},
            data={CONF_HOST: "192.0.2.99"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "relocated"
    assert entry.data[CONF_HOST] == "192.0.2.99"


async def test_integration_discovery_cannot_connect_leaves_entry_untouched(hass, v1_data):
    entry = make_config_entry(hass, serial=v1_data.serial)

    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_get_v1_data_current = AsyncMock(
            side_effect=api_mod.Healthbox3ConnectionError("no route")
        )

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_INTEGRATION_DISCOVERY},
            data={CONF_HOST: "192.0.2.99"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"
    assert entry.data[CONF_HOST] == "192.0.2.1"


async def test_integration_discovery_no_matching_entry(hass, v1_data):
    """No existing entry has this serial - nothing to relocate, and this
    must not create a new entry either (it's not a "new device setup"
    path, only a relocate-existing one).
    """
    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_get_v1_data_current = AsyncMock(return_value=v1_data)

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_INTEGRATION_DISCOVERY},
            data={CONF_HOST: "192.0.2.99"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_matching_entry"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 0


async def test_reauth_flow_success_updates_entry(
    hass, mock_api_client, v1_data, boost_status
):
    entry = make_config_entry(hass, serial=v1_data.serial, api_key="oldkey")

    # Reauth success reloads the entry, which goes through the __init__.py
    # client (a different patch target than config_flow's) - give it mocked
    # responses so the reload succeeds instead of hitting a real socket.
    mock_api_client.async_get_api_key_status = AsyncMock(
        return_value=api_mod.ApiKeyStatus(
            state="valid",
            disable_telemetry_data_allowed=True,
            local_sensor_data_allowed=True,
        )
    )
    mock_api_client.async_get_v2_data_current = AsyncMock(return_value=v1_data)
    mock_api_client.async_get_boost = AsyncMock(return_value=boost_status)

    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_activate_api_key = AsyncMock(return_value=None)
        instance.async_get_api_key_status = AsyncMock(
            return_value=api_mod.ApiKeyStatus(
                state="valid",
                disable_telemetry_data_allowed=True,
                local_sensor_data_allowed=True,
            )
        )

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=entry.data,
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "newkey"}
        )
        await hass.async_block_till_done()

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reauth_successful"
        assert entry.data[CONF_API_KEY] == "newkey"


async def test_reauth_flow_invalid_key_shows_error(hass, v1_data):
    entry = make_config_entry(hass, serial=v1_data.serial, api_key="oldkey")

    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_activate_api_key = AsyncMock(
            side_effect=api_mod.Healthbox3AuthenticationError("bad key")
        )

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=entry.data,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "stillbad"}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_api_key"}


def _start_reconfigure(hass, entry):
    return hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )


async def test_reconfigure_flow_success_updates_host_in_place(
    hass, mock_api_client, v1_data, boost_status
):
    entry = make_config_entry(hass, serial=v1_data.serial, api_key=None)
    original_entry_id = entry.entry_id
    original_unique_id = entry.unique_id

    # Reconfigure success reloads the entry, which goes through the
    # __init__.py client (a different patch target than config_flow's).
    mock_api_client.async_get_api_key_status = AsyncMock(
        return_value=api_mod.ApiKeyStatus(
            state="empty",
            disable_telemetry_data_allowed=False,
            local_sensor_data_allowed=False,
        )
    )
    mock_api_client.async_get_v1_data_current = AsyncMock(return_value=v1_data)
    mock_api_client.async_get_boost = AsyncMock(return_value=boost_status)

    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_get_v1_data_current = AsyncMock(return_value=v1_data)

        result = await _start_reconfigure(hass, entry)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reconfigure"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.0.2.99"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "192.0.2.99"
    assert entry.entry_id == original_entry_id
    assert entry.unique_id == original_unique_id
    assert (
        len(hass.config_entries.async_entries(DOMAIN)) == 1
    ), "reconfigure must not create a duplicate entry"


async def test_reconfigure_flow_cannot_connect_leaves_entry_untouched(hass, v1_data):
    entry = make_config_entry(hass, serial=v1_data.serial)

    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_get_v1_data_current = AsyncMock(
            side_effect=api_mod.Healthbox3ConnectionError("no route")
        )

        result = await _start_reconfigure(hass, entry)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.0.2.99"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data[CONF_HOST] == "192.0.2.1"


async def test_reconfigure_flow_aborts_on_different_device_serial(hass, v1_data):
    """The unique_id-mismatch guard: a different device answering at the
    new IP must not get silently associated with this entry.
    """
    entry = make_config_entry(hass, serial=v1_data.serial)
    different_device_data = replace(v1_data, serial="a-different-serial")

    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_get_v1_data_current = AsyncMock(
            return_value=different_device_data
        )

        result = await _start_reconfigure(hass, entry)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.0.2.99"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"
    assert entry.data[CONF_HOST] == "192.0.2.1"


async def test_reconfigure_flow_preserves_api_key_when_left_blank(
    hass, mock_api_client, v1_data, boost_status
):
    entry = make_config_entry(hass, serial=v1_data.serial, api_key="oldkey")

    mock_api_client.async_get_api_key_status = AsyncMock(
        return_value=api_mod.ApiKeyStatus(
            state="valid",
            disable_telemetry_data_allowed=True,
            local_sensor_data_allowed=True,
        )
    )
    mock_api_client.async_get_v2_data_current = AsyncMock(return_value=v1_data)
    mock_api_client.async_get_boost = AsyncMock(return_value=boost_status)

    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_get_v1_data_current = AsyncMock(return_value=v1_data)

        result = await _start_reconfigure(hass, entry)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.0.2.99"}
        )
        await hass.async_block_till_done()
        instance.async_activate_api_key.assert_not_called()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "192.0.2.99"
    assert entry.data[CONF_API_KEY] == "oldkey"


async def test_reconfigure_flow_updates_api_key_when_provided(
    hass, mock_api_client, v1_data, boost_status
):
    entry = make_config_entry(hass, serial=v1_data.serial, api_key="oldkey")

    mock_api_client.async_get_api_key_status = AsyncMock(
        return_value=api_mod.ApiKeyStatus(
            state="valid",
            disable_telemetry_data_allowed=True,
            local_sensor_data_allowed=True,
        )
    )
    mock_api_client.async_get_v2_data_current = AsyncMock(return_value=v1_data)
    mock_api_client.async_get_boost = AsyncMock(return_value=boost_status)

    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_get_v1_data_current = AsyncMock(return_value=v1_data)
        instance.async_activate_api_key = AsyncMock(return_value=None)
        instance.async_get_api_key_status = AsyncMock(
            return_value=api_mod.ApiKeyStatus(
                state="valid",
                disable_telemetry_data_allowed=True,
                local_sensor_data_allowed=True,
            )
        )

        result = await _start_reconfigure(hass, entry)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "192.0.2.1", CONF_API_KEY: "newkey"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_API_KEY] == "newkey"


async def test_reconfigure_flow_invalid_new_api_key_shows_error(hass, v1_data):
    entry = make_config_entry(hass, serial=v1_data.serial, api_key="oldkey")

    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_get_v1_data_current = AsyncMock(return_value=v1_data)
        instance.async_activate_api_key = AsyncMock(
            side_effect=api_mod.Healthbox3AuthenticationError("bad key")
        )

        result = await _start_reconfigure(hass, entry)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "192.0.2.1", CONF_API_KEY: "stillbad"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": "invalid_api_key"}
    assert entry.data[CONF_API_KEY] == "oldkey"


async def test_reauth_flow_activation_succeeds_but_status_reports_invalid(
    hass, v1_data
):
    """Same distinction as the api_key step: activation doesn't raise, but
    the device still reports the key as not valid.
    """
    entry = make_config_entry(hass, serial=v1_data.serial, api_key="oldkey")

    with _patch_client() as mock_cls:
        instance = mock_cls.return_value
        instance.async_activate_api_key = AsyncMock(return_value=None)
        instance.async_get_api_key_status = AsyncMock(
            return_value=api_mod.ApiKeyStatus(
                state="empty",
                disable_telemetry_data_allowed=False,
                local_sensor_data_allowed=False,
            )
        )

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=entry.data,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "stillnotvalid"}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"
        assert result["errors"] == {"base": "invalid_api_key"}
