"""Diagnostics support for the Renson Healthbox 3 integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY, CONF_HOST
from homeassistant.core import HomeAssistant

from .coordinator import Healthbox3ConfigEntry

# Anything that could identify this device or its owner: the config entry's
# own host/key, the device's serial/warranty numbers (top-level and
# per-valve), discovery's MAC/IP (not wired into setup yet, but
# future-proofed for when it is), and the handful of global parameters that
# can carry a serial-embedded device label or a home address - confirmed
# possible per the Renson API docs, even though this author's own device
# doesn't have them set.
TO_REDACT = {
    CONF_API_KEY,
    CONF_HOST,
    "serial",
    "warranty_number",
    "warranty",
    "valve_warranty",
    "device name",
    "street",
    "postal code",
    "city",
    "MAC",
    "IP",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: Healthbox3ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    diagnostics: dict[str, Any] = {
        "entry_data": dict(entry.data),
        "use_v2": coordinator.use_v2,
        "healthbox": asdict(coordinator.data.healthbox),
        "boost": {
            str(room_id): asdict(status)
            for room_id, status in coordinator.data.boost.items()
        },
        "boost_params": {
            str(room_id): asdict(params)
            for room_id, params in coordinator.boost_params.items()
        },
        "boost_all_params": asdict(coordinator.boost_all_params),
    }
    return async_redact_data(diagnostics, TO_REDACT)
