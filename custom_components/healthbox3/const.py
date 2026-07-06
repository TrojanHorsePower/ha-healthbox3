"""Constants for the Renson Healthbox 3 integration."""

from datetime import timedelta

DOMAIN = "healthbox3"

DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)

# Discovery (UDP broadcast/unicast on port 49152), documented in the
# 3rd-party API PDF. Not used by the config flow yet (manual IP entry only)
# but the client implements it for a future discovery step.
DISCOVERY_PORT = 49152
DISCOVERY_MESSAGE = b"RENSON_DEVICE/JSON?"
DISCOVERY_TIMEOUT = 5

# v1 API - no authentication, always available.
API_V1_DATA_CURRENT = "/v1/api/data/current"
API_V1_BOOST = "/v1/api/boost/{room_id}"

# v2 API - requires an activated API key.
API_V2_DATA_CURRENT = "/v2/api/data/current"
API_V2_API_KEY = "/v2/api/api_key"
API_V2_API_KEY_STATUS = "/v2/api/api_key/status"
API_V2_PROFILE_NAME = "/v2/api/data/current/room/{room_id}/profile_name"

API_KEY_STATE_VALID = "valid"
API_KEY_STATE_EMPTY = "empty"

PROFILE_ECO = "eco"
PROFILE_HEALTH = "health"
PROFILE_INTENSE = "intense"
PROFILES = [PROFILE_ECO, PROFILE_HEALTH, PROFILE_INTENSE]

# Sensor "type" values as they appear on the wire (confirmed against
# docs/fixtures/v2-data-current.json). These are used as parser keys, not
# translation keys.
SENSOR_TYPE_TEMPERATURE = "indoor temperature"
SENSOR_TYPE_HUMIDITY = "indoor relative humidity"
SENSOR_TYPE_CO2 = "indoor CO2"
SENSOR_TYPE_VOC = "indoor volatile organic compounds"
SENSOR_TYPE_AQI = "indoor air quality index"
SENSOR_TYPE_GLOBAL_AQI = "global air quality index"

# Boost level is a percentage of a room's nominal flow rate; 10-200% is the
# range offered by Renson's own app. The fan entity's percentage (0-100,
# a hard requirement of HA's fan platform) is rescaled onto this range -
# see fan.py's _level_to_percentage/_percentage_to_level.
BOOST_LEVEL_MIN = 10.0
BOOST_LEVEL_MAX = 200.0

# Boost duration is seconds on the wire; the fan entity exposes it as a
# curated preset_mode list rather than exact-minute granularity. Order
# matters: it defines the preset_mode option order shown in the UI.
BOOST_DURATION_PRESETS: dict[str, int] = {
    "15 min": 900,
    "30 min": 1800,
    "1 hour": 3600,
    "2 hours": 7200,
    "3 hours": 10800,
}

# Fallback level/timeout when a room's own default_level/default_timeout is
# missing or out of range - matches the factory default seen on real
# hardware (docs/fixtures/v1-boost-room1.json); 900s is also the "15 min"
# preset above.
BOOST_FALLBACK_LEVEL = 100.0
BOOST_FALLBACK_TIMEOUT = 900
