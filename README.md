# Renson Healthbox 3 for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/TrojanHorsePower/ha-healthbox3.svg)](https://github.com/TrojanHorsePower/ha-healthbox3/releases)
[![License](https://img.shields.io/github/license/TrojanHorsePower/ha-healthbox3.svg)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/TrojanHorsePower/ha-healthbox3/ci.yml?label=CI)](https://github.com/TrojanHorsePower/ha-healthbox3/actions/workflows/ci.yml)
[![HACS Validate](https://img.shields.io/github/actions/workflow/status/TrojanHorsePower/ha-healthbox3/hacs.yml?label=HACS%20Validate)](https://github.com/TrojanHorsePower/ha-healthbox3/actions/workflows/hacs.yml)
[![hassfest](https://img.shields.io/github/actions/workflow/status/TrojanHorsePower/ha-healthbox3/hassfest.yml?label=hassfest)](https://github.com/TrojanHorsePower/ha-healthbox3/actions/workflows/hassfest.yml)

A custom Home Assistant integration for the [Renson Healthbox
3](https://www.renson.net/), a whole-house demand-controlled ventilation
unit. It talks directly to the device over your local network - no cloud
account required.

This is **not** the same product as Home Assistant core's built-in `renson`
integration, which targets the unrelated Renson Endura Delta ventilation
unit and speaks a completely different API. This integration's domain is
`healthbox3` and does not conflict with it.

This is an unofficial, community-maintained integration, not affiliated
with or endorsed by Renson. The icon shown for this integration is a
generic ventilation-fan symbol, not Renson's actual logo or branding -
using their real branding here could wrongly imply official endorsement.

## Features

- Per-room sensors for whichever of temperature, humidity, CO2, VOC and air
  quality index your device's hardware actually reports (varies by room).
- A whole-house air quality index sensor.
- A boost `fan` entity per room (plus one for all rooms at once), with
  percentage/preset controls and a real-level attribute - see
  [Boost control](#boost-control).
- A ventilation profile selector per room (eco/health/intense) - only
  available with an activated API key (see below).
- Automatic reauthentication prompt if your API key stops working, with a
  graceful fallback to basic (v1) functionality in the meantime rather than
  entities going unavailable.

## Use cases

- **Whole-house air quality monitoring** - a dashboard built from the
  per-room temperature/humidity/CO2/VOC/AQI sensors, plus the whole-house
  air quality index sensor for an at-a-glance summary.
- **Targeted, humidity- or CO2-triggered boosting** - automatically boost
  a bathroom's extraction when its humidity sensor spikes, or a bedroom
  when CO2 climbs overnight, instead of relying on a fixed schedule or
  remembering to press boost manually (see [Examples](#examples)).
- **One-press "boost everywhere"** - the `Boost all` fan entity for
  situations like cooking with guests over, without needing to know which
  specific rooms need it.
- **Automated profile switching** - drive each room's eco/health/intense
  profile from presence or time-of-day automations (e.g. `health` during
  the day, `eco` overnight), rather than only through Renson's own app.

## Installation

### HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=TrojanHorsePower&repository=ha-healthbox3&category=integration)

Or manually:

1. In HACS, add this repository as a custom repository (category:
   Integration).
2. Install "Renson Healthbox 3".
3. Restart Home Assistant.

### Manual

Copy the `custom_components/healthbox3` folder from this repository into
your Home Assistant `config/custom_components/` directory, then restart
Home Assistant.

## Configuration

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=healthbox3)

Or manually: **Settings** → **Devices & Services** → **Add Integration** →
search "Renson Healthbox 3".

1. **Device IP address.** Enter the IP address or hostname of your
   Healthbox 3 on your local network. The integration validates this by
   calling the device's basic (v1) API before continuing - there's no
   automatic network discovery yet (see [Known limitations](#known-limitations)).
2. **API key (optional).** You can stop here and use the integration with
   basic functionality, or unlock full sensor data and profile control -
   see below.

### Changing the IP address or API key later

If your Healthbox 3 gets a new IP (e.g. a DHCP reassignment), you don't
need to remove and re-add the integration - use **Settings → Devices &
Services → Renson Healthbox 3 → Reconfigure**. It re-validates
connectivity against the new address and confirms (by serial number) that
it's still the *same* device before updating anything in place, so your
existing entities, history, and automations keep working. The API key
field is left blank by default and only changed if you type a new value -
leaving it blank keeps whatever key is already stored.

### Getting an API key (optional, but recommended)

Out of the box, the Healthbox 3's local API only exposes basic room/valve
data and lets you control boost - this doesn't require a key. To unlock
temperature, humidity, CO2, VOC and air quality sensors, plus ventilation
profile control, you need an API key from Renson:

1. Find your device's **serial number** and **warranty number**. Both are
   shown in the response of a basic API call to the device - if you're
   comfortable with `curl`:
   ```
   curl http://<device-ip>/v1/api/data/current
   ```
   Look for `"serial"` and `"warranty_number"` near the top of the response.
2. Contact Renson support and request a local API key for your device,
   giving them these two numbers.
3. When you receive the key, paste it into the "API key" field during setup
   (or via Reconfigure/Reauthenticate if you're adding it later), and the
   integration will activate it with the device and verify it before
   saving - if activation fails, you'll see an error and can retry.

**Already activated the key yourself** (e.g. by POSTing it to
`/v2/api/api_key` directly, per Renson's docs, before installing this
integration)? You don't need to paste it into the integration at all -
activation is a one-time change on the device itself, not something tied
to a particular client or session. Just leave the "API key" field blank;
the integration checks `/v2/api/api_key/status` on every startup regardless
of whether you gave it a key, so it will detect the already-active key and
enable full sensor/profile functionality automatically.

**Note:** Renson-issued API keys carry a multi-year expiry (e.g. a key
issued in 2026 might read `VALID_UNTIL: 20310706`). The device itself has
no local awareness of this expiry date - it isn't exposed anywhere in the
local API - so there's no way for this integration to warn you ahead of
time. If your profile-select entities and extra sensors quietly disappear
years from now and boost control keeps working, that's very likely an
expired key, not a bug; the integration will have already fallen back to
v1-only functionality and prompted you to reauthenticate with a new key.

## Entities

| Platform | Entity | Notes |
|---|---|---|
| `sensor` | `<room> Temperature` | Only created for rooms with a temperature sensor |
| `sensor` | `<room> Humidity` | Only created for rooms with a humidity sensor |
| `sensor` | `<room> CO2` | Only created for rooms with a CO2 sensor; reads "unavailable" if the device reports it as not-yet-sampled |
| `sensor` | `<room> VOC` | Only created for rooms with a VOC sensor |
| `sensor` | `<room> Air quality index` | Only created for rooms with an air quality sensor; exposes `main_pollutant` when set |
| `sensor` | `Air quality index` | Whole-house AQI; exposes `main_pollutant` and `room` |
| `select` | `<room> Profile` | eco/health/intense - only created with an active API key |
| `fan` | `<room> Boost` | Boost for that room - see "Boost control" below |
| `fan` | `Boost all` | Boost for every room at once, at one shared level/duration - on only when every room currently reports boost enabled |

All entities for a given Healthbox unit are grouped under a single device
(named after the device's own description, e.g. "Healthbox 3.0" - rename it
in the UI if you'd like something more specific, like "Basement
Healthbox").

### Boost control

Boost is modeled as a `fan` entity (per room, plus one "Boost all" for every
room at once) rather than a plain switch, since Home Assistant's fan
platform gets a proper more-info dialog and Tile card - a percentage slider
and a duration picker in one control, instead of three separate rows.

**Turning a boost fan off does not stop ventilation.** The Healthbox always
ventilates every room at a baseline rate determined by its eco/health/intense
profile (the `<room> Profile` select entity, unrelated to boost). "Off" on
a boost fan only means "boost cancelled - back to that normal profile-driven
rate," not "no airflow."

**The percentage slider is rescaled**, not the device's real numbers. The
Healthbox's actual boost level is 10-200% of a room's nominal flow rate, but
Home Assistant's fan platform hard-requires a plain 0-100% domain, so:
- 0% = boost off (`enable: false`) - ventilation continues at the profile rate
- 1-100% = boost on, linearly rescaled onto the device's real 10-200% range

The real, unscaled level (e.g. `"150%"`) is always shown as a `level`
attribute on the entity, so you can see what the device actually received
even though the slider itself reads a clean 0-100.

**Duration is a preset picker**, not exact minutes: `5 min`, `10 min`,
`15 min`, `30 min`, `45 min`, `1 hour`, `2 hours`, `4 hours` - a fixed list,
not an arbitrary custom duration (5 minutes is also the shortest boost
Renson's own app offers). Pick one from the fan's preset dropdown; it's
converted to the device's native seconds-based timeout at the boundary.

"Boost all" uses one shared percentage/preset applied to every room
simultaneously when triggered, matching Renson's own app - it is *not*
"trigger every room at its own settings."

**Confirmed on real hardware:** changing the percentage or preset while a
boost fan is already on does not adjust it smoothly in place - it restarts
the boost's countdown from the new full duration. For example: a boost with
279 seconds left, nudged to a new percentage, jumps back to a fresh 900
seconds (or whatever duration is currently set), not 279. This is a device
behavior, not a bug in this integration. Watch the `remaining` attribute
after adjusting the slider mid-boost and you'll see it jump back up - that's
expected. The integration logs an info-level message each time this happens
("Restarting active boost for room(s) ...").

## Examples

Entity IDs below assume the device's default name ("Healthbox 3.0" -
adjust the `healthbox_3_0` prefix if you've renamed the device or its
entities).

**Boost a room automatically when its humidity spikes** (e.g. a shower):

```yaml
alias: "Boost bathroom when humidity is high"
triggers:
  - trigger: numeric_state
    entity_id: sensor.healthbox_3_0_bathroom_humidity
    above: 70
actions:
  - action: fan.turn_on
    target:
      entity_id: fan.healthbox_3_0_bathroom_boost
    data:
      percentage: 100
      preset_mode: "30 min"
```

**Boost every room at once when the whole-house air quality index gets
bad** - a real use for `Boost all`'s single shared level/duration rather
than triggering each room separately:

```yaml
alias: "Boost all rooms on poor whole-house air quality"
triggers:
  - trigger: numeric_state
    entity_id: sensor.healthbox_3_0_air_quality_index
    above: 60
actions:
  - action: fan.turn_on
    target:
      entity_id: fan.healthbox_3_0_boost_all
    data:
      percentage: 75
      preset_mode: "1 hour"
```

**Switch a room's ventilation profile by time of day** (requires an
active API key, since profile control needs one - see
[Getting an API key](#getting-an-api-key-optional-but-recommended)):

```yaml
alias: "Bedroom profile: health by day, eco overnight"
triggers:
  - trigger: time
    at: "07:00:00"
  - trigger: time
    at: "22:00:00"
actions:
  - action: select.select_option
    target:
      entity_id: select.healthbox_3_0_bedroom_profile
    data:
      option: "{{ 'health' if trigger.now.hour == 7 else 'eco' }}"
```

## Data updates

The integration polls the device every 30 seconds via a
`DataUpdateCoordinator`: `/v2/api/data/current` if an API key is active,
otherwise `/v1/api/data/current`. Boost status is fetched per room on the
same cycle (it's a separate endpoint from the main data call). If the
device goes offline, affected entities go unavailable cleanly and recover
automatically once it's reachable again - no restart required.

## Known limitations

- **No automatic network discovery.** The device supports a UDP discovery
  broadcast, but broadcast delivery is unreliable on many networks (AP
  client isolation, IGMP snooping, and VLAN segmentation are all common
  culprits) and didn't work at all during development. You must enter the
  device's IP address manually. A future release may add unicast-based
  discovery once you've entered an IP, to confirm device identity during
  setup.
- **Without an API key**, only basic room/valve data and boost control are
  available - no temperature/humidity/CO2/VOC/air-quality sensors and no
  ventilation profile control. This is a limitation of the device's v1 API,
  not of this integration.
- **API keys expire** after a multi-year period set by Renson, with no way
  for the device (or this integration) to detect the expiry date in
  advance. See [Getting an API key](#getting-an-api-key-optional-but-recommended)
  above.

## Troubleshooting

**Setup fails with "Failed to connect to the device."** Confirm the IP is
reachable from Home Assistant (not just from your phone/laptop - a VLAN or
firewall rule can block one but not the other), and that nothing else
(e.g. the Renson app open elsewhere) is blocking the connection. This
integration only talks over your local network; it never needs internet
access to the device itself.

**Setup or Reconfigure fails with "The API key was rejected."** Double
check the key against the device's serial and warranty number (both
retrievable via `curl http://<device-ip>/v1/api/data/current` - see
[Getting an API key](#getting-an-api-key-optional-but-recommended)). If it
was working before and suddenly isn't, see the expiry note above - keys
aren't renewable in place, you'd need a new one from Renson.

**A room's CO2 sensor shows "unavailable."** Confirmed on real hardware:
some CO2 sensors report an empty reading (not zero, genuinely no data)
until they've warmed up after a device restart. This shows as
`unavailable`, not a stale/wrong value, and should resolve on its own once
the sensor starts reporting.

**A boost fan's `remaining` attribute jumped back up after I only changed
the level or duration.** Not a bug - confirmed on real hardware, changing
a boost's percentage or preset while it's already running restarts its
countdown from the new full duration rather than adjusting smoothly in
place. See [Boost control](#boost-control) for the full explanation.

**Entities disappeared after previously working (temperature/humidity/CO2/
VOC/AQI sensors and the profile select specifically).** Check
Settings → Devices & Services for a "reauthenticate" prompt on this
integration - this is the expected result of an API key expiring or being
revoked, not an error. Boost control keeps working in the meantime (see
[Known limitations](#known-limitations)); reauthenticating with a new key
restores the rest.

## Development

Tests use
[pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component)
and real JSON fixtures captured from a physical device (see
`docs/fixtures/`):

```
pip install -r requirements_test.txt
pytest
```

See `custom_components/healthbox3/quality_scale.yaml` for this
integration's progress against the Home Assistant [Integration Quality
Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/).

See [CONTRIBUTING.md](CONTRIBUTING.md) for the versioning scheme and
release process, and [CHANGELOG.md](CHANGELOG.md) for release history.
