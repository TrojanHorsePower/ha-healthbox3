"""Tests for the Healthbox3 config flow."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.const import CONF_API_KEY, CONF_HOST
from homeassistant.data_entry_flow import FlowResultType

from custom_components.healthbox3 import api as api_mod
from custom_components.healthbox3.const import DOMAIN

from .conftest import make_config_entry


def _patch_client():
    return patch("custom_components.healthbox3.config_flow.Healthbox3ApiClient")


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
