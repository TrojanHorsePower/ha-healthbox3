"""Async API client for the Renson Healthbox 3 local API."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import logging
from typing import Any

import aiohttp

from .const import (
    API_KEY_STATE_VALID,
    API_V1_BOOST,
    API_V1_DATA_CURRENT,
    API_V1_DECISION,
    API_V2_API_KEY,
    API_V2_API_KEY_STATUS,
    API_V2_DATA_CURRENT,
    API_V2_DECISION_BREEZE,
    API_V2_DECISION_ROOM,
    API_V2_PROFILE_NAME,
    DISCOVERY_MESSAGE,
    DISCOVERY_PORT,
    DISCOVERY_TIMEOUT,
    PROFILES,
    SILENT_WEEKDAYS,
)

_LOGGER = logging.getLogger(__name__)

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)


class Healthbox3Error(Exception):
    """Base exception for Healthbox3 API errors."""


class Healthbox3ConnectionError(Healthbox3Error):
    """Raised when the device cannot be reached."""


class Healthbox3AuthenticationError(Healthbox3Error):
    """Raised when the API key was rejected."""


class Healthbox3InvalidResponseError(Healthbox3Error):
    """Raised when the device returned a response we can't parse."""


@dataclass
class Parameter:
    """A single named value/unit pair, as found in every "parameter" block."""

    value: bool | float | str | None
    unit: str = ""


@dataclass
class Actuator:
    """An actuator (e.g. an air valve) attached to a room."""

    basic_id: int
    name: str
    type: str
    parameters: dict[str, Parameter] = field(default_factory=dict)


@dataclass
class Sensor:
    """A sensor attached to a room, or the global air quality sensor.

    `parameters` can legitimately be empty (confirmed on real hardware for a
    CO2 sensor that hasn't reported yet) - that means "not available", not
    an error.
    """

    basic_id: int
    name: str
    type: str
    parameters: dict[str, Parameter] = field(default_factory=dict)

    @property
    def is_available(self) -> bool:
        """Return whether this sensor has reported any data."""
        return bool(self.parameters)


@dataclass
class Room:
    """A single room/zone."""

    id: int
    name: str
    type: str
    parameters: dict[str, Parameter] = field(default_factory=dict)
    actuators: list[Actuator] = field(default_factory=list)
    sensors: list[Sensor] = field(default_factory=list)
    profile_name: str | None = None  # only present via the v2 API


@dataclass
class HealthboxData:
    """Parsed result of a v1 or v2 `data/current` call."""

    device_type: str
    description: str
    serial: str
    warranty_number: str
    global_parameters: dict[str, Parameter] = field(default_factory=dict)
    rooms: list[Room] = field(default_factory=list)
    global_sensors: list[Sensor] = field(default_factory=list)


@dataclass
class BoostStatus:
    """State of a room's boost function.

    `default_level`/`default_timeout` are returned by real hardware but are
    not documented in the Renson API PDF.
    """

    enable: bool
    level: float
    timeout: int
    remaining: int
    default_level: float | None = None
    default_timeout: int | None = None


@dataclass
class ApiKeyStatus:
    """Result of a `/v2/api/api_key/status` call."""

    state: str
    disable_telemetry_data_allowed: bool
    local_sensor_data_allowed: bool

    @property
    def is_valid(self) -> bool:
        """Return whether privileged v2 access is currently active."""
        return self.state == API_KEY_STATE_VALID


@dataclass
class SilentSettings:
    """Silent (reduced-noise) schedule settings, from `/v1/decision`'s
    `silent` block.

    The real per-weekday arrays (`monday`..`sunday`) are each a pair of
    `{silent, time}` entries - a `silent: true` entry marking when the
    schedule starts, a `silent: false` entry marking when it stops. This
    client only supports a single shared start/stop pair applied
    uniformly across every day (matching how the Renson app itself
    presents it, not a genuinely per-day schedule), so only `monday`'s
    array is ever read; every other weekday is assumed - and always
    written - to match it exactly.
    """

    enable: bool
    reduction: float
    start_time: str  # "HH:MM:SS", the silent:true entry
    stop_time: str  # "HH:MM:SS", the silent:false entry


