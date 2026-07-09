"""Number platform for the Renson Healthbox 3 integration."""

from __future__ import annotations

from typing import override

from homeassistant.components.number import NumberDeviceClass, NumberEntity
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfRatio, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import RoomCO2Demand
from .const import (
    BREEZE_TEMP_MAX,
    BREEZE_TEMP_MIN,
    CO2_THRESHOLD_MAX,
    CO2_THRESHOLD_MIN,
    CO2_THRESHOLD_STEP,
    DOMAIN,
    GLOBAL_MINIMUM_VENTILATION_MAX,
    GLOBAL_MINIMUM_VENTILATION_MIN,
    SILENT_REDUCTION_MAX,
    SILENT_REDUCTION_MIN,
)
from .coordinator import Healthbox3ConfigEntry, Healthbox3DataUpdateCoordinator
from .entity import Healthbox3Entity, room_exists

# Device-wide settings, changed rarely; nothing to throttle.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Healthbox3ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Healthbox 3 numbers from a config entry.

    Only available with an active API key - see const.py's API_V1_DECISION
    comment for why that's treated as required rather than assumed optional.
    """
    coordinator = entry.runtime_data
    if not coordinator.use_v2:
        return

    serial = coordinator.data.healthbox.serial
    entities: list[Healthbox3Entity] = [
        Healthbox3GlobalMinimumNumber(coordinator, serial),
        Healthbox3BreezeTemperatureNumber(coordinator, serial),
        Healthbox3SilentReductionNumber(coordinator, serial),
    ]
    for room in coordinator.data.healthbox.rooms:
        room_decision = coordinator.data.room_decisions.get(room.id)
        if room_decision is not None and room_decision.co2.enable:
            entities.append(
                Healthbox3RoomCO2ThresholdNumber(coordinator, serial, room.id, room.name)
            )
    async_add_entities(entities)


class Healthbox3GlobalMinimumNumber(Healthbox3Entity, NumberEntity):
    """The device-wide minimum ventilation level, as a percentage."""

    _attr_translation_key = "minimum_ventilation_level"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = GLOBAL_MINIMUM_VENTILATION_MIN
    _attr_native_max_value = GLOBAL_MINIMUM_VENTILATION_MAX
    _attr_native_step = 1.0

    def __init__(
        self, coordinator: Healthbox3DataUpdateCoordinator, serial: str
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_minimum_ventilation_level"

    @property
    @override
    def available(self) -> bool:
        """Return whether the device's decision data is known."""
        return super().available and self.coordinator.data.decision is not None

    @property
    @override
    def native_value(self) -> float | None:
        """Return the current minimum ventilation level."""
        decision = self.coordinator.data.decision
        return decision.global_minimum if decision is not None else None

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Set the minimum ventilation level."""
        await self.coordinator.client.async_set_global_minimum(value)
        await self.coordinator.async_request_refresh()


class Healthbox3BreezeTemperatureNumber(Healthbox3Entity, NumberEntity):
    """Breeze's trigger average outdoor temperature."""

    _attr_translation_key = "breeze_temperature"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = BREEZE_TEMP_MIN
    _attr_native_max_value = BREEZE_TEMP_MAX
    _attr_native_step = 1.0

    def __init__(
        self, coordinator: Healthbox3DataUpdateCoordinator, serial: str
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_breeze_temperature"

    @property
    @override
    def available(self) -> bool:
        """Return whether the device's breeze data is known."""
        return super().available and self.coordinator.data.breeze is not None

    @property
    @override
    def native_value(self) -> float | None:
        """Return Breeze's current trigger temperature."""
        breeze = self.coordinator.data.breeze
        return breeze.average_temp if breeze is not None else None

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Set Breeze's trigger temperature."""
        await self.coordinator.client.async_set_breeze_temp(value)
        await self.coordinator.async_request_refresh()


class Healthbox3RoomCO2ThresholdNumber(Healthbox3Entity, NumberEntity):
    """The CO2 concentration (ppm) that triggers this room's demand-
    controlled ventilation to ramp toward its maximum.

    Only created for rooms that report `demand.CO2.static.enable=true` at
    setup - confirmed on real hardware that this varies per room and is
    NOT tied to room type (e.g. Kitchen), so there's no way to know ahead
    of a device fetch which rooms support it. `available` re-checks the
    same flag live, since a room can also lose it across a device config
    change.
    """

    _attr_translation_key = "room_co2_threshold"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = NumberDeviceClass.CO2
    _attr_native_unit_of_measurement = UnitOfRatio.PARTS_PER_MILLION
    _attr_native_min_value = CO2_THRESHOLD_MIN
    _attr_native_max_value = CO2_THRESHOLD_MAX
    _attr_native_step = CO2_THRESHOLD_STEP

    def __init__(
        self,
        coordinator: Healthbox3DataUpdateCoordinator,
        serial: str,
        room_id: int,
        room_name: str,
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator, serial)
        self._room_id = room_id
        self._attr_translation_placeholders = {"room_name": room_name}
        self._attr_unique_id = f"{serial}_room{room_id}_co2_threshold"

    def _co2(self) -> RoomCO2Demand | None:
        room_decision = self.coordinator.data.room_decisions.get(self._room_id)
        return room_decision.co2 if room_decision is not None else None

    @property
    @override
    def available(self) -> bool:
        """Return whether this room currently supports a CO2 threshold."""
        co2 = self._co2()
        return super().available and co2 is not None and co2.enable

    @property
    @override
    def native_value(self) -> float | None:
        """Return the room's current CO2 threshold."""
        co2 = self._co2()
        return co2.minimum if co2 is not None else None

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Set the room's CO2 threshold, preserving the current
        maximum-minimum range (the device's own web UI does the same -
        `maximum` isn't independently user-editable).
        """
        if not room_exists(self.coordinator, self._room_id):
            # Confirmed on real hardware: acting on an unknown room id
            # returns a bare 500 with an empty body, indistinguishable
            # from "device is broken" - check against the coordinator's
            # own room list first rather than let that reach the device.
            # `room_decisions` alone isn't a substitute for this: it's a
            # separate endpoint (/v2/decision/room) from data/current's
            # room list, with no guarantee it drops a room the moment
            # that room disappears from data/current. Same guard boost
            # (fan.py) and profile select (select.py) already use.
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="room_not_found",
                translation_placeholders={"room_id": str(self._room_id)},
            )
        co2 = self._co2()
        assert co2 is not None  # HA only calls this when `available` is True
        new_maximum = co2.maximum + (value - co2.minimum)
        await self.coordinator.client.async_set_room_co2_threshold(
            self._room_id, minimum=value, maximum=new_maximum
        )
        await self.coordinator.async_request_refresh()


class Healthbox3SilentReductionNumber(Healthbox3Entity, NumberEntity):
    """The ventilation reduction applied while the silent schedule is
    active, as a percentage.

    The Renson mobile app displays this with a negative sign as a purely
    cosmetic convention (e.g. "-10%") - the wire value, and this entity,
    use the positive magnitude.
    """

    _attr_translation_key = "silent_reduction"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = SILENT_REDUCTION_MIN
    _attr_native_max_value = SILENT_REDUCTION_MAX
    _attr_native_step = 1.0

    def __init__(
        self, coordinator: Healthbox3DataUpdateCoordinator, serial: str
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_silent_reduction"

    @property
    @override
    def available(self) -> bool:
        """Return whether the device's decision data is known."""
        return super().available and self.coordinator.data.decision is not None

    @property
    @override
    def native_value(self) -> float | None:
        """Return the silent schedule's current ventilation reduction."""
        decision = self.coordinator.data.decision
        return decision.silent.reduction if decision is not None else None

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Set the silent schedule's ventilation reduction."""
        await self.coordinator.client.async_set_silent_reduction(value)
        await self.coordinator.async_request_refresh()
