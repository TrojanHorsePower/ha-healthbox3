"""DataUpdateCoordinator for the Renson Healthbox 3 integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import override

from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY, ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, discovery_flow, issue_registry as ir
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, format_mac
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    BoostStatus,
    BreezeSettings,
    DeviceDecision,
    DeviceError,
    GlobalInfo,
    Healthbox3ApiClient,
    Healthbox3AuthenticationError,
    Healthbox3ConnectionError,
    Healthbox3Error,
    Healthbox3InvalidResponseError,
    HealthboxData,
    RoomDecision,
    WifiStatus,
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
    WIFI_STATUS_CACHE_TTL,
)

_LOGGER = logging.getLogger(__name__)

# Bound the whole poll when a device disappears partway through serialized reads.
_UPDATE_TIMEOUT = 60.0

# Confirmed real values for DeviceError.severity - anything else falls
# back to WARNING rather than raising, since a defensive default here is
# safer than crashing a coordinator update over a device sending a
# severity value nobody's seen it send before.
_ERROR_SEVERITY: dict[str, ir.IssueSeverity] = {
    "critical": ir.IssueSeverity.CRITICAL,
    "warning": ir.IssueSeverity.WARNING,
}


def unit_connections(global_info: GlobalInfo) -> set[tuple[str, str]]:
    """Return the unit's network identity (its MAC), if the device reported one."""
    if global_info.mac is None:
        return set()
    return {(CONNECTION_NETWORK_MAC, format_mac(global_info.mac))}


