"""DataUpdateCoordinator for the Renson Healthbox 3 integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
import logging
from typing import override

from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY, ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import discovery_flow
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    BoostStatus,
    BreezeSettings,
    DeviceDecision,
    Healthbox3ApiClient,
    Healthbox3AuthenticationError,
    Healthbox3ConnectionError,
    Healthbox3Error,
    Healthbox3InvalidResponseError,
    HealthboxData,
    RoomDecision,
    async_discover_broadcast,
)
from .const import (
    BOOST_DURATION_PRESETS,
    BOOST_FALLBACK_LEVEL,
    BOOST_FALLBACK_TIMEOUT,
    BOOST_LEVEL_MAX,
    BOOST_LEVEL_MIN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class Healthbox3Data:
    """Combined result of a coordinator refresh.

    Boost status lives on a separate per-room endpoint
    (`/v1/api/boost/{room_id}`), not on `data/current`, so it's fetched as
    a second step and merged in here. `decision` is `None` whenever it
    can't be fetched (no active API key, or the fetch itself failed) -
    entities built against it must treat that as "unavailable", not raise.
    """

    healthbox: HealthboxData
    boost: dict[int, BoostStatus] = field(default_factory=dict)
    decision: DeviceDecision | None = None
    breeze: BreezeSettings | None = None
    room_decisions: dict[int, RoomDecision] = field(default_factory=dict)


@dataclass
class BoostParams:
    """The level/timeout to use next time a boost is (re)started.

    This is user-editable UI state (via each boost fan entity's
    percentage/preset_mode, in fan.py), not polled device data - it lives
    on the coordinator directly rather than in Healthbox3Data, which gets
    wholesale-replaced every refresh cycle.
    """

    level: float
    timeout: int


def _clamp_level(level: float | None) -> float:
    if level is None:
        return BOOST_FALLBACK_LEVEL
    return max(BOOST_LEVEL_MIN, min(BOOST_LEVEL_MAX, level))


def _clamp_timeout(timeout: int | None) -> int:
    """Snap a device-reported timeout to the nearest curated preset.

    The fan entity's preset_mode is one of a fixed set of duration labels
    (see BOOST_DURATION_PRESETS), so any timeout we seed from the device
    must land on one of those exact values to round-trip cleanly - even
    if a room's own default_timeout isn't an exact match.
    """
    if timeout is None:
        return BOOST_FALLBACK_TIMEOUT
    return min(BOOST_DURATION_PRESETS.values(), key=lambda seconds: abs(seconds - timeout))


type Healthbox3ConfigEntry = ConfigEntry["Healthbox3DataUpdateCoordinator"]


class Healthbox3DataUpdateCoordinator(DataUpdateCoordinator[Healthbox3Data]):
    """Coordinator that polls `data/current`, using v2 if an API key is active."""

    config_entry: Healthbox3ConfigEntry  # DataUpdateCoordinator itself types
    # this ConfigEntry | None, since a coordinator can technically exist
    # without one - ours is always constructed with a real entry (see
    # __init__ below), so this narrows the type to match, the same idiom
    # used throughout HA core integrations for the same situation.

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: Healthbox3ConfigEntry,
        client: Healthbox3ApiClient,
        *,
        use_v2: bool,
        update_interval: timedelta = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.client = client
        self.use_v2 = use_v2
        self.boost_params: dict[int, BoostParams] = {}
        self.boost_all_params = BoostParams(
            level=BOOST_FALLBACK_LEVEL, timeout=BOOST_FALLBACK_TIMEOUT
        )
        self._relocate_attempted = False

    @override
    async def _async_update_data(self) -> Healthbox3Data:
        healthbox = await self._async_get_healthbox_data()
        boost = await self._async_get_boost_data(healthbox)
        decision = await self._async_get_decision_data()
        breeze = await self._async_get_breeze_data()
        room_decisions = await self._async_get_room_decisions_data()
        return Healthbox3Data(
            healthbox=healthbox,
            boost=boost,
            decision=decision,
            breeze=breeze,
            room_decisions=room_decisions,
        )

    async def _async_get_decision_data(self) -> DeviceDecision | None:
        """Fetch `/v1/decision`, tolerating failure the same way boost does.

        By this point `data/current` already succeeded, so the device is
        known reachable; a failure here just means the entities built on
        it go unavailable, not a full update failure. Also never attempted
        without an active API key - see const.py's API_V1_DECISION comment
        on why that's a deliberately conservative, not yet proven,
        assumption.
        """
        if not self.use_v2:
            return None
        try:
            return await self.client.async_get_decision()
        except Healthbox3Error as err:
            _LOGGER.debug("Failed to fetch decision data: %s", err)
            return None

    async def _async_get_breeze_data(self) -> BreezeSettings | None:
        """Fetch `/v2/decision/breeze` - same gating/tolerance as decision."""
        if not self.use_v2:
            return None
        try:
            return await self.client.async_get_breeze()
        except Healthbox3Error as err:
            _LOGGER.debug("Failed to fetch breeze data: %s", err)
            return None

    async def _async_get_room_decisions_data(self) -> dict[int, RoomDecision]:
        """Fetch `/v2/decision/room` - same gating/tolerance as decision and
        breeze, but returns `{}` (not `None`) on failure/v1-only, since
        callers key into it per room id the same way boost does.
        """
        if not self.use_v2:
            return {}
        try:
            return await self.client.async_get_room_decisions()
        except Healthbox3Error as err:
            _LOGGER.debug("Failed to fetch room decision data: %s", err)
            return {}

    async def _async_try_relocate(self) -> None:
        """Best-effort: if this entry's device is answering at a new IP
        (e.g. a DHCP lease renewal), find it via broadcast discovery and
        trigger a silent, invisible-to-the-user reconnect.

        Only attempted once per outage, not on every failed poll (every
        DEFAULT_SCAN_INTERVAL indefinitely) - the device may simply be
        offline for an unrelated reason, and there's no reason to keep
        broadcasting while that sorts itself out. Reset on the next
        successful poll.

        Triggers a real config flow (source integration_discovery) rather
        than updating the entry directly, so the same identity
        verification (a real HTTP call, not just trusting the broadcast
        reply) used everywhere else in this integration also gates this -
        see Healthbox3ConfigFlow.async_step_integration_discovery.
        """
        if self._relocate_attempted:
            return
        self._relocate_attempted = True

        try:
            devices = await async_discover_broadcast()
        except OSError:
            _LOGGER.debug("Relocate broadcast discovery failed", exc_info=True)
            return

        match = next(
            (d for d in devices if d.serial == self.config_entry.unique_id), None
        )
        if match is None or match.ip == self.config_entry.data[CONF_HOST]:
            return

        _LOGGER.info(
            "Healthbox 3 %s found at new address %s (was %s); reconnecting",
            self.config_entry.unique_id,
            match.ip,
            self.config_entry.data[CONF_HOST],
        )
        discovery_flow.async_create_flow(
            self.hass,
            DOMAIN,
            context={"source": SOURCE_INTEGRATION_DISCOVERY},
            data={CONF_HOST: match.ip},
        )

    async def _async_get_healthbox_data(self) -> HealthboxData:
        if not self.use_v2:
            return await self._async_get_v1_data()

        key_invalid = False
        try:
            data = await self.client.async_get_v2_data_current()
        except Healthbox3AuthenticationError:
            key_invalid = True
        except Healthbox3ConnectionError as err:
            await self._async_try_relocate()
            raise UpdateFailed(f"Error communicating with Healthbox 3: {err}") from err
        except Healthbox3InvalidResponseError as err:
            if not await self._async_api_key_still_valid():
                key_invalid = True
            else:
                raise UpdateFailed(
                    f"Error communicating with Healthbox 3: {err}"
                ) from err
        else:
            self._relocate_attempted = False
            return data

        assert key_invalid  # every branch above either returns or sets this
        self._async_handle_key_invalid()
        return await self._async_get_v1_data()

    async def _async_get_v1_data(self) -> HealthboxData:
        try:
            data = await self.client.async_get_v1_data_current()
        except Healthbox3ConnectionError as err:
            await self._async_try_relocate()
            raise UpdateFailed(f"Error communicating with Healthbox 3: {err}") from err
        except Healthbox3InvalidResponseError as err:
            raise UpdateFailed(f"Error communicating with Healthbox 3: {err}") from err
        self._relocate_attempted = False
        return data

    async def _async_api_key_still_valid(self) -> bool:
        """Disambiguate a v2 data/current parse failure from a revoked key.

        Neither Renson PDF documents what `data/current` actually returns
        once a previously-active key stops working, so on a v2 parse
        failure we fall back to the one endpoint with an unambiguous
        contract (`/v2/api/api_key/status`) to decide whether this is an
        auth problem or a transient/format problem.
        """
        try:
            status = await self.client.async_get_api_key_status()
        except Healthbox3Error:
            return True
        return status.is_valid

    def _async_handle_key_invalid(self) -> None:
        """Fall back to v1-only and request reauth, without failing this update.

        Renson-issued API keys carry a multi-year expiry that the device
        itself has no local awareness of (confirmed: `/v2/api/api_key/status`
        exposes no expiry field), so there's no way to warn ahead of time.
        When the key does eventually stop working - from expiry or
        revocation - v1 still works without one, so this degrades to
        v1-only functionality (same as if no key were ever configured)
        instead of failing every poll and taking every entity unavailable
        until the user reauthenticates.
        """
        _LOGGER.warning(
            "Healthbox 3 API key is no longer valid; falling back to v1-only "
            "functionality until reauthentication"
        )
        self.use_v2 = False
        self.config_entry.async_start_reauth(self.hass)

    async def _async_get_boost_data(
        self, healthbox: HealthboxData
    ) -> dict[int, BoostStatus]:
        """Fetch boost status for every room.

        By this point `data/current` already succeeded, so the device is
        known reachable; a failure fetching one room's boost status is
        treated as that room's boost entity going unavailable, not as a
        full update failure.
        """
        results = await asyncio.gather(
            *(self.client.async_get_boost(room.id) for room in healthbox.rooms),
            return_exceptions=True,
        )
        boost: dict[int, BoostStatus] = {}
        for room, result in zip(healthbox.rooms, results, strict=True):
            if isinstance(result, Healthbox3Error):
                _LOGGER.debug(
                    "Failed to fetch boost status for room %s: %s", room.id, result
                )
                continue
            if isinstance(result, BaseException):
                raise result
            boost[room.id] = result
            if room.id not in self.boost_params:
                # Seed once from the room's own device-reported defaults;
                # never overwritten afterwards so a user's own choice (or a
                # restored one) sticks across refreshes.
                self.boost_params[room.id] = BoostParams(
                    level=_clamp_level(result.default_level),
                    timeout=_clamp_timeout(result.default_timeout),
                )
        return boost
