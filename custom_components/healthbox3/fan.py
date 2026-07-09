"""Fan platform for the Renson Healthbox 3 integration (room boost control).

Modeled as a fan because Home Assistant's fan platform gets a first-class
more-info dialog and Tile card (percentage slider + preset picker in one
control), which reads much better for "boost" than a switch plus two
number entities.

Turning a boost fan off does NOT stop ventilation in the room - the
Healthbox always ventilates every room at a baseline rate determined by
its eco/health/intense profile (see select.py). "Off" here only means
"boost cancelled, back to that normal profile-driven rate."
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.fan import (
    ATTR_PERCENTAGE,
    ATTR_PRESET_MODE,
    FanEntity,
    FanEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import BOOST_DURATION_PRESETS, BOOST_LEVEL_MAX, BOOST_LEVEL_MIN, DOMAIN
from .coordinator import (
    BoostParams,
    Healthbox3ConfigEntry,
    Healthbox3DataUpdateCoordinator,
)
from .entity import Healthbox3Entity, room_exists

_LOGGER = logging.getLogger(__name__)

# Entities only read from the coordinator (or, for restarts, issue an
# infrequent user-triggered write); the coordinator itself serializes the
# actual device polling, so there's nothing for per-entity parallel updates
# to limit.
PARALLEL_UPDATES = 0

_SUPPORTED_FEATURES = (
    FanEntityFeature.TURN_ON
    | FanEntityFeature.TURN_OFF
    | FanEntityFeature.SET_SPEED
    | FanEntityFeature.PRESET_MODE
)


def _level_to_percentage(level: float) -> int:
    """Rescale the device's real 10-200% boost level onto HA's 0-100 slider."""
    return round((level - BOOST_LEVEL_MIN) / (BOOST_LEVEL_MAX - BOOST_LEVEL_MIN) * 100)


def _percentage_to_level(percentage: int) -> float:
    """Inverse of _level_to_percentage."""
    return percentage / 100 * (BOOST_LEVEL_MAX - BOOST_LEVEL_MIN) + BOOST_LEVEL_MIN


def _preset_mode_for_timeout(timeout: int) -> str:
    """Return the curated preset label closest to a given timeout in seconds."""
    return min(
        BOOST_DURATION_PRESETS, key=lambda label: abs(BOOST_DURATION_PRESETS[label] - timeout)
    )


def _timeout_for_preset_mode(preset_mode: str) -> int:
    return BOOST_DURATION_PRESETS[preset_mode]


def _room_active(coordinator: Healthbox3DataUpdateCoordinator, room_id: int) -> bool:
    status = coordinator.data.boost.get(room_id)
    return status is not None and status.enable


def _all_rooms_active(coordinator: Healthbox3DataUpdateCoordinator) -> bool:
    return bool(coordinator.data.boost) and all(
        status.enable for status in coordinator.data.boost.values()
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Healthbox3ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Healthbox 3 boost fans from a config entry."""
    coordinator = entry.runtime_data
    serial = coordinator.data.healthbox.serial

    entities: list[Healthbox3Entity] = []
    for room in coordinator.data.healthbox.rooms:
        params = coordinator.boost_params.setdefault(
            room.id, BoostParams(level=100.0, timeout=900)
        )
        entities.append(
            Healthbox3RoomBoostFan(
                coordinator,
                serial,
                params=params,
                unique_id=f"{serial}_room{room.id}_boost",
                translation_key="room_boost",
                room_name=room.name,
                room_id=room.id,
            )
        )

    entities.append(
        Healthbox3AllBoostFan(
            coordinator,
            serial,
            params=coordinator.boost_all_params,
            unique_id=f"{serial}_boost_all",
            translation_key="boost_all",
            room_name=None,
        )
    )

    async_add_entities(entities)


