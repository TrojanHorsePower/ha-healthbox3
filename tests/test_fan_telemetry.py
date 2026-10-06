"""The fan's own readings from /v1/device: flow, pressure, rpm, voltage, power."""

from __future__ import annotations

import pytest
from homeassistant.const import EntityCategory
from homeassistant.helpers import entity_registry as er

from custom_components.healthbox3 import api as api_mod
from custom_components.healthbox3.const import DOMAIN

from .conftest import setup_integration

# Telemetry field, and the unique-ID suffix of its sensor.
_FIELDS = {
    "fan_flow": "fan_flow",
    "fan_pressure": "fan_pressure",
    "fan_rpm": "fan_rpm",
    "fan_voltage": "fan_voltage",
    "fan_power": "fan_power",
}


def _entity_id(hass, serial: str, key: str) -> str | None:
    # Looked up by unique ID: the entity ID comes from the translated name,
    # which is not always the key ("Fan speed" for fan_rpm).
    return er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{serial}_{key}")


# --- parsing, against the real captured response ---


def test_fan_fields_parse_from_fixture(v1_device_raw):
    telemetry = api_mod._parse_device(v1_device_raw)
    fan = v1_device_raw["fan"]

    assert telemetry.fan_flow == pytest.approx(fan["flow"])
    assert telemetry.fan_pressure == pytest.approx(fan["pressure"])
    assert telemetry.fan_rpm == pytest.approx(fan["rpm"])
    assert telemetry.fan_voltage == pytest.approx(fan["voltage"])
    assert telemetry.fan_power == pytest.approx(fan["power"])


def test_missing_fan_block_leaves_fan_fields_absent(v1_device_raw):
    raw = {key: value for key, value in v1_device_raw.items() if key != "fan"}
    telemetry = api_mod._parse_device(raw)

    assert telemetry.fan_flow is None
    assert telemetry.fan_power is None
    assert telemetry.power == pytest.approx(v1_device_raw["power"])


def test_non_numeric_fan_values_are_absent():
    raw = {"fan": {"flow": "151", "pressure": True, "rpm": float("nan"), "voltage": None}}
    telemetry = api_mod._parse_device(raw)

    assert telemetry.fan_flow is None
    assert telemetry.fan_pressure is None
    assert telemetry.fan_rpm is None
    assert telemetry.fan_voltage is None


# --- entities ---


@pytest.mark.parametrize("key", list(_FIELDS))
async def test_fan_sensor_reports_its_reading(
    hass, mock_api_client, v1_data, boost_status, device_telemetry, key
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        healthbox_data=v1_data,
        boost_status=boost_status,
        device=device_telemetry,
    )

    entity_id = _entity_id(hass, v1_data.serial, key)
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert float(state.state) == pytest.approx(getattr(device_telemetry, _FIELDS[key]))


async def test_fan_sensors_not_created_without_api_key(
    hass, mock_api_client, v1_data, boost_status, device_telemetry
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        api_key=None,
        healthbox_data=v1_data,
        boost_status=boost_status,
        device=device_telemetry,
    )

    for key in _FIELDS:
        assert _entity_id(hass, v1_data.serial, key) is None


async def test_fan_flow_is_enabled_and_the_rest_are_diagnostic(
    hass, mock_api_client, v1_data, boost_status, device_telemetry
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        healthbox_data=v1_data,
        boost_status=boost_status,
        device=device_telemetry,
    )

    registry = er.async_get(hass)
    flow = registry.async_get(_entity_id(hass, v1_data.serial, "fan_flow"))
    assert flow.entity_category is None
    for key in ("fan_pressure", "fan_rpm", "fan_voltage", "fan_power"):
        entry = registry.async_get(_entity_id(hass, v1_data.serial, key))
        assert entry.entity_category is EntityCategory.DIAGNOSTIC


async def test_fan_sensor_unavailable_when_device_omits_its_reading(
    hass, mock_api_client, v1_data, boost_status
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        healthbox_data=v1_data,
        boost_status=boost_status,
        device=api_mod.DeviceTelemetry(power=5.0),
    )

    entity_id = _entity_id(hass, v1_data.serial, "fan_flow")
    assert hass.states.get(entity_id).state == "unavailable"
