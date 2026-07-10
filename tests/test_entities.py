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


async def test_room_airflow_sensor_reports_percentage_of_nominal(
    hass, mock_api_client, v2_data, boost_status
):
    """Toilet (room 1): flow_rate=6.0 m3/h, nominal=30.0 m3/h -> 20%."""
    await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
    )

    airflow = hass.states.get(f"sensor.{_PREFIX}_toilet_airflow")
    assert airflow is not None
    assert float(airflow.state) == pytest.approx(20.0)


async def test_room_airflow_sensor_not_created_without_nominal_or_flow_rate(
    hass, mock_api_client, v2_data, boost_status
):
    """A room missing either nominal or flow_rate must simply not get an
    airflow entity - not an error, not an "unavailable" entity.
    """
    stripped = copy.deepcopy(v2_data)
    toilet = next(r for r in stripped.rooms if r.id == 1)
    del toilet.parameters["nominal"]

    await setup_integration(
        hass,
        mock_api_client,
        serial=stripped.serial,
        healthbox_data=stripped,
        boost_status=boost_status,
    )

    assert hass.states.get(f"sensor.{_PREFIX}_toilet_airflow") is None
    # Other rooms, unaffected, still get their airflow sensor.
    assert hass.states.get(f"sensor.{_PREFIX}_bathroom_airflow") is not None


async def test_room_airflow_sensor_not_created_with_non_numeric_nominal(
    hass, mock_api_client, v2_data, boost_status
):
    """A non-numeric nominal value (confirmed never seen on real hardware,
    but not something the API schema actually rules out) must be treated
    the same as a missing one - not created, not a crash.
    """
    stripped = copy.deepcopy(v2_data)
    toilet = next(r for r in stripped.rooms if r.id == 1)
    toilet.parameters["nominal"].value = "not-a-number"

    await setup_integration(
        hass,
        mock_api_client,
        serial=stripped.serial,
        healthbox_data=stripped,
        boost_status=boost_status,
    )

    assert hass.states.get(f"sensor.{_PREFIX}_toilet_airflow") is None
    assert hass.states.get(f"sensor.{_PREFIX}_bathroom_airflow") is not None


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


async def test_global_ventilation_level_sensor_reports_state(
    hass, mock_api_client, v2_data, boost_status, device_decision
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
        decision=device_decision,
    )

    state = hass.states.get(f"sensor.{_PREFIX}_ventilation_level")
    assert state is not None
    assert float(state.state) == 45.0


async def test_global_ventilation_level_sensor_not_created_without_api_key(
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

    assert hass.states.get(f"sensor.{_PREFIX}_ventilation_level") is None


async def test_global_ventilation_level_sensor_unavailable_when_decision_fetch_failed(
    hass, mock_api_client, v2_data, boost_status, device_decision
):
    entry = await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
        decision=device_decision,
    )
    coordinator = entry.runtime_data

    coordinator.data.decision = None
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    assert hass.states.get(f"sensor.{_PREFIX}_ventilation_level").state == "unavailable"


async def test_firmware_version_sensor_reports_state(
    hass, mock_api_client, v2_data, boost_status, firmware_version
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
        firmware_version=firmware_version,
    )

    state = hass.states.get(f"sensor.{_PREFIX}_firmware_version")
    assert state is not None
    assert state.state == "2.6.9"


async def test_firmware_version_sensor_not_created_without_api_key(
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

    assert hass.states.get(f"sensor.{_PREFIX}_firmware_version") is None


async def test_firmware_version_sensor_unavailable_when_fetch_failed(
    hass, mock_api_client, v2_data, boost_status, firmware_version
):
    entry = await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
        firmware_version=firmware_version,
    )
    coordinator = entry.runtime_data

    coordinator.data.firmware_version = None
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    assert hass.states.get(f"sensor.{_PREFIX}_firmware_version").state == "unavailable"


async def test_device_errors_sensor_reports_count(
    hass, mock_api_client, v2_data, boost_status, device_errors
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
        errors=device_errors,
    )

    state = hass.states.get(f"sensor.{_PREFIX}_device_errors")
    assert state is not None
    assert state.state == "2"


async def test_device_errors_sensor_reports_zero_and_stays_available_with_no_errors(
    hass, mock_api_client, v2_data, boost_status
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
        errors=[],
    )

    state = hass.states.get(f"sensor.{_PREFIX}_device_errors")
    assert state is not None
    assert state.state == "0"
    assert "code" not in state.attributes