def _parse_silent(raw: dict[str, Any]) -> SilentSettings:
    schedule = {entry["silent"]: entry["time"] for entry in raw["monday"]}
    return SilentSettings(
        enable=raw["enable"],
        reduction=raw["reduction"],
        start_time=schedule[True],
        stop_time=schedule[False],
    )


@dataclass
class DeviceDecision:
    """Device-wide ventilation decision settings, from `/v1/decision`.

    The real response also has `room`, `breeze`, `profile`, `cdd_*`,
    `cooking_hood`, `fire_protect`, and `global_ventilation_level` keys -
    deliberately not parsed here. `room` in particular has a *different*,
    incompatible shape for CO2 demand data than the dedicated
    `/v2/decision/room` endpoint (confirmed on real hardware: same field
    ends up as `offset`+`coefficients` here vs `minimum`+`maximum` there) -
    `/v2/decision/room` is what the device's own web UI actually reads and
    writes, so that's the only source ever used for room-level decision
    data in this client. `breeze` is likewise available here too, but
    `/v2/decision/breeze` is used instead to avoid maintaining two parsing
    paths for the same setting.
    """

    program_enabled: bool
    global_minimum: float
    silent: SilentSettings


def _parse_decision(raw: dict[str, Any]) -> DeviceDecision:
    return DeviceDecision(
        program_enabled=raw["program"]["enable"],
        global_minimum=raw["minimum"],
        silent=_parse_silent(raw["silent"]),
    )


@dataclass
class BreezeSettings:
    """Breeze (temperature-triggered night cooling) settings, from
    `/v2/decision/breeze`.

    The real response also has `min_hold_time`/`ramp_time` (confirmed
    present, both times in seconds) - internal tuning parameters, not
    something a typical user would want to adjust, so deliberately not
    parsed or exposed as entities.
    """

    enable: bool
    average_temp: float


def _parse_breeze(raw: dict[str, Any]) -> BreezeSettings:
    return BreezeSettings(
        enable=raw["enable"],
        average_temp=raw["average_temp"],
    )


@dataclass
class RoomCO2Demand:
    """A room's static CO2 demand-control thresholds, from the
    `demand.CO2.static` block of `/v2/decision/room`.

    `enable` gates whether this room supports CO2-threshold configuration
    at all - confirmed on real hardware to vary per room and NOT be tied
    to room type (e.g. Kitchen), reversing what the reference web UI's own
    JS appears to gate on. `coefficients` is confirmed present but
    deliberately not parsed/exposed (internal tuning). The dynamic demand
    block, and the other demand types (DVOC/VOC/absolute_humidity/
    relative_humidity), are likewise out of scope for this client.
    """

    enable: bool
    minimum: float
    maximum: float


@dataclass
class RoomDecision:
    """A single room's entry in `/v2/decision/room`.

    The real per-room object also has minimum/nominal/offset/profile (an
    index, not the string-based profile_name this client already writes
    via /v2/api/data/current/room/{id}/profile_name) - deliberately not
    parsed here.
    """

    co2: RoomCO2Demand


def _parse_room_decisions(raw: dict[str, Any]) -> dict[int, RoomDecision]:
    result: dict[int, RoomDecision] = {}
    for room_id, r in raw.items():
        static = r["demand"]["CO2"]["static"]
        result[int(room_id)] = RoomDecision(
            co2=RoomCO2Demand(
                enable=static["enable"],
                minimum=static["minimum"],
                maximum=static["maximum"],
            )
        )
    return result


@dataclass
class DiscoveryInfo:
    """Parsed UDP discovery response.

    `subtype` is returned by real hardware but not documented in the PDF.
    `local_api_version` is documented but hasn't been observed on real
    hardware.
    """

    device: str
    firmware_version: str
    ip: str
    mac: str
    serial: str
    warranty_number: str
    scope: str
    description: str
    subtype: str = ""
    local_api_version: str | None = None


