"""Shared fixtures for Healthbox3 tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_API_KEY, CONF_HOST

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.healthbox3 import api as api_mod
from custom_components.healthbox3.const import DOMAIN

FIXTURES_DIR = Path(__file__).parent.parent / "docs" / "fixtures"


def _load_fixture(name: str) -> dict:
    with (FIXTURES_DIR / name).open() as f:
        return json.load(f)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make custom_components/healthbox3 discoverable to Home Assistant."""
    yield


@pytest.fixture(autouse=True)
def mock_discover_broadcast():
    """Default broadcast discovery to "nothing found".

    Config flow tests that don't care about discovery (i.e. most of them)
    would otherwise try to open a real UDP socket the moment the user step
    runs, since it now attempts discovery unconditionally. Tests that do
    care override this mock's return_value/side_effect explicitly.
    """
    with patch(
        "custom_components.healthbox3.config_flow.async_discover_broadcast",
        AsyncMock(return_value=[]),
    ) as mock:
        yield mock


@pytest.fixture(autouse=True)
def mock_coordinator_discover_broadcast():
    """Same reasoning as mock_discover_broadcast, for the coordinator's own
    relocate-on-connection-error probe (a separate import into
    coordinator.py, not the same patch target as the config flow's).
    """
    with patch(
        "custom_components.healthbox3.coordinator.async_discover_broadcast",
        AsyncMock(return_value=[]),
    ) as mock:
        yield mock


@pytest.fixture
def v1_data_raw() -> dict:
    """Raw JSON from a real device's /v1/api/data/current."""
    return _load_fixture("v1-data-current.json")


@pytest.fixture
def v2_data_raw() -> dict:
    """Raw JSON from a real device's /v2/api/data/current."""
    return _load_fixture("v2-data-current.json")


@pytest.fixture
def boost_raw() -> dict:
    """Raw JSON from a real device's /v1/api/boost/1."""
    return _load_fixture("v1-boost-room1.json")


@pytest.fixture
def discovery_raw() -> dict:
    """Raw JSON from a real device's discovery response.

    The captured file has a leading "<n>\\t(ip, port)" prefix from the
    tool used to record it, so extract just the JSON object.
    """
    content = (FIXTURES_DIR / "discovery-response.json").read_text()
    start = content.index("{")
    end = content.rindex("}") + 1
    return json.loads(content[start:end])


@pytest.fixture
def v1_data(v1_data_raw) -> api_mod.HealthboxData:
    """Parsed HealthboxData from the real v1 fixture."""
    return api_mod._parse_v1_data(v1_data_raw)


@pytest.fixture
def v2_data(v2_data_raw) -> api_mod.HealthboxData:
    """Parsed HealthboxData from the real v2 fixture."""
    return api_mod._parse_v2_data(v2_data_raw)


@pytest.fixture
def boost_status(boost_raw) -> api_mod.BoostStatus:
    """Parsed BoostStatus from the real boost fixture."""
    return api_mod._parse_boost(boost_raw)


@pytest.fixture
def mock_api_client():
    """Patch the API client used by __init__.py's async_setup_entry.

    autospec=True is required so autodetected async methods (e.g.
    async_get_api_key_status) become AsyncMocks instead of plain MagicMocks
    that return a non-awaitable value.
    """
    with patch(
        "custom_components.healthbox3.Healthbox3ApiClient",
        autospec=True,
    ) as mock_cls:
        yield mock_cls.return_value


def make_config_entry(hass, *, serial: str, api_key: str | None = "goodkey") -> MockConfigEntry:
    """Create and register a Healthbox3 config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "192.0.2.1", CONF_API_KEY: api_key},
        unique_id=serial,
    )
    entry.add_to_hass(hass)
    return entry


async def setup_integration(
    hass,
    mock_api_client,
    *,
    serial: str,
    api_key: str | None = "goodkey",
    api_key_valid: bool | None = None,
    healthbox_data: api_mod.HealthboxData | None = None,
    boost_status: api_mod.BoostStatus | None = None,
) -> MockConfigEntry:
    """Create a config entry and run async_setup_entry against a mocked client.

    __init__.py always checks /v2/api/api_key/status on startup, regardless
    of whether a key was ever stored in the config entry - activation is a
    one-time device-side change, not tied to what we remember. So
    `api_key_valid` (whether the *device* currently reports privileged
    access) is independent of `api_key` (whether *this config entry* has a
    key on file). Defaults to matching `api_key` when not given, to cover
    the common case of "the entry's own key is/isn't valid".
    """
    entry = make_config_entry(hass, serial=serial, api_key=api_key)

    effective_valid = bool(api_key) if api_key_valid is None else api_key_valid
    mock_api_client.async_get_api_key_status.return_value = api_mod.ApiKeyStatus(
        state="valid" if effective_valid else "empty",
        disable_telemetry_data_allowed=effective_valid,
        local_sensor_data_allowed=effective_valid,
    )
    if healthbox_data is not None:
        mock_api_client.async_get_v1_data_current = AsyncMock(
            return_value=healthbox_data
        )
        mock_api_client.async_get_v2_data_current = AsyncMock(
            return_value=healthbox_data
        )
    if boost_status is not None:
        mock_api_client.async_get_boost = AsyncMock(return_value=boost_status)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
