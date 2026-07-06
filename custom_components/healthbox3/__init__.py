"""The Renson Healthbox 3 integration."""

from __future__ import annotations

from homeassistant.const import CONF_API_KEY, CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import Healthbox3ApiClient, Healthbox3ConnectionError, Healthbox3Error
from .coordinator import Healthbox3ConfigEntry, Healthbox3DataUpdateCoordinator

PLATFORMS = [Platform.FAN, Platform.SELECT, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: Healthbox3ConfigEntry) -> bool:
    """Set up Renson Healthbox 3 from a config entry."""
    client = Healthbox3ApiClient(entry.data[CONF_HOST], async_get_clientsession(hass))

    # Activation is a one-time, device-side state change (confirmed: the
    # device never expects a per-request Authorization header), not
    # something scoped to this config entry. So privileged access may
    # already be active even if the user never gave us a key - e.g. they
    # POSTed it directly per the Renson docs instead of through our config
    # flow. Always ask the device, rather than trusting only what we stored.
    try:
        status = await client.async_get_api_key_status()
    except Healthbox3ConnectionError as err:
        raise ConfigEntryNotReady(
            f"Error connecting to Healthbox 3 at {entry.data[CONF_HOST]}"
        ) from err
    except Healthbox3Error as err:
        raise ConfigEntryNotReady(
            "Unexpected error checking Healthbox 3 API key status"
        ) from err

    use_v2 = status.is_valid
    if entry.data.get(CONF_API_KEY) and not status.is_valid:
        # The user told us they had a working key; the device now disagrees.
        raise ConfigEntryAuthFailed("Healthbox 3 API key is no longer valid")

    coordinator = Healthbox3DataUpdateCoordinator(
        hass, entry, client, use_v2=use_v2
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: Healthbox3ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