def _basic_id(raw: dict[str, Any]) -> int:
    """Return the basic id, normalizing v1's "basic id" and v2's "basic_id"."""
    if "basic_id" in raw:
        return raw["basic_id"]
    return raw["basic id"]


def _parse_parameters(raw: dict[str, Any] | None) -> dict[str, Parameter]:
    if not raw:
        return {}
    return {
        name: Parameter(value=p.get("value"), unit=p.get("unit", ""))
        for name, p in raw.items()
    }


def _parse_actuators(raw: list[dict[str, Any]] | None) -> list[Actuator]:
    return [
        Actuator(
            basic_id=_basic_id(a),
            name=a["name"],
            type=a["type"],
            parameters=_parse_parameters(a.get("parameter")),
        )
        for a in raw or []
    ]


def _parse_sensors(raw: list[dict[str, Any]] | None) -> list[Sensor]:
    return [
        Sensor(
            basic_id=_basic_id(s),
            name=s["name"],
            type=s["type"],
            parameters=_parse_parameters(s.get("parameter")),
        )
        for s in raw or []
    ]


def _parse_v1_data(raw: dict[str, Any]) -> HealthboxData:
    rooms = [
        Room(
            id=r["id"],
            name=r["name"],
            type=r["type"],
            parameters=_parse_parameters(r.get("parameter")),
            actuators=_parse_actuators(r.get("actuator")),
        )
        for r in raw.get("room", [])
    ]
    return HealthboxData(
        device_type=raw["device_type"],
        description=raw["description"],
        serial=raw["serial"],
        warranty_number=raw["warranty_number"],
        global_parameters=_parse_parameters(raw.get("global", {}).get("parameter")),
        rooms=rooms,
        global_sensors=_parse_sensors(raw.get("sensor")),
    )


def _parse_v2_data(raw: dict[str, Any]) -> HealthboxData:
    rooms = [
        Room(
            id=int(room_id),
            name=r["name"],
            type=r["type"],
            parameters=_parse_parameters(r.get("parameter")),
            actuators=_parse_actuators(r.get("actuator")),
            sensors=_parse_sensors(r.get("sensor")),
            profile_name=r.get("profile_name"),
        )
        for room_id, r in raw.get("room", {}).items()
    ]
    return HealthboxData(
        device_type=raw["device_type"],
        description=raw["description"],
        serial=raw["serial"],
        warranty_number=raw["warranty_number"],
        global_parameters=_parse_parameters(raw.get("global", {}).get("parameter")),
        rooms=rooms,
        global_sensors=_parse_sensors(raw.get("sensor")),
    )


def _parse_boost(raw: dict[str, Any]) -> BoostStatus:
    return BoostStatus(
        enable=raw["enable"],
        level=raw["level"],
        timeout=raw["timeout"],
        remaining=raw["remaining"],
        default_level=raw.get("default_level"),
        default_timeout=raw.get("default_timeout"),
    )


def _parse_discovery(raw: dict[str, Any]) -> DiscoveryInfo:
    return DiscoveryInfo(
        device=raw["Device"],
        firmware_version=raw["Firmwareversion"],
        ip=raw["IP"],
        mac=raw["MAC"],
        serial=raw["serial"],
        warranty_number=raw["warranty_number"],
        scope=raw["scope"],
        description=raw["Description"],
        subtype=raw.get("subtype", ""),
        local_api_version=raw.get("local API version"),
    )


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    """Datagram protocol that resolves a future with the first response."""

    def __init__(self, response_future: asyncio.Future[bytes]) -> None:
        self._response_future = response_future

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if not self._response_future.done():
            self._response_future.set_result(data)

    def error_received(self, exc: Exception) -> None:
        if not self._response_future.done():
            self._response_future.set_exception(exc)


