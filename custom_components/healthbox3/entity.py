"""Shared base entity for the Renson Healthbox 3 integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import (
    Healthbox3DataUpdateCoordinator,
    unit_configuration_url,
    unit_connections,
)


@dataclass(frozen=True)
class RoomRef:
    """The room an entity belongs to. Its name becomes the room device's name."""

    id: int
    name: str


def unit_device_info(coordinator: Healthbox3DataUpdateCoordinator, serial: str) -> DeviceInfo:
    """Return the device entry for the unit as a whole.

    The MAC and the device's web-UI address come from the global info, when
    the device reported them. The coordinator keeps them current on each poll.
    """
    info = DeviceInfo(
        identifiers={(DOMAIN, serial)},
        manufacturer="Renson",
        model="Healthbox 3.0",
        name=coordinator.data.healthbox.description,
        serial_number=serial,
    )
    global_info = coordinator.data.global_info
    if global_info is not None:
        info["connections"] = unit_connections(global_info)
        info["configuration_url"] = unit_configuration_url(global_info)
    return info


def room_device_info(
    coordinator: Healthbox3DataUpdateCoordinator, serial: str, room: RoomRef
) -> DeviceInfo:
    """Return the device entry for one ventilated room.

    `via_device_id` takes the unit's registry id, not its identifiers, so the
    unit device must already exist. async_setup_entry creates it before any
    platform is forwarded, which is what makes that id available here.
    """
    assert coordinator.unit_device_id is not None, (
        "the unit device must be created before any room entity"
    )
    return DeviceInfo(
        identifiers={(DOMAIN, f"{serial}_room{room.id}")},
        manufacturer="Renson",
        model="Air valve",
        name=room.name,
        via_device_id=coordinator.unit_device_id,
    )


class Healthbox3Entity(CoordinatorEntity[Healthbox3DataUpdateCoordinator]):
    """Base entity tying every platform entity to a device.

    Unit-level entities belong to the unit device. Room-level entities pass
    `room` and belong to that room's own device, linked to the unit. Entity
    names therefore leave out the room name: the device supplies it.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Healthbox3DataUpdateCoordinator,
        serial: str,
        *,
        room: RoomRef | None = None,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._serial = serial
        if room is None:
            self._attr_device_info = unit_device_info(coordinator, serial)
        else:
            self._attr_device_info = room_device_info(coordinator, serial, room)


def room_exists(coordinator: Healthbox3DataUpdateCoordinator, room_id: int) -> bool:
    """Return whether the device currently reports a room with this id.

    Confirmed on real hardware: acting on an unknown room id returns a bare
    500 with an empty body, indistinguishable from "device is broken" - so
    entities that act on a specific room id check this first rather than
    ever sending that request.
    """
    return any(r.id == room_id for r in coordinator.data.healthbox.rooms)
