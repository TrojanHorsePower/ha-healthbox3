"""Switch platform for the Renson Healthbox 3 integration."""

from __future__ import annotations

from typing import Any, override

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import Healthbox3ConfigEntry, Healthbox3DataUpdateCoordinator
from .entity import Healthbox3Entity

# Device-wide settings, changed rarely; nothing to throttle.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Healthbox3ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Healthbox 3 switches from a config entry.

    Only available with an active API key - see const.py's API_V1_DECISION
    comment for why that's treated as required rather than assumed optional.
    """
    coordinator = entry.runtime_data
    if not coordinator.use_v2:
        return

    serial = coordinator.data.healthbox.serial
    async_add_entities(
        [
            Healthbox3DemandControlSwitch(coordinator, serial),
            Healthbox3SilentSwitch(coordinator, serial),
        ]
    )


class Healthbox3DemandControlSwitch(Healthbox3Entity, SwitchEntity):
    """Toggle demand-controlled ventilation on or off.

    Off means the device falls back to a fixed/scheduled ventilation rate
    instead of continuously adjusting based on live sensor readings - the
    device's own `/v1/decision` schema also supports a full per-weekday
    schedule for that fallback mode, deliberately not built here (not
    requested, and a much bigger feature than a simple toggle).

    Presents/writes the negation of the raw `program.enable` field
    (`DeviceDecision.program_enabled` / `async_set_program_enable`).
    Confirmed on real hardware: a fresh `/v1/decision` fetch showed
    `program.enable: false` while the Renson app displayed demand control
    as ON at that same moment - `program.enable` tracks whether the
    clock/schedule fallback is active, the opposite concept from "demand
    control is active". See DeviceDecision.program_enabled's docstring.
    """

    _attr_translation_key = "demand_control"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: Healthbox3DataUpdateCoordinator, serial: str
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_demand_control"

    @property
    @override
    def available(self) -> bool:
        """Return whether the device's decision data is known."""
        return super().available and self.coordinator.data.decision is not None

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether demand control is currently enabled (the
        negation of the raw `program.enable` field - see class docstring).
        """
        decision = self.coordinator.data.decision
        return not decision.program_enabled if decision is not None else None

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable demand control (writes program.enable=False)."""
        await self.coordinator.client.async_set_program_enable(False)
        await self.coordinator.async_request_refresh()

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable demand control (writes program.enable=True)."""
        await self.coordinator.client.async_set_program_enable(True)
        await self.coordinator.async_request_refresh()


class Healthbox3SilentSwitch(Healthbox3Entity, SwitchEntity):
    """Toggle the silent (reduced-noise) schedule on or off.

    Presents/writes the raw `silent.enable` field as-is, unlike
    demand control's `program.enable` (see
    Healthbox3DemandControlSwitch). Unlike CO2 threshold and demand
    control, no vendor JS or PDF reference ever mentions "silent" at
    all - this feature has zero corroborating source to cross-check
    field semantics against. Explicitly verified anyway: confirmed
    directly against the Renson app that this switch's on/off state
    matches the app's Silent toggle, with no inversion - the raw field
    is correct as bound, not just unconfirmed-and-assumed-fine.
    """

    _attr_translation_key = "silent"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: Healthbox3DataUpdateCoordinator, serial: str
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_silent"

    @property
    @override
    def available(self) -> bool:
        """Return whether the device's decision data is known."""
        return super().available and self.coordinator.data.decision is not None

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether the silent schedule is currently enabled."""
        decision = self.coordinator.data.decision
        return decision.silent.enable if decision is not None else None

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the silent schedule."""
        await self.coordinator.client.async_set_silent_enable(True)
        await self.coordinator.async_request_refresh()

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the silent schedule."""
        await self.coordinator.client.async_set_silent_enable(False)
        await self.coordinator.async_request_refresh()
