"""Switch platform for the Renson Healthbox 3 integration."""

from __future__ import annotations

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
            Healthbox3BreezeSwitch(coordinator, serial),
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
    def available(self) -> bool:
        """Return whether the device's decision data is known."""
        return super().available and self.coordinator.data.decision is not None

    @property
    def is_on(self) -> bool | None:
        """Return whether demand control is currently enabled."""
        decision = self.coordinator.data.decision
        return decision.program_enabled if decision is not None else None

    async def async_turn_on(self, **kwargs) -> None:
        """Enable demand control."""
        await self.coordinator.client.async_set_demand_control(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable demand control."""
        await self.coordinator.client.async_set_demand_control(False)
        await self.coordinator.async_request_refresh()


class Healthbox3BreezeSwitch(Healthbox3Entity, SwitchEntity):
    """Toggle Breeze (temperature-triggered night cooling) on or off."""

    _attr_translation_key = "breeze"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: Healthbox3DataUpdateCoordinator, serial: str
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_breeze"

    @property
    def available(self) -> bool:
        """Return whether the device's breeze data is known."""
        return super().available and self.coordinator.data.breeze is not None

    @property
    def is_on(self) -> bool | None:
        """Return whether Breeze is currently enabled."""
        breeze = self.coordinator.data.breeze
        return breeze.enable if breeze is not None else None

    async def async_turn_on(self, **kwargs) -> None:
        """Enable Breeze."""
        await self.coordinator.client.async_set_breeze_enable(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable Breeze."""
        await self.coordinator.client.async_set_breeze_enable(False)
        await self.coordinator.async_request_refresh()


class Healthbox3SilentSwitch(Healthbox3Entity, SwitchEntity):
    """Toggle the silent (reduced-noise) schedule on or off."""

    _attr_translation_key = "silent"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: Healthbox3DataUpdateCoordinator, serial: str
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_silent"

    @property
    def available(self) -> bool:
        """Return whether the device's decision data is known."""
        return super().available and self.coordinator.data.decision is not None

    @property
    def is_on(self) -> bool | None:
        """Return whether the silent schedule is currently enabled."""
        decision = self.coordinator.data.decision
        return decision.silent.enable if decision is not None else None

    async def async_turn_on(self, **kwargs) -> None:
        """Enable the silent schedule."""
        await self.coordinator.client.async_set_silent_enable(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable the silent schedule."""
        await self.coordinator.client.async_set_silent_enable(False)
        await self.coordinator.async_request_refresh()
