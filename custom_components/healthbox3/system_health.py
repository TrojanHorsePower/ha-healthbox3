"""System health for the Renson Healthbox 3 integration.

The page answers the first questions of a support exchange without a
diagnostics file: is the device answering, which firmware, is the API key
active, how often do we poll, did the last poll succeed, how many rooms.

Nothing on it identifies the device or its owner: no host, IP, MAC or serial,
and not the entry title, which contains the serial. The page is pasted into
forum threads as a screenshot, so it carries only these values.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components import system_health
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback

from .const import API_V2_API_KEY_STATUS, DOMAIN
from .coordinator import Healthbox3ConfigEntry

_UNKNOWN = "unknown"


@callback
def async_register(
    hass: HomeAssistant, register: system_health.SystemHealthRegistration
) -> None:
    """Register the system health info callback."""
    register.async_register_info(system_health_info)


def _status_url(entry: Healthbox3ConfigEntry) -> str:
    """Return the URL that tests whether the device answers.

    `/v2/api/api_key/status` is the first request setup makes, and it needs no
    key to answer. So "reachable" here means setup would get past its first
    step, not merely that something accepted a TCP connection at that address.
    """
    return f"http://{entry.data[CONF_HOST]}{API_V2_API_KEY_STATUS}"


def _firmware_version(entry: Healthbox3ConfigEntry) -> str:
    global_info = entry.runtime_data.data.global_info
    return global_info.firmware_version if global_info else _UNKNOWN


def _poll_interval(entry: Healthbox3ConfigEntry) -> int | str:
    interval = entry.runtime_data.update_interval
    return int(interval.total_seconds()) if interval else _UNKNOWN


# Read in this order on the page: from "is it there at all" to what it answered.
_VALUES: dict[str, Callable[[Healthbox3ConfigEntry], Any]] = {
    "firmware_version": _firmware_version,
    "api_key_active": lambda entry: entry.runtime_data.use_v2,
    "poll_interval_seconds": _poll_interval,
    "last_poll_successful": lambda entry: entry.runtime_data.last_update_success,
    "rooms": lambda entry: len(entry.runtime_data.data.healthbox.rooms),
}


def _render(value: Any) -> Any:
    """Spell booleans out: a bare `false` beside "API key active" reads like a
    field that failed to load.
    """
    if isinstance(value, bool):
        return "yes" if value else "no"
    return value


def _summarize(values: list[Any]) -> str:
    """Join one value per unit onto a single row, numbered in setup order.

    System health labels are translated per key, so several units cannot each
    have a labelled row of their own. The number is an ordinal rather than the
    entry title, which carries the serial.
    """
    return "; ".join(
        f"#{index}: {_render(value)}" for index, value in enumerate(values, start=1)
    )


def _render_reachability(result: str | dict[str, str]) -> str:
    """Flatten a reachability result to one line, for the multi-unit row."""
    if isinstance(result, dict):
        return f"failed ({result.get('error', _UNKNOWN)})"
    return result


async def system_health_info(hass: HomeAssistant) -> dict[str, Any]:
    """Return the info shown on the system health page."""
    entries: list[Healthbox3ConfigEntry] = hass.config_entries.async_loaded_entries(
        DOMAIN
    )
    if not entries:
        # Configured but not loaded (failed setup, or disabled): there is no
        # coordinator to read. An empty page is honest; a page of "unknown"
        # would look like the device answering badly.
        return {}

    if len(entries) == 1:
        entry = entries[0]
        return {
            # Not awaited: the frontend runs the check and renders its result,
            # including the failure shape.
            "can_reach_device": system_health.async_check_can_reach_url(
                hass, _status_url(entry)
            ),
            **{key: _render(value(entry)) for key, value in _VALUES.items()},
        }

    reachability = [
        _render_reachability(
            await system_health.async_check_can_reach_url(hass, _status_url(entry))
        )
        for entry in entries
    ]
    return {
        "can_reach_device": _summarize(reachability),
        **{key: _summarize([value(entry) for entry in entries]) for key, value in _VALUES.items()},
    }