async def _async_udp_discover(host: str, timeout: float) -> dict[str, Any]:
    """Send a unicast discovery request to `host` and return the decoded JSON.

    Broadcast to 255.255.255.255 is documented but was unreliable on real
    networks (AP client isolation / IGMP snooping / VLANs); unicast directly
    to a known IP is confirmed to work.
    """
    loop = asyncio.get_running_loop()
    response_future: asyncio.Future[bytes] = loop.create_future()

    transport, _ = await loop.create_datagram_endpoint(
        lambda: _DiscoveryProtocol(response_future),
        remote_addr=(host, DISCOVERY_PORT),
    )
    try:
        transport.sendto(DISCOVERY_MESSAGE)
        try:
            data = await asyncio.wait_for(response_future, timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError) as err:
            raise Healthbox3ConnectionError(
                f"No discovery response from {host}"
            ) from err
        except OSError as err:
            raise Healthbox3ConnectionError(
                f"Discovery request to {host} failed: {err}"
            ) from err
    finally:
        transport.close()

    try:
        return json.loads(data.decode())
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        raise Healthbox3InvalidResponseError(
            "Invalid discovery JSON response"
        ) from err


class _BroadcastDiscoveryProtocol(asyncio.DatagramProtocol):
    """Datagram protocol that collects every response received during a
    fixed listening window.

    Unlike `_DiscoveryProtocol` (a single future resolved by the first
    reply from one known host), a broadcast can draw replies from multiple
    devices - or none at all - so there's no single "the" response to
    resolve early on; the caller just lets the window run out.
    """

    def __init__(self) -> None:
        self.responses: list[bytes] = []

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.responses.append(data)

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("Broadcast discovery socket error: %s", exc)


async def _async_udp_discover_broadcast(timeout: float) -> list[dict[str, Any]]:
    """Broadcast a discovery request and collect all responses received
    within `timeout` seconds.

    An empty result is a normal outcome, not an error - broadcast delivery
    is confirmed unreliable on some networks (AP client isolation, IGMP
    snooping, VLAN segmentation), so "nobody answered" must be as
    unsurprising to callers as "one or more devices answered".
    """
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        _BroadcastDiscoveryProtocol,
        local_addr=("0.0.0.0", 0),  # unbound source port; broadcast needs no specific interface
        allow_broadcast=True,
    )
    try:
        transport.sendto(DISCOVERY_MESSAGE, ("255.255.255.255", DISCOVERY_PORT))
        await asyncio.sleep(timeout)
    finally:
        transport.close()

    results = []
    for data in protocol.responses:
        try:
            results.append(json.loads(data.decode()))
        except (json.JSONDecodeError, UnicodeDecodeError):
            _LOGGER.debug("Ignoring malformed broadcast discovery response: %r", data)
    return results


async def async_discover_broadcast(
    timeout: float = DISCOVERY_TIMEOUT,
) -> list[DiscoveryInfo]:
    """Broadcast-discover Healthbox 3 devices on the local network.

    Returns an empty list - not an error - if no devices respond. Callers
    (the config flow) must fall back to manual entry rather than treating
    an empty result as a failure.
    """
    raw_responses = await _async_udp_discover_broadcast(timeout)
    devices: dict[str, DiscoveryInfo] = {}
    for raw in raw_responses:
        try:
            info = _parse_discovery(raw)
        except (KeyError, TypeError):
            _LOGGER.debug("Ignoring discovery response with unexpected shape: %r", raw)
            continue
        devices[info.serial] = info  # de-dupe repeat replies from the same device
    return list(devices.values())


