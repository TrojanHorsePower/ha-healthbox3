"""Config flow for the Renson Healthbox 3 integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_API_KEY, CONF_HOST
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import Healthbox3ApiClient, Healthbox3ConnectionError, Healthbox3Error
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class Healthbox3ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Renson Healthbox 3."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._host: str | None = None
        self._serial: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the device IP and validate v1 connectivity."""
        errors: dict[str, str] = {}
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
                self._abort_if_unique_id_configured()
                self._host = host
                self._serial = data.serial
                return await self.async_step_api_key()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )

    async def async_step_api_key(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for an optional API key and activate/verify it if given."""
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
