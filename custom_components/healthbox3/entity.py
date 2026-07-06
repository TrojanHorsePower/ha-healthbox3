"""Shared base entity for the Renson Healthbox 3 integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Healthbox3DataUpdateCoordinator


class Healthbox3Entity(CoordinatorEntity[Healthbox3DataUpdateCoordinator]):
    """Base entity tying every platform entity to a single Healthbox device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Healthbox3DataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._serial = serial
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            manufacturer="Renson",
            model="Healthbox 3.0",
            name=coordinator.data.healthbox.description,
            serial_number=serial,
        )


def room_exists(coordinator: Healthbox3DataUpdateCoordinator, room_id: int) -> bool:
    """Return whether the device currently reports a room with this id.

    Confirmed on real hardware: acting on an unknown room id returns a bare
    500 with an empty body, indistinguishable from "device is broken" - so
    entities that act on a specific room id check this first rather than
    ever sending that request.
    """
    return any(r.id == room_id for r in coordinator.data.healthbox.rooms)
