"""Entity state tests for the number platform."""

from __future__ import annotations

from .conftest import setup_integration

# The device name ("Healthbox 3.0" in both fixtures) becomes an entity_id
# slug prefix once has_entity_name groups every entity under one device.
_PREFIX = "healthbox_3_0"


async def test_global_minimum_number_reports_state(
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

    state = hass.states.get(f"number.{_PREFIX}_minimum_ventilation_level")
    assert state is not None
    assert float(state.state) == 20.0


async def test_global_minimum_number_not_created_without_api_key(
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

    assert hass.states.get(f"number.{_PREFIX}_minimum_ventilation_level") is None


async def test_global_minimum_number_set_value_calls_api(
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
        "number",
        "set_value",
        {"entity_id": f"number.{_PREFIX}_minimum_ventilation_level", "value": 15},
        blocking=True,
    )

    mock_api_client.async_set_global_minimum.assert_awaited_once_with(15.0)


async def test_global_minimum_number_unavailable_when_decision_fetch_failed(
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

    assert (
        hass.states.get(f"number.{_PREFIX}_minimum_ventilation_level").state
        == "unavailable"
    )


async def test_breeze_temperature_number_reports_state(
    hass, mock_api_client, v2_data, boost_status, breeze_settings
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
        breeze=breeze_settings,
    )

    state = hass.states.get(f"number.{_PREFIX}_breeze_temperature")
    assert state is not None
    assert float(state.state) == 30.0


async def test_breeze_temperature_number_not_created_without_api_key(
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

    assert hass.states.get(f"number.{_PREFIX}_breeze_temperature") is None


async def test_breeze_temperature_number_set_value_calls_api(
    hass, mock_api_client, v2_data, boost_status, breeze_settings
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
        breeze=breeze_settings,
    )

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": f"number.{_PREFIX}_breeze_temperature", "value": 18},
        blocking=True,
    )

    mock_api_client.async_set_breeze_temp.assert_awaited_once_with(18.0)


async def test_breeze_temperature_number_unavailable_when_breeze_fetch_failed(
    hass, mock_api_client, v2_data, boost_status, breeze_settings
):
    entry = await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
        breeze=breeze_settings,
    )
    coordinator = entry.runtime_data

    coordinator.data.breeze = None
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    assert (
        hass.states.get(f"number.{_PREFIX}_breeze_temperature").state
        == "unavailable"
    )


async def test_room_co2_threshold_number_reports_state(
    hass, mock_api_client, v2_data, boost_status, room_decisions
):
    """Room 1 ("Toilet") has CO2 static demand enabled in the fixture;
    room 2 ("Bathroom") doesn't - only room 1 gets an entity.
    """
    await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
        room_decisions=room_decisions,
    )

    state = hass.states.get(f"number.{_PREFIX}_toilet_co2_threshold")
    assert state is not None
    assert float(state.state) == 650.0

    assert hass.states.get(f"number.{_PREFIX}_bathroom_co2_threshold") is None


async def test_room_co2_threshold_number_not_created_without_api_key(
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

    assert hass.states.get(f"number.{_PREFIX}_toilet_co2_threshold") is None


async def test_room_co2_threshold_number_set_value_preserves_range_calls_api(
    hass, mock_api_client, v2_data, boost_status, room_decisions
):
    """The fixture's room 1 has minimum=650/maximum=800 (a 150-wide range) -
    setting a new minimum must preserve that range, not just the minimum.
    """
    await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
        room_decisions=room_decisions,
    )

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": f"number.{_PREFIX}_toilet_co2_threshold", "value": 700},
        blocking=True,
    )

    mock_api_client.async_set_room_co2_threshold.assert_awaited_once_with(
        1, minimum=700.0, maximum=850.0
    )


async def test_room_co2_threshold_number_unavailable_when_room_decisions_fetch_failed(
    hass, mock_api_client, v2_data, boost_status, room_decisions
):
    entry = await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
        room_decisions=room_decisions,
    )
    coordinator = entry.runtime_data

    coordinator.data.room_decisions = {}
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    assert (
        hass.states.get(f"number.{_PREFIX}_toilet_co2_threshold").state
        == "unavailable"
    )


async def test_silent_reduction_number_reports_state(
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

    state = hass.states.get(f"number.{_PREFIX}_silent_reduction")
    assert state is not None
    assert float(state.state) == 5.0


async def test_silent_reduction_number_not_created_without_api_key(
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

    assert hass.states.get(f"number.{_PREFIX}_silent_reduction") is None


async def test_silent_reduction_number_set_value_calls_api(
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
        "number",
        "set_value",
        {"entity_id": f"number.{_PREFIX}_silent_reduction", "value": 15},
        blocking=True,
    )

    mock_api_client.async_set_silent_reduction.assert_awaited_once_with(15.0)


async def test_silent_reduction_number_unavailable_when_decision_fetch_failed(
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

    assert (
        hass.states.get(f"number.{_PREFIX}_silent_reduction").state == "unavailable"
    )