async def test_device_errors_sensor_attributes_reflect_most_recent_error(
    hass, mock_api_client, v2_data, boost_status, device_errors
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
        errors=device_errors,
    )

    state = hass.states.get(f"sensor.{_PREFIX}_device_errors")
    # device_errors fixture: E042 at 08:30 (2026-01-15) is later than W007
    # at 22:10 (2026-01-14).
    assert state.attributes["code"] == "E042"
    assert state.attributes["description"] == "Sensor fault in room 3"
    assert state.attributes["severity"] == "critical"
    assert state.attributes["time"] == "2026-01-15T08:30:00Z"
    # E042 doesn't match any known 3-digit prefix (see
    # api._ERROR_CATEGORIES) - the fixture is hand-built, not a real code.
    assert state.attributes["category"] == "Unknown"


async def test_device_errors_sensor_not_created_without_api_key(
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

    assert hass.states.get(f"sensor.{_PREFIX}_device_errors") is None


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


async def test_demand_control_switch_reports_state(
    hass, mock_api_client, v2_data, boost_status, device_decision
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
        decision=device_decision,
    )

    state = hass.states.get(f"switch.{_PREFIX}_demand_control")
    assert state is not None
    # The fixture's raw program.enable is False, but this switch presents
    # the negation - confirmed on real hardware that program.enable false
    # means demand control ON in the Renson app (see switch.py's
    # Healthbox3DemandControlSwitch docstring).
    assert state.state == "on"


async def test_demand_control_switch_not_created_without_api_key(
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

    assert hass.states.get(f"switch.{_PREFIX}_demand_control") is None


async def test_demand_control_switch_turn_on_calls_api(
    hass, mock_api_client, v2_data, boost_status, device_decision
):
    """Turning demand control ON writes program.enable=False - the
    negated raw field (see switch.py's Healthbox3DemandControlSwitch
    docstring).
    """
    await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
        decision=device_decision,
    )

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": f"switch.{_PREFIX}_demand_control"},
        blocking=True,
    )

    mock_api_client.async_set_program_enable.assert_awaited_once_with(False)


async def test_demand_control_switch_turn_off_calls_api(
    hass, mock_api_client, v2_data, boost_status, device_decision
):
    """Turning demand control OFF writes program.enable=True - the
    negated raw field (see switch.py's Healthbox3DemandControlSwitch
    docstring).
    """
    await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
        decision=device_decision,
    )

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": f"switch.{_PREFIX}_demand_control"},
        blocking=True,
    )

    mock_api_client.async_set_program_enable.assert_awaited_once_with(True)


async def test_demand_control_switch_unavailable_when_decision_fetch_failed(
    hass, mock_api_client, v2_data, boost_status, device_decision
):
    """Matches how a room-removal makes the profile select unavailable:
    mutate the coordinator's already-fetched data directly and trigger a
    listener update, simulating what a real failed /v1/decision fetch
    leaves behind (decision=None - see coordinator._async_get_decision_data).
    """
    entry = await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
        decision=device_decision,
    )
    coordinator = entry.runtime_data

    coordinator.data.decision = None
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    assert hass.states.get(f"switch.{_PREFIX}_demand_control").state == "unavailable"


async def test_silent_switch_reports_state(
    hass, mock_api_client, v2_data, boost_status, device_decision
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
        decision=device_decision,
    )

    state = hass.states.get(f"switch.{_PREFIX}_silent")
    assert state is not None
    assert state.state == "off"  # the fixture's silent.enable is False


async def test_silent_switch_not_created_without_api_key(
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

    assert hass.states.get(f"switch.{_PREFIX}_silent") is None


async def test_silent_switch_turn_on_calls_api(
    hass, mock_api_client, v2_data, boost_status, device_decision
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
        decision=device_decision,
    )

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": f"switch.{_PREFIX}_silent"},
        blocking=True,
    )

    mock_api_client.async_set_silent_enable.assert_awaited_once_with(True)


async def test_silent_switch_turn_off_calls_api(
    hass, mock_api_client, v2_data, boost_status, device_decision
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
        decision=device_decision,
    )

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": f"switch.{_PREFIX}_silent"},
        blocking=True,
    )

    mock_api_client.async_set_silent_enable.assert_awaited_once_with(False)


async def test_silent_switch_unavailable_when_decision_fetch_failed(
    hass, mock_api_client, v2_data, boost_status, device_decision
):
    entry = await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
        decision=device_decision,
    )
    coordinator = entry.runtime_data

    coordinator.data.decision = None
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    assert hass.states.get(f"switch.{_PREFIX}_silent").state == "unavailable"
