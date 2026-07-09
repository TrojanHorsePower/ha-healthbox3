"""Time platform for the Renson Healthbox 3 integration (silent schedule)."""

from __future__ import annotations

import datetime
from typing import override

from homeassistant.components.time import TimeEntity
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
    """Set up Healthbox 3 times from a config entry.

    Only available with an active API key - see const.py's API_V1_DECISION
    comment for why that's treated as required rather than assumed optional.
    """
    coordinator = entry.runtime_data
    if not coordinator.use_v2:
        return

    serial = coordinator.data.healthbox.serial
    async_add_entities(
        [
            Healthbox3SilentStartTime(coordinator, serial),
            Healthbox3SilentStopTime(coordinator, serial),
        ]
    )


class Healthbox3SilentStartTime(Healthbox3Entity, TimeEntity):
    """The time of day the silent schedule starts.

    Writing this reads the current stop_time from already-fetched
    coordinator data and sends both together - the wire format has no
    "just the start" write, see async_set_silent_schedule.
    """

    _attr_translation_key = "silent_start_time"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: Healthbox3DataUpdateCoordinator, serial: str
    ) -> None:
        """Initialize the time entity."""
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_silent_start_time"

    @property
    @override
    def available(self) -> bool:
        """Return whether the device's decision data is known."""
        return super().available and self.coordinator.data.decision is not None

    @property
    @override
    def native_value(self) -> datetime.time | None:
        """Return the silent schedule's current start time."""
        decision = self.coordinator.data.decision
        if decision is None:
            return None
        return datetime.time.fromisoformat(decision.silent.start_time)

    @override
    async def async_set_value(self, value: datetime.time) -> None:
        """Set the silent schedule's start time."""
        decision = self.coordinator.data.decision
        assert decision is not None  # HA only calls this when `available` is True
        stop_time = decision.silent.stop_time
        await self.coordinator.client.async_set_silent_schedule(
            start_time=value.isoformat(), stop_time=stop_time
        )
        await self.coordinator.async_request_refresh()


class Healthbox3SilentStopTime(Healthbox3Entity, TimeEntity):
    """The time of day the silent schedule stops.

    Writing this reads the current start_time from already-fetched
    coordinator data and sends both together - see
    Healthbox3SilentStartTime and async_set_silent_schedule.
    """

    _attr_translation_key = "silent_stop_time"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: Healthbox3DataUpdateCoordinator, serial: str
    ) -> None:
        """Initialize the time entity."""
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_silent_stop_time"

    @property
    @override
    def available(self) -> bool:
        """Return whether the device's decision data is known."""
        return super().available and self.coordinator.data.decision is not None

    @property
    @override
    def native_value(self) -> datetime.time | None:
        """Return the silent schedule's current stop time."""
        decision = self.coordinator.data.decision
        if decision is None:
            return None
        return datetime.time.fromisoformat(decision.silent.stop_time)

    @override
    async def async_set_value(self, value: datetime.time) -> None:
        """Set the silent schedule's stop time."""
        decision = self.coordinator.data.decision
        assert decision is not None  # HA only calls this when `available` is True
        start_time = decision.silent.start_time
        await self.coordinator.client.async_set_silent_schedule(
            start_time=start_time, stop_time=value.isoformat()
        )
        await self.coordinator.async_request_refresh()
