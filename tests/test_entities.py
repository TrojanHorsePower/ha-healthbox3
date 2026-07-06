"""Entity state tests for sensor/switch/select platforms."""

from __future__ import annotations

import copy

import pytest

from .conftest import setup_integration

# The device name ("Healthbox 3.0" in both fixtures) becomes an entity_id
# slug prefix once has_entity_name groups every entity under one device.
_PREFIX = "healthbox_3_0"


async def test_room_sensors_report_values_and_empty_co2_is_unavailable(
    hass, mock_api_client, v2_data, boost_status
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
    )

    temp = hass.states.get(f"sensor.{_PREFIX}_toilet_temperature")
    assert temp is not None
    assert float(temp.state) == pytest.approx(22.0)

    # room 1's CO2 sensor has an empty `parameter` dict on real hardware.
    co2 = hass.states.get(f"sensor.{_PREFIX}_toilet_co2")
    assert co2 is not None
    assert co2.state == "unavailable"

    # room 3's CO2 sensor does report.
    co2_room3 = hass.states.get(f"sensor.{_PREFIX}_guest_room_co2")
    assert co2_room3.state == "500.0"


async def test_global_aqi_sensor_has_main_pollutant_and_room_attributes(
    hass, mock_api_client, v2_data, boost_status
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
    )

    global_aqi = hass.states.get(f"sensor.{_PREFIX}_air_quality_index")
    assert global_aqi is not None
    assert float(global_aqi.state) == pytest.approx(45.0)
    assert global_aqi.attributes["main_pollutant"] == "indoor CO2"
    assert global_aqi.attributes["room"] == "Bedroom"


async def test_profile_select_reports_current_option(
    hass, mock_api_client, v2_data, boost_status
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
    )

    state = hass.states.get(f"select.{_PREFIX}_toilet_profile")
    assert state is not None
    assert state.state == "health"
    assert set(state.attributes["options"]) == {"eco", "health", "intense"}


async def test_profile_select_not_created_without_api_key(
    hass, mock_api_client, v1_data, boost_status
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        api_key=None,
        healthbox_data=v1_data,
        boost_status=boost_status,
    )

    assert hass.states.get(f"select.{_PREFIX}_toilet_profile") is None


async def test_profile_select_change_calls_api(hass, mock_api_client, v2_data, boost_status):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
    )

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": f"select.{_PREFIX}_toilet_profile", "option": "eco"},
        blocking=True,
    )

    mock_api_client.async_set_profile.assert_awaited_once_with(1, "eco")


async def test_profile_select_becomes_unavailable_when_room_removed_from_device(
    hass, mock_api_client, v2_data, boost_status
):
    """Unlike boost, profile has no separate cache: once its room is gone,
    the select's own `available` property goes False, so Home Assistant's
    service layer refuses the call before ever reaching our entity code -
    a stricter, earlier safeguard than the explicit boost-switch guard.
    """
    entry = await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
    )
    coordinator = entry.runtime_data

    shrunk = copy.deepcopy(v2_data)
    shrunk.rooms = [r for r in shrunk.rooms if r.id != 1]
    coordinator.data.healthbox = shrunk
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    assert hass.states.get(f"select.{_PREFIX}_toilet_profile").state == "unavailable"
