"""Binary sensors for the Healthbox 3 unit."""

from __future__ import annotations

from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import Healthbox3ConfigEntry, Healthbox3DataUpdateCoordinator
from .entity import Healthbox3Entity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Healthbox3ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the unit's binary sensors from a config entry."""
    coordinator = entry.runtime_data
    serial = coordinator.data.healthbox.serial

    entities: list[Healthbox3Entity] = []
    global_info = coordinator.data.global_info
    # Only a Wi-Fi unit has an internet state worth reporting. A wired unit
    # reports on a Wi-Fi radio that is switched off, which would read as a fault.
    if global_info is not None and global_info.interface_type == "WIFI":
        entities.append(Healthbox3InternetBinarySensor(coordinator, serial))

    async_add_entities(entities)


class Healthbox3InternetBinarySensor(Healthbox3Entity, BinarySensorEntity):
    """Whether the unit reports having internet access.

    Not the same as being reachable: the integration talks to the unit over
    the LAN and keeps working without internet. Internet access matters
    because the device validates its API key over it, so when the advanced
    sensors stop updating, this is the first place to look.

    Unknown when the Wi-Fi status could not be read, which is not the same as
    the unit being offline.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "internet_connection"

    def __init__(
        self, coordinator: Healthbox3DataUpdateCoordinator, serial: str
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_internet_connection"

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether the unit reports internet access, or None if unknown."""
        wifi = self.coordinator.data.wifi
        return wifi.internet_connection if wifi is not None else None
