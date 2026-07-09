"""Tests for the Healthbox3 API client, using real device fixture JSON."""

from __future__ import annotations

import asyncio
import json

import pytest

from custom_components.healthbox3 import api as api_mod
from custom_components.healthbox3.const import SENSOR_TYPE_CO2, SENSOR_TYPE_TEMPERATURE


class _FakeResponse:
    def __init__(self, status: int, body: str = "") -> None:
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body


class _FakeRequestCM:
    """Mimics aiohttp's `async with session.request(...) as resp`."""

    def __init__(self, outcome: _FakeResponse | BaseException) -> None:
        self._outcome = outcome

    async def __aenter__(self):
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return self._outcome

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeSession:
    def __init__(self, outcomes: list[_FakeResponse | BaseException]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        return _FakeRequestCM(self._outcomes.pop(0))


async def test_get_v1_data_current_parses_real_fixture(v1_data_raw):
    session = _FakeSession([_FakeResponse(200, json.dumps(v1_data_raw))])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    data = await client.async_get_v1_data_current()

    assert len(data.rooms) == 7
    assert data.rooms[0].sensors == []  # v1 has no per-room sensors
    assert len(data.global_sensors) == 1
    assert data.global_sensors[0].basic_id == 0  # normalized from v1's "basic id"


async def test_get_v2_data_current_marks_empty_co2_unavailable(v2_data_raw):
    session = _FakeSession([_FakeResponse(200, json.dumps(v2_data_raw))])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    data = await client.async_get_v2_data_current()

    room1 = next(r for r in data.rooms if r.id == 1)
    co2 = next(s for s in room1.sensors if s.type == SENSOR_TYPE_CO2)
    assert co2.is_available is False
    temp = next(s for s in room1.sensors if s.type == SENSOR_TYPE_TEMPERATURE)
    assert temp.is_available is True
    assert room1.profile_name == "health"


async def test_get_boost_includes_undocumented_defaults(boost_raw):
    session = _FakeSession([_FakeResponse(200, json.dumps(boost_raw))])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    boost = await client.async_get_boost(1)

    assert boost.default_level == 100.0
    assert boost.default_timeout == 900


async def test_set_boost_sends_expected_payload(boost_raw):
    session = _FakeSession([_FakeResponse(200, json.dumps(boost_raw))])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    await client.async_set_boost(1, enable=True, level=175, timeout=900)

    method, url, kwargs = session.calls[0]
    assert method == "PUT"
    assert url.endswith("/v1/api/boost/1")
    assert kwargs["json"] == {"enable": True, "level": 175, "timeout": 900}


async def test_activate_and_check_api_key():
    session = _FakeSession(
        [
            _FakeResponse(200, ""),
            _FakeResponse(
                200,
                json.dumps(
                    {
                        "options": {
                            "disable_telemetry_data_allowed": True,
                            "local_sensor_data_allowed": True,
                        },
                        "state": "valid",
                    }
                ),
            ),
        ]
    )
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    await client.async_activate_api_key("some-key")
    status = await client.async_get_api_key_status()

    assert status.is_valid is True


async def test_set_profile_rejects_unknown_profile():
    client = api_mod.Healthbox3ApiClient("192.0.2.1", _FakeSession([]))

    with pytest.raises(ValueError):
        await client.async_set_profile(1, "turbo")


def test_parse_decision_ignores_unread_keys(decision_raw):
    """Confirms DeviceDecision only reads program.enable/minimum/
    global_ventilation_level/silent - the fixture has no room/breeze/
    profile/fire_protect/etc. keys at all (see decision_raw's docstring),
    so this also implicitly confirms those stay unparsed.
    """
    decision = api_mod._parse_decision(decision_raw)

    assert decision.program_enabled is False
    assert decision.global_minimum == 20.0
    assert decision.global_ventilation_level == 45.0
    assert decision.silent.enable is False
    assert decision.silent.reduction == 5.0
    assert decision.silent.start_time == "22:00:00"
    assert decision.silent.stop_time == "08:00:00"


async def test_get_decision_parses_real_shape(decision_raw):
    session = _FakeSession([_FakeResponse(200, json.dumps(decision_raw))])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    decision = await client.async_get_decision()

    assert decision.program_enabled is False
    assert decision.global_minimum == 20.0
    assert decision.global_ventilation_level == 45.0
    assert decision.silent.enable is False


@pytest.mark.parametrize("enable", [True, False])
async def test_set_demand_control_sends_expected_payload(enable):
    session = _FakeSession([_FakeResponse(200, "")])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    await client.async_set_demand_control(enable)

    method, url, kwargs = session.calls[0]
    assert method == "PUT"
    assert url.endswith("/v1/decision")
    assert kwargs["json"] == {"program": {"enable": enable}}


async def test_set_global_minimum_sends_expected_payload():
    session = _FakeSession([_FakeResponse(200, "")])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    await client.async_set_global_minimum(15.0)

    method, url, kwargs = session.calls[0]
    assert method == "PUT"
    assert url.endswith("/v1/decision")
    assert kwargs["json"] == {"minimum": 15.0}


def test_parse_silent_reads_start_stop_from_monday(decision_raw):
    """The silent:true entry is the start time, silent:false is the stop
    time - every weekday in the fixture is identical, so this only proves
    monday specifically is what gets read (not some other day).
    """
    silent = api_mod._parse_silent(decision_raw["silent"])

    assert silent.enable is False
    assert silent.reduction == 5.0
    assert silent.start_time == "22:00:00"
    assert silent.stop_time == "08:00:00"


@pytest.mark.parametrize("enable", [True, False])
async def test_set_silent_enable_sends_expected_payload(enable):
    session = _FakeSession([_FakeResponse(200, "")])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    await client.async_set_silent_enable(enable)

    method, url, kwargs = session.calls[0]
    assert method == "PUT"
    assert url.endswith("/v1/decision")
    assert kwargs["json"] == {"silent": {"enable": enable}}


async def test_set_silent_reduction_sends_expected_payload():
    session = _FakeSession([_FakeResponse(200, "")])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    await client.async_set_silent_reduction(10.0)

    method, url, kwargs = session.calls[0]
    assert method == "PUT"
    assert url.endswith("/v1/decision")
    assert kwargs["json"] == {"silent": {"reduction": 10.0}}


async def test_set_silent_schedule_writes_every_weekday_uniformly():
    session = _FakeSession([_FakeResponse(200, "")])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    await client.async_set_silent_schedule(start_time="21:00:00", stop_time="07:00:00")

    method, url, kwargs = session.calls[0]
    assert method == "PUT"
    assert url.endswith("/v1/decision")
    expected_day_schedule = [
        {"silent": True, "time": "21:00:00"},
        {"silent": False, "time": "07:00:00"},
    ]
    assert kwargs["json"] == {
        "silent": {day: expected_day_schedule for day in api_mod.SILENT_WEEKDAYS}
    }


def test_parse_breeze(breeze_raw):
    breeze = api_mod._parse_breeze(breeze_raw)

    assert breeze.enable is True
    assert breeze.average_temp == 30.0


async def test_get_breeze_parses_real_shape(breeze_raw):
    session = _FakeSession([_FakeResponse(200, json.dumps(breeze_raw))])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    breeze = await client.async_get_breeze()

    assert breeze.enable is True
    assert breeze.average_temp == 30.0


@pytest.mark.parametrize("enable", [True, False])
async def test_set_breeze_enable_sends_expected_payload(enable):
    session = _FakeSession([_FakeResponse(200, "")])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    await client.async_set_breeze_enable(enable)

    method, url, kwargs = session.calls[0]
    assert method == "PUT"
    assert url.endswith("/v2/decision/breeze")
    assert kwargs["json"] == {"enable": enable}


async def test_set_breeze_temp_sends_expected_payload():
    session = _FakeSession([_FakeResponse(200, "")])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    await client.async_set_breeze_temp(25.0)

    method, url, kwargs = session.calls[0]
    assert method == "PUT"
    assert url.endswith("/v2/decision/breeze")
    assert kwargs["json"] == {"average_temp": 25.0}


def test_parse_room_decisions_reads_co2_static_only(room_decisions_raw):
    """Confirms only demand.CO2.static is read - room "1"/"2" differ only
    in their `enable` flag, matching the real-hardware finding that this
    varies per room and isn't tied to room type.
    """
    decisions = api_mod._parse_room_decisions(room_decisions_raw)

    assert decisions[1].co2.enable is True
    assert decisions[1].co2.minimum == 650.0
    assert decisions[1].co2.maximum == 800.0
    assert decisions[2].co2.enable is False


async def test_get_room_decisions_parses_real_shape(room_decisions_raw):
    session = _FakeSession([_FakeResponse(200, json.dumps(room_decisions_raw))])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    decisions = await client.async_get_room_decisions()

    assert decisions[1].co2.enable is True
    assert decisions[2].co2.enable is False


async def test_set_room_co2_threshold_sends_expected_payload():
    session = _FakeSession([_FakeResponse(200, "")])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    await client.async_set_room_co2_threshold(1, minimum=700.0, maximum=850.0)

    method, url, kwargs = session.calls[0]
    assert method == "PUT"
    assert url.endswith("/v2/decision/room")
    assert kwargs["json"] == {
        "1": {"demand": {"CO2": {"static": {"minimum": 700.0, "maximum": 850.0}}}}
    }


async def test_get_firmware_version_parses_real_shape(renson_core_global_raw):
    session = _FakeSession([_FakeResponse(200, json.dumps(renson_core_global_raw))])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    version = await client.async_get_firmware_version()

    assert version == "2.6.9"


async def test_get_firmware_version_rejects_unexpected_shape():
    session = _FakeSession([_FakeResponse(200, json.dumps({"unexpected": "shape"}))])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    with pytest.raises(api_mod.Healthbox3InvalidResponseError):
        await client.async_get_firmware_version()


async def test_get_errors_parses_real_shape(errors_raw):
    session = _FakeSession([_FakeResponse(200, json.dumps(errors_raw))])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    errors = await client.async_get_errors()

    assert errors == [
        api_mod.DeviceError(
            code="E042",
            time="2026-01-15T08:30:00Z",
            description="Sensor fault in room 3",
            association_id="abc123",
            severity="critical",
        ),
        api_mod.DeviceError(
            code="W007",
            time="2026-01-14T22:10:00Z",
            description="Filter replacement recommended",
            association_id="def456",
            severity="warning",
        ),
    ]


async def test_get_errors_handles_empty_list():
    session = _FakeSession([_FakeResponse(200, json.dumps([]))])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    assert await client.async_get_errors() == []


async def test_get_errors_rejects_unexpected_shape():
    session = _FakeSession([_FakeResponse(200, json.dumps([{"unexpected": "shape"}]))])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    with pytest.raises(api_mod.Healthbox3InvalidResponseError):
        await client.async_get_errors()


@pytest.mark.parametrize("status", [401, 403])
async def test_auth_error_statuses_raise_authentication_error(status):
    session = _FakeSession([_FakeResponse(status)])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    with pytest.raises(api_mod.Healthbox3AuthenticationError):
        await client.async_get_v2_data_current()


async def test_bare_500_empty_body_raises_invalid_response_error():
    """Confirmed on real hardware: an unknown room id returns a bare 500, no body."""
    session = _FakeSession([_FakeResponse(500, "")])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    with pytest.raises(api_mod.Healthbox3InvalidResponseError):
        await client.async_get_boost(99)


async def test_connection_error_wrapped():
    session = _FakeSession([TimeoutError()])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    with pytest.raises(api_mod.Healthbox3ConnectionError):
        await client.async_get_v1_data_current()


async def test_malformed_json_raises_invalid_response_error():
    session = _FakeSession([_FakeResponse(200, "{not json")])
    client = api_mod.Healthbox3ApiClient("192.0.2.1", session)

    with pytest.raises(api_mod.Healthbox3InvalidResponseError):
        await client.async_get_v1_data_current()


async def test_parse_discovery_handles_undocumented_subtype_field(discovery_raw):
    info = api_mod._parse_discovery(discovery_raw)

    assert info.device == "HEALTHBOX3"
    assert info.subtype == ""
    assert info.local_api_version is None  # documented field, absent on real hardware


async def test_async_discover_wires_through_udp_helper(monkeypatch, discovery_raw):
    async def _fake_udp_discover(host, timeout):
        assert host == "192.0.2.1"
        return discovery_raw

    monkeypatch.setattr(api_mod, "_async_udp_discover", _fake_udp_discover)
    client = api_mod.Healthbox3ApiClient("192.0.2.1", _FakeSession([]))

    info = await client.async_discover()

    assert info.serial == discovery_raw["serial"]


class _FakeDatagramTransport:
    """Stands in for the real UDP socket transport (the test harness hard-
    blocks real sockets, even on localhost - pytest-homeassistant-custom-
    component's own pytest_runtest_setup calls pytest_socket.disable_socket()
    unconditionally on every test, ignoring the usual enable_socket marker).

    Wired to the REAL _DiscoveryProtocol instance via `on_sendto`, so
    `_async_udp_discover`'s actual future/timeout/parsing logic - and
    _DiscoveryProtocol's actual callbacks - run for real. Only the literal
    OS socket creation is faked.
    """

    def __init__(self, protocol: asyncio.DatagramProtocol, on_sendto) -> None:
        self._protocol = protocol
        self._on_sendto = on_sendto
        self.closed = False

    def sendto(self, data: bytes, addr: tuple[str, int] | None = None) -> None:
        self._on_sendto(self._protocol, data)

    def close(self) -> None:
        self.closed = True


async def _discover_with_fake_transport(host: str, timeout: float, on_sendto):
    """Run the real _async_udp_discover with loop.create_datagram_endpoint
    swapped for a fake that hands back a _FakeDatagramTransport wired to
    the real protocol factory - everything downstream of socket creation
    is genuine.
    """
    loop = asyncio.get_running_loop()
    real_create_datagram_endpoint = loop.create_datagram_endpoint

    async def _fake_create_datagram_endpoint(protocol_factory, **kwargs):
        protocol = protocol_factory()
        transport = _FakeDatagramTransport(protocol, on_sendto)
        return transport, protocol

    loop.create_datagram_endpoint = _fake_create_datagram_endpoint
    try:
        return await api_mod._async_udp_discover(host, timeout)
    finally:
        loop.create_datagram_endpoint = real_create_datagram_endpoint


async def test_async_udp_discover_parses_real_response(discovery_raw):
    """Exercises the real _async_udp_discover/_DiscoveryProtocol end to
    end: a fake "device" replies with a real captured discovery payload as
    soon as it "receives" the request, and the real parsing/future/
    timeout logic handles it.
    """
    reply = json.dumps(discovery_raw).encode()

    def _on_sendto(protocol, data):
        assert data == api_mod.DISCOVERY_MESSAGE
        protocol.datagram_received(reply, ("127.0.0.1", api_mod.DISCOVERY_PORT))

    result = await _discover_with_fake_transport("127.0.0.1", 2, _on_sendto)

    assert result == discovery_raw


async def test_async_udp_discover_times_out_with_no_response():
    """A device that receives the request but never replies must surface as
    a connection error rather than hang forever.
    """

    def _on_sendto(protocol, data):
        pass  # deliberately silent - no reply

    with pytest.raises(api_mod.Healthbox3ConnectionError):
        await _discover_with_fake_transport("127.0.0.1", 0.2, _on_sendto)


async def test_async_udp_discover_rejects_malformed_json():
    """A garbage (non-JSON) reply must raise cleanly, not crash."""

    def _on_sendto(protocol, data):
        protocol.datagram_received(b"not valid json", ("127.0.0.1", api_mod.DISCOVERY_PORT))

    with pytest.raises(api_mod.Healthbox3InvalidResponseError):
        await _discover_with_fake_transport("127.0.0.1", 2, _on_sendto)


async def test_async_udp_discover_rejects_invalid_utf8():
    """A reply that isn't even valid UTF-8 hits a different except branch
    (UnicodeDecodeError) than malformed-but-decodable JSON.
    """

    def _on_sendto(protocol, data):
        protocol.datagram_received(b"\xff\xfe\x00\x01", ("127.0.0.1", api_mod.DISCOVERY_PORT))

    with pytest.raises(api_mod.Healthbox3InvalidResponseError):
        await _discover_with_fake_transport("127.0.0.1", 2, _on_sendto)


async def test_async_udp_discover_surfaces_error_received():
    """A device/network error delivered via the transport's error_received
    callback (e.g. a real "port unreachable" ICMP) must surface as a
    connection error too, not just a plain timeout.
    """

    def _on_sendto(protocol, data):
        protocol.error_received(OSError("port unreachable"))

    with pytest.raises(api_mod.Healthbox3ConnectionError):
        await _discover_with_fake_transport("127.0.0.1", 2, _on_sendto)


async def test_discovery_protocol_datagram_received_resolves_future_once():
    """Direct unit test of _DiscoveryProtocol: real network timing can't
    reliably force a second datagram to arrive after the first, so this
    exercises the "already done" guard deterministically instead.
    """
    future: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
    protocol = api_mod._DiscoveryProtocol(future)

    protocol.datagram_received(b"first", ("127.0.0.1", 12345))
    assert await future == b"first"

    # Must not raise (asyncio.Future.set_result on an already-done future
    # raises InvalidStateError) - a second/duplicate reply is just ignored.
    protocol.datagram_received(b"second", ("127.0.0.1", 12345))


async def test_discovery_protocol_error_received_sets_future_exception():
    """Direct unit test of _DiscoveryProtocol.error_received: real ICMP
    "port unreachable" delivery is OS/timing-dependent and not reliable to
    force in a test, so this calls the callback directly instead.
    """
    future: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
    protocol = api_mod._DiscoveryProtocol(future)

    protocol.error_received(OSError("boom"))
    with pytest.raises(OSError, match="boom"):
        await future

    # Same already-done guard as datagram_received.
    protocol.error_received(OSError("second, should be ignored"))


# --- broadcast discovery ---


class _FakeBroadcastTransport:
    """Fake transport for the broadcast collect-many protocol.

    Unlike unicast's `_FakeDatagramTransport`, the broadcast socket isn't
    "connected" to a single remote, so `sendto` here takes an explicit
    address each call, and `on_sendto` receives it too.
    """

    def __init__(self, protocol: asyncio.DatagramProtocol, on_sendto) -> None:
        self._protocol = protocol
        self._on_sendto = on_sendto
        self.closed = False

    def sendto(self, data: bytes, addr: tuple[str, int] | None = None) -> None:
        self._on_sendto(self._protocol, data, addr)

    def close(self) -> None:
        self.closed = True


async def _discover_broadcast_with_fake_transport(timeout: float, on_sendto):
    """Run the real _async_udp_discover_broadcast with
    loop.create_datagram_endpoint swapped for a fake, same approach as
    _discover_with_fake_transport - only the literal OS socket creation is
    faked, everything downstream (protocol, timeout, parsing) is real.
    """
    loop = asyncio.get_running_loop()
    real_create_datagram_endpoint = loop.create_datagram_endpoint

    async def _fake_create_datagram_endpoint(protocol_factory, **kwargs):
        protocol = protocol_factory()
        transport = _FakeBroadcastTransport(protocol, on_sendto)
        return transport, protocol

    loop.create_datagram_endpoint = _fake_create_datagram_endpoint
    try:
        return await api_mod._async_udp_discover_broadcast(timeout)
    finally:
        loop.create_datagram_endpoint = real_create_datagram_endpoint


async def test_async_udp_discover_broadcast_collects_response(discovery_raw):
    """A broadcast reply is decoded the same way a unicast one is."""
    reply = json.dumps(discovery_raw).encode()

    def _on_sendto(protocol, data, addr):
        assert data == api_mod.DISCOVERY_MESSAGE
        assert addr == ("255.255.255.255", api_mod.DISCOVERY_PORT)
        protocol.datagram_received(reply, ("192.0.2.1", api_mod.DISCOVERY_PORT))

    results = await _discover_broadcast_with_fake_transport(0.05, _on_sendto)

    assert results == [discovery_raw]


async def test_async_udp_discover_broadcast_collects_multiple_responses(discovery_raw):
    """Broadcast can draw replies from more than one device, unlike unicast
    discover's single-future/first-response-wins design.
    """
    other = {**discovery_raw, "serial": "other-serial", "IP": "192.0.2.2"}

    def _on_sendto(protocol, data, addr):
        protocol.datagram_received(
            json.dumps(discovery_raw).encode(), ("192.0.2.1", api_mod.DISCOVERY_PORT)
        )
        protocol.datagram_received(
            json.dumps(other).encode(), ("192.0.2.2", api_mod.DISCOVERY_PORT)
        )

    results = await _discover_broadcast_with_fake_transport(0.05, _on_sendto)

    assert results == [discovery_raw, other]


async def test_async_udp_discover_broadcast_times_out_with_no_responses():
    """No replies within the window must return an empty list, not hang or
    raise - broadcast delivery being unreliable is the expected common
    case, not a failure state.
    """

    def _on_sendto(protocol, data, addr):
        pass  # deliberately silent - no reply

    results = await _discover_broadcast_with_fake_transport(0.05, _on_sendto)

    assert results == []


async def test_async_udp_discover_broadcast_ignores_malformed_response(discovery_raw):
    """A garbage reply from one device must not prevent a good reply from
    another device being returned.
    """

    def _on_sendto(protocol, data, addr):
        protocol.datagram_received(b"not valid json", ("192.0.2.9", api_mod.DISCOVERY_PORT))
        protocol.datagram_received(
            json.dumps(discovery_raw).encode(), ("192.0.2.1", api_mod.DISCOVERY_PORT)
        )

    results = await _discover_broadcast_with_fake_transport(0.05, _on_sendto)

    assert results == [discovery_raw]


async def test_async_discover_broadcast_parses_and_dedupes_by_serial(
    monkeypatch, discovery_raw
):
    """async_discover_broadcast wires the raw JSON through _parse_discovery
    and de-dupes repeat replies from the same device (same serial).
    """

    async def _fake_udp_discover_broadcast(timeout):
        return [discovery_raw, dict(discovery_raw)]  # same device, two replies

    monkeypatch.setattr(
        api_mod, "_async_udp_discover_broadcast", _fake_udp_discover_broadcast
    )

    devices = await api_mod.async_discover_broadcast()

    assert len(devices) == 1
    assert devices[0].serial == discovery_raw["serial"]


async def test_async_discover_broadcast_returns_empty_list_with_no_responses(
    monkeypatch,
):
    async def _fake_udp_discover_broadcast(timeout):
        return []

    monkeypatch.setattr(
        api_mod, "_async_udp_discover_broadcast", _fake_udp_discover_broadcast
    )

    assert await api_mod.async_discover_broadcast() == []


async def test_async_discover_broadcast_skips_malformed_shape(monkeypatch, discovery_raw):
    """A response missing required fields is skipped, not fatal to the
    whole batch.
    """
    bad = {"unexpected": "shape"}

    async def _fake_udp_discover_broadcast(timeout):
        return [bad, discovery_raw]

    monkeypatch.setattr(
        api_mod, "_async_udp_discover_broadcast", _fake_udp_discover_broadcast
    )

    devices = await api_mod.async_discover_broadcast()

    assert len(devices) == 1
    assert devices[0].serial == discovery_raw["serial"]


async def test_broadcast_discovery_protocol_collects_all_datagrams():
    """Direct unit test of _BroadcastDiscoveryProtocol: unlike
    _DiscoveryProtocol, every datagram is kept, not just the first.
    """
    protocol = api_mod._BroadcastDiscoveryProtocol()

    protocol.datagram_received(b"first", ("127.0.0.1", 12345))
    protocol.datagram_received(b"second", ("127.0.0.2", 12345))

    assert protocol.responses == [b"first", b"second"]


async def test_broadcast_discovery_protocol_error_received_does_not_raise():
    """error_received just logs and returns - there's no future to fail,
    since the caller collects over a fixed window instead of awaiting a
    single response.
    """
    protocol = api_mod._BroadcastDiscoveryProtocol()

    protocol.error_received(OSError("boom"))  # must not raise