class _Healthbox3BoostFan(Healthbox3Entity, RestoreEntity, FanEntity):
    """Shared boost-fan behavior for a single room or for all rooms at once.

    `percentage` and `preset_mode` are purely local UI state (there's no
    documented way to read a "pending" level/duration back from the device,
    only the currently active one), persisted across restarts via
    RestoreEntity. `is_on` mirrors the device's real, live enable state.

    Confirmed on real hardware: PUTing enable=true while boost is already
    active does not adjust it in place - it restarts the countdown from the
    new full timeout. Turning a boost fan off does not stop ventilation;
    see this module's docstring.
    """

    _attr_supported_features = _SUPPORTED_FEATURES
    _attr_preset_modes = list(BOOST_DURATION_PRESETS)

    def __init__(
        self,
        coordinator: Healthbox3DataUpdateCoordinator,
        serial: str,
        *,
        params: BoostParams,
        unique_id: str,
        translation_key: str,
        room_name: str | None,
    ) -> None:
        """Initialize the fan."""
        super().__init__(coordinator, serial)
        self._params = params
        self._attr_unique_id = unique_id
        self._attr_translation_key = translation_key
        if room_name is not None:
            self._attr_translation_placeholders = {"room_name": room_name}

    # --- overridden by subclasses ---

    def _target_room_ids(self) -> list[int]:
        raise NotImplementedError

    def _is_active(self) -> bool:
        raise NotImplementedError

    def _check_room_exists(self) -> None:
        """No-op by default; the per-room fan overrides with a real guard."""

    def _remaining(self) -> int | None:
        return None

    def _extra_available(self) -> bool:
        return True

    async def _async_apply(self, enable: bool) -> None:
        raise NotImplementedError

    # --- shared behavior ---

    @property
    def available(self) -> bool:
        """Return whether this fan's underlying boost data was fetched."""
        return super().available and self._extra_available()

    @property
    def is_on(self) -> bool | None:
        """Return whether boost is currently active."""
        return self._is_active()

    @property
    def percentage(self) -> int:
        """Return the boost level rescaled to 0-100, or 0 if boost is off."""
        if not self._is_active():
            return 0
        return max(1, _level_to_percentage(self._params.level))

    @property
    def preset_mode(self) -> str:
        """Return the curated duration preset closest to the desired timeout."""
        return _preset_mode_for_timeout(self._params.timeout)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the real (unscaled) boost level and, if known, remaining time."""
        attrs: dict[str, Any] = {"level": f"{self._params.level:.0f}%"}
        remaining = self._remaining()
        if remaining is not None:
            attrs["remaining"] = remaining
        return attrs

    async def async_added_to_hass(self) -> None:
        """Restore the last set percentage/preset_mode across restarts."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None:
            return
        percentage = last_state.attributes.get(ATTR_PERCENTAGE)
        # A restored 0 means "was off" - it carries no usable level
        # information, so leave the coordinator-seeded default in place.
        if percentage:
            self._params.level = _percentage_to_level(percentage)
        preset_mode = last_state.attributes.get(ATTR_PRESET_MODE)
        if preset_mode in BOOST_DURATION_PRESETS:
            self._params.timeout = _timeout_for_preset_mode(preset_mode)

    async def _async_activate(self) -> None:
        """PUT enable=true with the current level/timeout.

        Confirmed on real hardware: if boost is already active, this
        restarts its countdown from the full timeout rather than adjusting
        it in place - logged here so that's not a silent surprise.
        """
        if self._is_active():
            _LOGGER.info(
                "Restarting active boost for room(s) %s at level=%s%%, "
                "timeout=%ss (remaining countdown resets to the full "
                "timeout, per confirmed device behavior)",
                self._target_room_ids(),
                self._params.level,
                self._params.timeout,
            )
        await self._async_apply(True)

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn boost on, optionally at a given percentage/preset_mode."""
        self._check_room_exists()
        if preset_mode is not None:
            self._params.timeout = _timeout_for_preset_mode(preset_mode)
        if percentage:
            self._params.level = _percentage_to_level(percentage)
        await self._async_activate()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn boost off. Ventilation continues at the room's normal profile rate."""
        self._check_room_exists()
        await self._async_apply(False)

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the desired boost level (0 turns boost off)."""
        self._check_room_exists()
        if percentage == 0:
            await self._async_apply(False)
            return
        self._params.level = _percentage_to_level(percentage)
        await self._async_activate()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the desired boost duration.

        Only pushed to the device (restarting the boost) if it's currently
        active; otherwise just staged for the next time boost starts.
        """
        self._check_room_exists()
        self._params.timeout = _timeout_for_preset_mode(preset_mode)
        self.async_write_ha_state()
        if self._is_active():
            await self._async_activate()


class Healthbox3RoomBoostFan(_Healthbox3BoostFan):
    """Boost fan for a single room."""

    def __init__(
        self,
        coordinator: Healthbox3DataUpdateCoordinator,
        serial: str,
        *,
        params: BoostParams,
        unique_id: str,
        translation_key: str,
        room_name: str,
        room_id: int,
    ) -> None:
        """Initialize the fan."""
        super().__init__(
            coordinator,
            serial,
            params=params,
            unique_id=unique_id,
            translation_key=translation_key,
            room_name=room_name,
        )
        self._room_id = room_id

    def _boost_status(self):
        return self.coordinator.data.boost.get(self._room_id)

    def _target_room_ids(self) -> list[int]:
        return [self._room_id]

    def _is_active(self) -> bool:
        return _room_active(self.coordinator, self._room_id)

    def _check_room_exists(self) -> None:
        if not room_exists(self.coordinator, self._room_id):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="room_not_found",
                translation_placeholders={"room_id": str(self._room_id)},
            )

    def _remaining(self) -> int | None:
        status = self._boost_status()
        return status.remaining if status is not None else None

    def _extra_available(self) -> bool:
        return self._boost_status() is not None

    async def _async_apply(self, enable: bool) -> None:
        await self.coordinator.client.async_set_boost(
            self._room_id,
            enable=enable,
            level=self._params.level,
            timeout=self._params.timeout,
        )
        await self.coordinator.async_request_refresh()


class Healthbox3AllBoostFan(_Healthbox3BoostFan):
    """Boost fan for every room at once, at one shared level/duration.

    This mirrors Renson's own app: "boost all" is not "trigger each room at
    its own configured level" but a single global action - one shared
    level/timeout applied identically to every room. There's no such
    resource on the device itself; this synthesizes the behavior by
    calling the per-room boost endpoint for every room.
    """

    def _target_room_ids(self) -> list[int]:
        return [r.id for r in self.coordinator.data.healthbox.rooms]

    def _is_active(self) -> bool:
        return _all_rooms_active(self.coordinator)

    def _extra_available(self) -> bool:
        return bool(self.coordinator.data.boost)

    async def _async_apply(self, enable: bool) -> None:
        room_ids = self._target_room_ids()
        results = await asyncio.gather(
            *(
                self.coordinator.client.async_set_boost(
                    room_id,
                    enable=enable,
                    level=self._params.level,
                    timeout=self._params.timeout,
                )
                for room_id in room_ids
            ),
            return_exceptions=True,
        )
        failed = [
            room_id
            for room_id, result in zip(room_ids, results, strict=True)
            if isinstance(result, BaseException)
        ]
        await self.coordinator.async_request_refresh()
        if failed:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="boost_partial_failure",
                translation_placeholders={
                    "action": "start" if enable else "stop",
                    "rooms": str(failed),
                },
            )
