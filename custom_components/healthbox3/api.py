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
    API_V2_API_KEY,
    API_V2_API_KEY_STATUS,
    API_V2_DATA_CURRENT,
    API_V2_PROFILE_NAME,
    DISCOVERY_MESSAGE,
    DISCOVERY_PORT,
    DISCOVERY_TIMEOUT,
    PROFILES,
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