class Healthbox3ApiClient:
    """Client for the Healthbox 3 local v1/v2 HTTP API."""

    def __init__(self, host: str, session: aiohttp.ClientSession) -> None:
        """Initialize the client. `session` should be HA's shared client session."""
        self._host = host
        self._session = session
        self._base_url = f"http://{host}"

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> Any:
        url = f"{self._base_url}{path}"
        try:
            async with self._session.request(
                method, url, timeout=_REQUEST_TIMEOUT, **kwargs
            ) as resp:
                if resp.status in (401, 403):
                    raise Healthbox3AuthenticationError(
                        f"{method} {path} returned HTTP {resp.status}"
                    )
                if resp.status != 200:
                    raise Healthbox3InvalidResponseError(
                        f"{method} {path} returned HTTP {resp.status}"
                    )
                text = await resp.text()
        except TimeoutError as err:
            raise Healthbox3ConnectionError(
                f"Timeout connecting to {self._host}"
            ) from err
        except aiohttp.ClientError as err:
            raise Healthbox3ConnectionError(
                f"Error connecting to {self._host}: {err}"
            ) from err

        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as err:
            raise Healthbox3InvalidResponseError(
                f"Invalid JSON response from {method} {path}"
            ) from err

    async def async_get_v1_data_current(self) -> HealthboxData:
        """Fetch and parse `/v1/api/data/current`."""
        raw = await self._request("GET", API_V1_DATA_CURRENT)
        try:
            return _parse_v1_data(raw)
        except (KeyError, TypeError, AttributeError) as err:
            raise Healthbox3InvalidResponseError(
                "Unexpected v1 data/current response shape"
            ) from err

    async def async_get_v2_data_current(self) -> HealthboxData:
        """Fetch and parse `/v2/api/data/current`."""
        raw = await self._request("GET", API_V2_DATA_CURRENT)
        try:
            return _parse_v2_data(raw)
        except (KeyError, TypeError, AttributeError) as err:
            raise Healthbox3InvalidResponseError(
                "Unexpected v2 data/current response shape"
            ) from err

    async def async_get_boost(self, room_id: int) -> BoostStatus:
        """Fetch the boost status for a room."""
        raw = await self._request("GET", API_V1_BOOST.format(room_id=room_id))
        try:
            return _parse_boost(raw)
        except (KeyError, TypeError) as err:
            raise Healthbox3InvalidResponseError(
                "Unexpected boost response shape"
            ) from err

    async def async_set_boost(
        self, room_id: int, *, enable: bool, level: float, timeout: int
    ) -> BoostStatus:
        """Set the boost status for a room."""
        payload = {"enable": enable, "level": level, "timeout": timeout}
        raw = await self._request(
            "PUT", API_V1_BOOST.format(room_id=room_id), json=payload
        )
        try:
            return _parse_boost(raw)
        except (KeyError, TypeError) as err:
            raise Healthbox3InvalidResponseError(
                "Unexpected boost response shape"
            ) from err

    async def async_activate_api_key(self, api_key: str) -> None:
        """Upload and activate an API key for privileged v2 access."""
        await self._request(
            "POST",
            API_V2_API_KEY,
            data=json.dumps(api_key),
            headers={"Content-Type": "application/json"},
        )

    async def async_get_api_key_status(self) -> ApiKeyStatus:
        """Check whether privileged v2 access is currently active."""
        raw = await self._request("GET", API_V2_API_KEY_STATUS)
        try:
            options = raw["options"]
            return ApiKeyStatus(
                state=raw["state"],
                disable_telemetry_data_allowed=options[
                    "disable_telemetry_data_allowed"
                ],
                local_sensor_data_allowed=options["local_sensor_data_allowed"],
            )
        except (KeyError, TypeError) as err:
            raise Healthbox3InvalidResponseError(
                "Unexpected api_key/status response shape"
            ) from err

    async def async_set_profile(self, room_id: int, profile_name: str) -> None:
        """Set a room's ventilation profile. Requires an active API key."""
        if profile_name not in PROFILES:
            raise ValueError(f"Invalid profile_name: {profile_name}")
        await self._request(
            "PUT",
            API_V2_PROFILE_NAME.format(room_id=room_id),
            data=json.dumps(profile_name),
            headers={"Content-Type": "application/json"},
        )

    async def async_discover(
        self, timeout: float = DISCOVERY_TIMEOUT
    ) -> DiscoveryInfo:
        """Query this device's discovery endpoint (unicast)."""
        raw = await _async_udp_discover(self._host, timeout=timeout)
        try:
            return _parse_discovery(raw)
        except (KeyError, TypeError) as err:
            raise Healthbox3InvalidResponseError(
                "Unexpected discovery response shape"
            ) from err

    async def async_get_decision(self) -> DeviceDecision:
        """Fetch and parse `/v1/decision`. Requires an active API key."""
        raw = await self._request("GET", API_V1_DECISION)
        try:
            return _parse_decision(raw)
        except (KeyError, TypeError) as err:
            raise Healthbox3InvalidResponseError(
                "Unexpected decision response shape"
            ) from err

    async def async_set_demand_control(self, enable: bool) -> None:
        """Enable/disable demand-controlled ventilation. Requires an active API key."""
        await self._request(
            "PUT", API_V1_DECISION, json={"program": {"enable": enable}}
        )

    async def async_set_global_minimum(self, value: float) -> None:
        """Set the device-wide minimum ventilation level. Requires an active API key."""
        await self._request("PUT", API_V1_DECISION, json={"minimum": value})

    async def async_get_breeze(self) -> BreezeSettings:
        """Fetch and parse `/v2/decision/breeze`. Requires an active API key."""
        raw = await self._request("GET", API_V2_DECISION_BREEZE)
        try:
            return _parse_breeze(raw)
        except (KeyError, TypeError) as err:
            raise Healthbox3InvalidResponseError(
                "Unexpected breeze response shape"
            ) from err

    async def async_set_breeze_enable(self, enable: bool) -> None:
        """Enable/disable Breeze. Requires an active API key."""
        await self._request(
            "PUT", API_V2_DECISION_BREEZE, json={"enable": enable}
        )

    async def async_set_breeze_temp(self, value: float) -> None:
        """Set Breeze's trigger average outdoor temperature. Requires an active API key."""
        await self._request(
            "PUT", API_V2_DECISION_BREEZE, json={"average_temp": value}
        )

    async def async_get_room_decisions(self) -> dict[int, RoomDecision]:
        """Fetch and parse `/v2/decision/room`. Requires an active API key."""
        raw = await self._request("GET", API_V2_DECISION_ROOM)
        try:
            return _parse_room_decisions(raw)
        except (KeyError, TypeError) as err:
            raise Healthbox3InvalidResponseError(
                "Unexpected room decision response shape"
            ) from err

    async def async_set_room_co2_threshold(
        self, room_id: int, *, minimum: float, maximum: float
    ) -> None:
        """Set a room's CO2 static demand thresholds. Requires an active API key."""
        await self._request(
            "PUT",
            API_V2_DECISION_ROOM,
            json={
                str(room_id): {
                    "demand": {"CO2": {"static": {"minimum": minimum, "maximum": maximum}}}
                }
            },
        )

    async def async_set_silent_enable(self, enable: bool) -> None:
        """Enable/disable the silent schedule. Requires an active API key."""
        await self._request(
            "PUT", API_V1_DECISION, json={"silent": {"enable": enable}}
        )

    async def async_set_silent_reduction(self, value: float) -> None:
        """Set the silent schedule's ventilation reduction. Requires an active API key."""
        await self._request(
            "PUT", API_V1_DECISION, json={"silent": {"reduction": value}}
        )

    async def async_set_silent_schedule(self, *, start_time: str, stop_time: str) -> None:
        """Set the silent schedule's start/stop times ("HH:MM:SS"), applied
        uniformly to every weekday - the single shared pair this client
        supports (see SilentSettings' docstring). Requires an active API key.
        """
        day_schedule = [
            {"silent": True, "time": start_time},
            {"silent": False, "time": stop_time},
        ]
        payload = {"silent": {day: day_schedule for day in SILENT_WEEKDAYS}}
        await self._request("PUT", API_V1_DECISION, json=payload)
