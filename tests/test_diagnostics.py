"""Tests for the diagnostics platform."""

from __future__ import annotations

from custom_components.healthbox3.diagnostics import async_get_config_entry_diagnostics

from .conftest import setup_integration


async def test_diagnostics_redacts_sensitive_fields(
    hass, mock_api_client, v2_data, boost_status
):
    entry = await setup_integration(
        hass,
        mock_api_client,
        serial=v2_data.serial,
        healthbox_data=v2_data,
        boost_status=boost_status,
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["entry_data"]["api_key"] == "**REDACTED**"
    assert diagnostics["entry_data"]["host"] == "**REDACTED**"
    assert diagnostics["healthbox"]["serial"] == "**REDACTED**"
    assert diagnostics["healthbox"]["warranty_number"] == "**REDACTED**"

    room1 = next(r for r in diagnostics["healthbox"]["rooms"] if r["id"] == 1)
    assert room1["parameters"]["valve_warranty"] == "**REDACTED**"


async def test_diagnostics_includes_boost_and_use_v2(
    hass, mock_api_client, v1_data, boost_status
):
    entry = await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        api_key=None,
        healthbox_data=v1_data,
        boost_status=boost_status,
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["use_v2"] is False
    assert diagnostics["boost"]["1"]["enable"] is False
    assert diagnostics["boost_params"]["1"]["level"] == 100.0
    assert diagnostics["boost_all_params"] == {"level": 100.0, "timeout": 900}
