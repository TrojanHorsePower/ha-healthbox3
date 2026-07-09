"""Config flow for the Renson Healthbox 3 integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any, override

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_API_KEY, CONF_HOST
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .api import (
    DiscoveryInfo,
    Healthbox3ApiClient,
    Healthbox3ConnectionError,
    Healthbox3Error,
    async_discover_broadcast,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_MANUAL_HOST_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})


class Healthbox3ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Renson Healthbox 3."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._host: str | None = None
        self._serial: str | None = None
        self._discovered_device: DiscoveryInfo | None = None
        self._discovered_devices: list[DiscoveryInfo] = []

    async def _async_validate_host(self, host: str) -> dict[str, str]:
        """Validate v1 connectivity for `host` and, on success, record the
        unique id/host/serial for the rest of the flow.

        Returns an errors dict (empty on success) in the shape
        `async_show_form` expects - shared by manual entry and both
        discovery paths so none of them duplicate this logic.
        """
        client = Healthbox3ApiClient(host, async_get_clientsession(self.hass))
        try:
            data = await client.async_get_v1_data_current()
        except Healthbox3ConnectionError:
            return {"base": "cannot_connect"}
        except Healthbox3Error:
            _LOGGER.exception("Unexpected error validating Healthbox 3 at %s", host)
            return {"base": "unknown"}

        await self.async_set_unique_id(data.serial)
        self._abort_if_unique_id_configured()
        self._host = host
        self._serial = data.serial
        return {}

    async def _async_try_discover_broadcast(self) -> list[DiscoveryInfo]:
        """Best-effort broadcast discovery, already-configured devices
        filtered out.

        Any failure (e.g. a real socket-creation error, distinct from the
        normal "nobody answered" case which already comes back as an empty
        list) is treated the same as "found nothing" - discovery must never
        block or fail the flow, only skip straight to manual entry.
        """
        try:
            devices = await async_discover_broadcast()
        except OSError:
            _LOGGER.debug("Broadcast discovery failed", exc_info=True)
            return []

        current_ids = self._async_current_ids()
        return [d for d in devices if d.serial not in current_ids]

    async def _async_try_unicast_discover(self, host: str) -> DiscoveryInfo | None:
        """Best-effort unicast probe against an already-validated host, to
        enrich the confirmation display with mac/firmware.

        Purely cosmetic: `host` has already passed the required HTTP
        validation by the time this is called, so any failure here just
        means less display detail, not an unverified device - never raises,
        never blocks the flow past its own short timeout.
        """
        client = Healthbox3ApiClient(host, async_get_clientsession(self.hass))
        try:
            return await client.async_discover()
        except (Healthbox3Error, OSError):
            return None

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Attempt automatic discovery first; fall back to manual IP entry."""
        if user_input is None:
            devices = await self._async_try_discover_broadcast()
            if len(devices) == 1:
                self._discovered_device = devices[0]
                return await self.async_step_discovery_confirm()
            if len(devices) > 1:
                self._discovered_devices = devices
                return await self.async_step_discovery_select()
            return self.async_show_form(
                step_id="user", data_schema=_MANUAL_HOST_SCHEMA
            )

        errors = await self._async_validate_host(user_input[CONF_HOST])
        if errors:
            return self.async_show_form(
                step_id="user", data_schema=_MANUAL_HOST_SCHEMA, errors=errors
            )

        assert self._host is not None  # set by _async_validate_host on success
        self._discovered_device = await self._async_try_unicast_discover(self._host)
        if self._discovered_device is not None:
            return await self.async_step_discovery_confirm()
        return await self.async_step_api_key()

    async def async_step_discovery_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick from multiple broadcast-discovered devices."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._async_validate_host(user_input[CONF_HOST])
            if not errors:
                return await self.async_step_api_key()

        options = {
            device.ip: f"{device.description} ({device.ip})"
            for device in self._discovered_devices
        }
        return self.async_show_form(
            step_id="discovery_select",
            data_schema=vol.Schema({vol.Required(CONF_HOST): vol.In(options)}),
            errors=errors,
        )

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered device before continuing.

        Reached two ways: broadcast discovery (self._host is still None
        here - validation happens on submit, same as manual entry always
        has) or the manual-entry unicast enrichment probe (self._host was
        already validated before this step was even reached, so submitting
        here just continues - no redundant re-validation or unique_id
        re-set).
        """
        device = self._discovered_device
        assert device is not None  # always set before this step is reached
        errors: dict[str, str] = {}
        if user_input is not None:
            if self._host is None:
                errors = await self._async_validate_host(device.ip)
            if not errors:
                return await self.async_step_api_key()

        self._set_confirm_only()
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={
                "description": device.description,
                "ip": device.ip,
                "serial": device.serial,
            },
            errors=errors,
        )

    async def _async_relocate_or_abort(self, host: str) -> ConfigFlowResult:
        """Verify `host` via a real HTTP call and, if it matches an
        existing entry's serial, relocate that entry there; otherwise
        abort without creating anything.

        Shared body for every "an already-configured device might have
        moved" trigger - internally-triggered broadcast relocate
        (async_step_integration_discovery) and DHCP-triggered relocate
        (async_step_dhcp) both resolve on their first step this way,
        never showing the user a form. Deliberately never creates a new
        entry for an unmatched serial - relocating a known device is a
        different, narrower problem than discovering a new one, and both
        callers are reached outside the normal new-device setup path.
        """
        client = Healthbox3ApiClient(host, async_get_clientsession(self.hass))
        try:
            data = await client.async_get_v1_data_current()
        except Healthbox3Error:
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(data.serial)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host}, error="relocated")
        return self.async_abort(reason="no_matching_entry")

    @override
    async def async_step_integration_discovery(
        self, discovery_info: dict[str, Any]
    ) -> ConfigFlowResult:
        """Silently relocate an existing entry to a new IP.

        This step is only ever triggered internally, by the coordinator
        (via homeassistant.helpers.discovery_flow), after it has already
        matched a broadcast response's serial against a specific existing
        entry's own unique_id. See async_step_dhcp for Home Assistant's
        own DHCP-based discovery, a second, independent trigger for the
        same underlying relocate.
        """
        return await self._async_relocate_or_abort(discovery_info[CONF_HOST])

    @override
    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        """Silently relocate an existing entry to a new IP, triggered by
        Home Assistant's own passive DHCP discovery.

        Healthbox 3 devices broadcast a DHCP hostname of the form
        "HEALTHBOX3<serial>" (confirmed via HA's own DHCP integration
        page on one real device, firmware 2.6.9) - matched here
        hostname-only (manifest.json's "dhcp" key), deliberately never on
        macaddress, since a device's MAC changes if it's ever moved
        between WiFi and Ethernet while the hostname stays the same. Only
        observed on one device/firmware version - not guaranteed
        permanent across future Renson firmware updates (the same kind of
        silent convention change already confirmed once for the room
        profile index - see RoomDecision's docstring in api.py); worth
        re-checking here first if DHCP-based reconnection ever seems to
        stop working after a firmware update.

        Deliberately scoped the same as async_step_integration_discovery:
        relocates an existing entry if the confirmed serial matches one,
        never creates a new entry for an unmatched serial. Extending DHCP
        discovery to also drive first-time device setup is a separate,
        not-yet-decided feature.
        """
        return await self._async_relocate_or_abort(discovery_info.ip)

    async def async_step_api_key(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for an optional API key and activate/verify it if given."""
        assert self._host is not None  # set by _async_validate_host before this step
        assert self._serial is not None  # set by _async_validate_host before this step
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input.get(CONF_API_KEY) or None
            if api_key:
                client = Healthbox3ApiClient(
                    self._host, async_get_clientsession(self.hass)
                )
                try:
                    await client.async_activate_api_key(api_key)
                    status = await client.async_get_api_key_status()
                except Healthbox3Error:
                    errors["base"] = "invalid_api_key"
                else:
                    if not status.is_valid:
                        errors["base"] = "invalid_api_key"

            if not errors:
                return self.async_create_entry(
                    title=f"Healthbox 3 ({self._serial})",
                    data={CONF_HOST: self._host, CONF_API_KEY: api_key},
                )

        return self.async_show_form(
            step_id="api_key",
            data_schema=vol.Schema({vol.Optional(CONF_API_KEY): str}),
            errors=errors,
            description_placeholders={"serial": self._serial},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user change the device's IP and/or API key in place.

        Always re-validates connectivity (and, via the unique_id check,
        that this is still the *same* device by serial - not just some
        other Healthbox that happens to answer at the new IP) regardless
        of which field actually changed. The API key is only touched if
        the user actually typed a new one; leaving it blank preserves
        whatever is already stored.
        """
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            host = user_input[CONF_HOST]
            client = Healthbox3ApiClient(host, async_get_clientsession(self.hass))
            try:
                data = await client.async_get_v1_data_current()
            except Healthbox3ConnectionError:
                errors["base"] = "cannot_connect"
            except Healthbox3Error:
                _LOGGER.exception("Unexpected error validating Healthbox 3 at %s", host)
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(data.serial)
                self._abort_if_unique_id_mismatch()

                data_updates: dict[str, Any] = {CONF_HOST: host}
                new_api_key = user_input.get(CONF_API_KEY) or None
                if new_api_key:
                    try:
                        await client.async_activate_api_key(new_api_key)
                        status = await client.async_get_api_key_status()
                    except Healthbox3Error:
                        errors["base"] = "invalid_api_key"
                    else:
                        if not status.is_valid:
                            errors["base"] = "invalid_api_key"
                        else:
                            data_updates[CONF_API_KEY] = new_api_key

                if not errors:
                    return self.async_update_reload_and_abort(
                        reconfigure_entry, data_updates=data_updates
                    )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST, default=reconfigure_entry.data[CONF_HOST]
                    ): str,
                    vol.Optional(CONF_API_KEY): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauthentication when the device rejects the stored API key."""
        self._host = entry_data[CONF_HOST]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a replacement API key."""
        assert self._host is not None  # set by async_step_reauth just before this
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY]
            client = Healthbox3ApiClient(self._host, async_get_clientsession(self.hass))
            try:
                await client.async_activate_api_key(api_key)
                status = await client.async_get_api_key_status()
            except Healthbox3Error:
                errors["base"] = "invalid_api_key"
            else:
                if not status.is_valid:
                    errors["base"] = "invalid_api_key"
                else:
                    reauth_entry = self._get_reauth_entry()
                    return self.async_update_reload_and_abort(
                        reauth_entry,
                        data={**reauth_entry.data, CONF_API_KEY: api_key},
                    )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )
