"""Unit power draw and the energy total integrated from it."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.components.sensor import SensorExtraStoredData

from custom_components.healthbox3 import api as api_mod
from custom_components.healthbox3.const import ENERGY_MAX_GAP_SECONDS
from custom_components.healthbox3.sensor import Healthbox3EnergySensor

from .conftest import setup_integration

_POWER_ENTITY = "sensor.healthbox_3_0_power"
_ENERGY_ENTITY = "sensor.healthbox_3_0_energy"


# --- parsing, against the real captured response ---


def test_device_telemetry_parses_power(v1_device_raw):
    telemetry = api_mod._parse_device(v1_device_raw)

    assert telemetry.power == pytest.approx(v1_device_raw["power"])


def test_device_telemetry_does_not_expose_calibration_power(device_telemetry):
    assert not hasattr(device_telemetry, "c_mode_power")


@pytest.mark.parametrize(
    "raw",
    [
        {"power": None},
        {"power": "11.2"},
        {"power": True},
        {"power": float("nan")},
        {"power": float("inf")},
        {},
    ],
)
def test_device_telemetry_treats_unusable_power_as_absent(raw):
    assert api_mod._parse_device(raw).power is None


def test_device_telemetry_rejects_non_object():
    with pytest.raises(api_mod.Healthbox3InvalidResponseError):
        api_mod._parse_device(["not", "an", "object"])


# --- entities ---


async def test_power_sensor_reports_draw(hass, mock_api_client, v1_data, boost_status, device_telemetry):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        healthbox_data=v1_data,
        boost_status=boost_status,
        device=device_telemetry,
    )

    state = hass.states.get(_POWER_ENTITY)
    assert float(state.state) == pytest.approx(device_telemetry.power)
    assert state.attributes["unit_of_measurement"] == "W"


async def test_power_and_energy_not_created_without_api_key(hass, mock_api_client, v1_data, boost_status, device_telemetry):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        api_key=None,
        healthbox_data=v1_data,
        boost_status=boost_status,
        device=device_telemetry,
    )

    assert hass.states.get(_POWER_ENTITY) is None
    assert hass.states.get(_ENERGY_ENTITY) is None


async def test_energy_total_survives_restart(hass, mock_api_client, v1_data, boost_status, device_telemetry):
    restored = SensorExtraStoredData(native_value=1.5, native_unit_of_measurement="kWh")
    with patch(
        "homeassistant.components.sensor.RestoreSensor.async_get_last_sensor_data",
        AsyncMock(return_value=restored),
    ):
        await setup_integration(
            hass,
            mock_api_client,
            serial=v1_data.serial,
            healthbox_data=v1_data,
            boost_status=boost_status,
            device=device_telemetry,
        )

    # The first sample only sets the anchor, so the restored total is unchanged.
    assert float(hass.states.get(_ENERGY_ENTITY).state) == pytest.approx(1.5)


# --- integration, driven by a fake clock ---


def _energy_entity(clock_value: list[float]):
    """Build the energy entity against a stub coordinator, with a fake clock.

    `clock_value` is a one-item list the test advances between samples.
    """
    coordinator = SimpleNamespace(
        data=SimpleNamespace(
            healthbox=SimpleNamespace(description="Healthbox 3.0"),
            global_info=None,
            device=None,
        ),
        unit_device_id=None,
    )
    entity = Healthbox3EnergySensor(coordinator, "SERIAL", clock=lambda: clock_value[0])
    entity.async_write_ha_state = Mock()
    return entity, coordinator


def _sample(entity, coordinator, watts: float | None) -> None:
    coordinator.data.device = None if watts is None else api_mod.DeviceTelemetry(power=watts)
    entity._handle_coordinator_update()


def test_energy_is_trapezoidal_over_samples():
    clock = [0.0]
    entity, coordinator = _energy_entity(clock)

    _sample(entity, coordinator, 100.0)
    clock[0] = 60.0
    _sample(entity, coordinator, 200.0)

    # Average 150 W for 60 s is 9000 J, which is 0.0025 kWh.
    assert entity.native_value == pytest.approx(0.0025)


def test_energy_ignores_gap_longer_than_the_limit():
    clock = [0.0]
    entity, coordinator = _energy_entity(clock)

    _sample(entity, coordinator, 100.0)
    clock[0] = ENERGY_MAX_GAP_SECONDS + 1
    _sample(entity, coordinator, 100.0)

    assert entity.native_value == 0.0


def test_energy_counts_a_gap_at_exactly_the_limit():
    clock = [0.0]
    entity, coordinator = _energy_entity(clock)

    _sample(entity, coordinator, 100.0)
    clock[0] = ENERGY_MAX_GAP_SECONDS
    _sample(entity, coordinator, 100.0)

    assert entity.native_value == pytest.approx(100.0 * ENERGY_MAX_GAP_SECONDS / 3_600_000)


def test_outage_clears_the_previous_sample():
    clock = [0.0]
    entity, coordinator = _energy_entity(clock)

    _sample(entity, coordinator, 100.0)
    clock[0] = 30.0
    _sample(entity, coordinator, None)
    clock[0] = 60.0
    _sample(entity, coordinator, 100.0)

    # Nothing is counted across the outage, and the reading after it only anchors.
    assert entity.native_value == 0.0
