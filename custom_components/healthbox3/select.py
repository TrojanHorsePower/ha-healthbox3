"""Select platform for the Renson Healthbox 3 integration (room profile)."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, PROFILES
from .coordinator import Healthbox3ConfigEntry, Healthbox3DataUpdateCoordinator
from .entity import Healthbox3Entity

# Profile changes are a low-frequency user action against a single small
# device; the coordinator (not per-entity polling) owns concurrency for
# reads, so there's nothing meaningful to throttle here.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Healthbox3ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Healthbox 3 profile selects from a config entry.

    Only available with an active API key: v1 does not expose profile_name.
    """
    coordinator = entry.runtime_data
    if not coordinator.use_v2:
        return

    serial = coordinator.data.healthbox.serial
    async_add_entities(
        Healthbox3ProfileSelect(coordinator, serial, room.id, room.name)
        for room in coordinator.data.healthbox.rooms
    )


class Healthbox3ProfileSelect(Healthbox3Entity, SelectEntity):
    """Select the ventilation profile (eco/health/intense) for a room.

    Always reads/writes the string-based profile_name field, never the
    index-based `profile` field also present elsewhere in the API - see
    RoomDecision's docstring in api.py for why that index isn't trusted.
    """

    _attr_translation_key = "room_profile"
    _attr_options = PROFILES

    def __init__(
        self,
        coordinator: Healthbox3DataUpdateCoordinator,
        serial: str,
        room_id: int,
        room_name: str,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator, serial)
        self._room_id = room_id
        self._attr_translation_placeholders = {"room_name": room_name}
        self._attr_unique_id = f"{serial}_room{room_id}_profile"

    def _room(self):
        return next(
            (r for r in self.coordinator.data.healthbox.rooms if r.id == self._room_id),
            None,
        )

    @property
    def available(self) -> bool:
        """Return whether this room's profile is known."""
        room = self._room()
        return super().available and room is not None and room.profile_name is not None

    @property
    def current_option(self) -> str | None:
        """Return the room's current ventilation profile."""
        room = self._room()
        return room.profile_name if room is not None else None

    async def async_select_option(self, option: str) -> None:
        """Set the room's ventilation profile."""
        if self._room() is None:
            # Confirmed on real hardware: acting on an unknown room id
            # returns a bare 500 with an empty body, indistinguishable from
            # "device is broken" - check against the coordinator's own room
            # list first rather than let that reach the device.
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="room_not_found",
                translation_placeholders={"room_id": str(self._room_id)},
            )
        await self.coordinator.client.async_set_profile(self._room_id, option)
        await self.coordinator.async_request_refresh()