def unit_configuration_url(global_info: GlobalInfo) -> str | None:
    """Return the URL of the device's own web UI, if the device reported an IP."""
    return f"http://{global_info.ip}" if global_info.ip is not None else None


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
    # When this poll completed. Remaining-time readings are relative to it.
    polled_at: datetime | None = None
    decision: DeviceDecision | None = None
    breeze: BreezeSettings | None = None
    room_decisions: dict[int, RoomDecision] = field(default_factory=dict)
    firmware_version: str | None = None
    # Unit identity and network position, from /renson_core/v2/global.
    global_info: GlobalInfo | None = None
    # Wi-Fi client status, only read for a Wi-Fi unit and cached between polls.
    wifi: WifiStatus | None = None
    errors: list[DeviceError] = field(default_factory=list)


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
        self._tracked_error_issue_ids: set[str] = set()
        # Registry id of the unit device, which room devices link to via
        # `via_device_id`. Set by async_setup_entry before platforms load.
        self.unit_device_id: str | None = None
        self._wifi_cache: WifiStatus | None = None
        self._wifi_cached_at: datetime | None = None

    @override
    async def _async_update_data(self) -> Healthbox3Data:
        async with asyncio.timeout(_UPDATE_TIMEOUT):
            healthbox = await self._async_get_healthbox_data()
            boost = await self._async_get_boost_data(healthbox)
            decision = await self._async_get_decision_data()
            breeze = await self._async_get_breeze_data()
            room_decisions = await self._async_get_room_decisions_data()
            global_info = await self._async_get_global_info_data()
            wifi = await self._async_get_wifi_data(global_info)
            errors = await self._async_get_errors_data()
            self._async_reconcile_error_issues(errors)
            data = Healthbox3Data(
                polled_at=dt_util.utcnow(),
                healthbox=healthbox,
                boost=boost,
                decision=decision,
                breeze=breeze,
                room_decisions=room_decisions,
                firmware_version=global_info.firmware_version if global_info else None,
                global_info=global_info,
                wifi=wifi,
                errors=errors,
            )
            self._async_sync_unit_device(global_info)
            return data

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

    async def _async_get_global_info_data(self) -> GlobalInfo | None:
        """Fetch `/renson_core/v2/global` once per poll - same gating and
        tolerance as decision/breeze/room_decisions. One request supplies the
        firmware version, MAC, IP and interface type.
        """
        if not self.use_v2:
            return None
        try:
            return await self.client.async_get_global_info()
        except Healthbox3Error as err:
            _LOGGER.debug("Failed to fetch global info: %s", err)
            return None

    async def _async_get_wifi_data(self, global_info: GlobalInfo | None) -> WifiStatus | None:
        """Fetch Wi-Fi status for a Wi-Fi unit, at most once per cache TTL.

        A failed read is cached too, so a struggling device is not asked again
        on every poll; the internet sensor reads unknown until the next try.
        """
        if not self.use_v2 or global_info is None or global_info.interface_type != "WIFI":
            return None
        now = dt_util.utcnow()
        if self._wifi_cached_at is not None and now - self._wifi_cached_at < WIFI_STATUS_CACHE_TTL:
            return self._wifi_cache
        try:
            self._wifi_cache = await self.client.async_get_wifi_status()
        except Healthbox3Error as err:
            _LOGGER.debug("Failed to fetch Wi-Fi status: %s", err)
            self._wifi_cache = None
        self._wifi_cached_at = now
        return self._wifi_cache

    def _async_sync_unit_device(self, global_info: GlobalInfo | None) -> None:
        """Keep the unit device's MAC and address current with the device.

        The device's IP can change when the router hands it a new lease, and
        the device entry should follow it rather than keep the value from
        first setup.
        """
        if self.unit_device_id is None or global_info is None:
            return
        device_registry = dr.async_get(self.hass)
        device = device_registry.async_get(self.unit_device_id)
        if not isinstance(device, dr.DeviceEntry):
            return
        connections = unit_connections(global_info)
        configuration_url = unit_configuration_url(global_info)
        if (
            device.connections != connections
            or device.configuration_url != configuration_url
        ):
            device_registry.async_update_device(
                self.unit_device_id,
                new_connections=connections,
                configuration_url=configuration_url,
            )

    async def _async_get_errors_data(self) -> list[DeviceError]:
        """Fetch `/v1/error` - same gating/tolerance as room_decisions (a
        list, so `[]` not `None` on failure/v1-only).
        """
        if not self.use_v2:
            return []
        try:
            return await self.client.async_get_errors()
        except Healthbox3Error as err:
            _LOGGER.debug("Failed to fetch device errors: %s", err)
            return []

    def _async_reconcile_error_issues(self, errors: list[DeviceError]) -> None:
        """Create a repair issue for each currently-reported device error,
        and delete any previously-tracked issue whose error is no longer
        present - self-healing, no user action required to dismiss one
        that's resolved itself.

        Deliberately `is_fixable=False`: DELETE /v1/error/clear (see
        API_V1_ERROR's comment in const.py) is a bulk "clear everything"
        action with no per-error variant, so wiring a "Fix" button to it
        would risk dismissing unrelated errors alongside the one the user
        meant to act on. Clearing stays a manual device/Renson-app
        action; these issues exist purely to inform.

        Keyed on `association_id` - its name strongly implies it's the
        device's own per-fault correlation id, but this has never been
        confirmed against a real populated response (see DeviceError's
        docstring - /v1/error has only ever been observed empty). If that
        assumption turns out wrong (e.g. two distinct faults somehow
        share one association_id), the practical effect is at worst
        under-reporting - one visible issue instead of two - not
        anything dangerous.
        """
        current_issue_ids: set[str] = set()
        for error in errors:
            issue_id = f"device_error_{error.association_id}"
            current_issue_ids.add(issue_id)
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=_ERROR_SEVERITY.get(error.severity, ir.IssueSeverity.WARNING),
                translation_key="device_error",
                translation_placeholders={
                    "code": error.code,
                    "description": error.description,
                    "time": error.time,
                    "severity": error.severity,
                    "category": error.category,
                },
            )

        for stale_issue_id in self._tracked_error_issue_ids - current_issue_ids:
            ir.async_delete_issue(self.hass, DOMAIN, stale_issue_id)

        self._tracked_error_issue_ids = current_issue_ids

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
