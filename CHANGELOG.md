# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.3] - 2026-07-14

### Added

- New `AQI level` sensors (per-room and whole-house), showing the same
  qualification band (Very good/Good/Moderate/Poor/Very poor) already
  available as the numeric AQI sensors' `qualification` attribute, but as
  their own primary, dashboard-friendly state - the numeric sensors are
  unchanged, so anything already graphing AQI history keeps working. See
  [Known limitations](README.md#known-limitations) for the same
  comparability caveats that apply to the `qualification` attribute.

## [0.3.2] - 2026-07-13

### Added

- Air quality index sensors (per-room and whole-house) now include a
  `qualification` attribute (Very good/Good/Moderate/Poor/Very poor)
  alongside the existing raw numeric value, per Renson's own official
  guidance on how to interpret the index. See
  [Known limitations](README.md#known-limitations) for two comparability
  caveats Renson also raised: values aren't strictly comparable across
  rooms with different sensor types, and the whole-house value isn't
  necessarily equal to whichever room its attributes point at.

## [0.3.1] - 2026-07-10

### Added

- Device-reported errors now include a short `category` label (e.g.
  "Power", "Fan and main PCB") alongside the existing code and
  description, on both the repair issue and the `Device errors` sensor.
  Best-effort only - see [Known limitations](README.md#known-limitations),
  since it's sourced from Renson's public error-code index rather than
  the local API and hasn't been confirmed against a real device error.

## [0.3.0] - 2026-07-09

### ⚠️ Breaking changes

- **The demand control switch's on/off meaning is now correct but
  inverted from 0.2.0's buggy behavior.** If you have automations or
  dashboards referencing this switch, check anything depending on its
  state - this is the one that fails silently rather than obviously.
- **The per-room CO2 threshold number now represents a different value
  than before** (the device's `maximum` field, not `minimum`) - if you
  have automations setting or reading this number, its meaning and
  typical value have both changed.
- **The `Breeze` switch has been removed.** Breeze can no longer be
  turned on/off from Home Assistant, only its trigger temperature - use
  the Renson app or the device itself for on/off.

### Added

- Automatic reconnection after an IP change can now also be triggered by
  Home Assistant's own passive DHCP discovery, alongside the existing
  active network search - including for a device that's never connected
  successfully even once, which the active search alone couldn't help
  with.
- Diagnostic firmware version sensor - requires an active API key.
- Device-reported errors now create a Home Assistant repair issue
  (Settings > Repairs), plus a diagnostic sensor with the current error
  count and most recent error's details - requires an active API key.
  Clearing an error still requires the Renson app or the device itself;
  see [Known limitations](README.md#known-limitations).
- Dutch translation, reviewed by a native speaker. French translation,
  best-effort only and not yet reviewed by a native speaker - see
  [Translations](README.md#translations).

### Changed

- Switched the integration's icon and logo to Renson's own Healthbox 3
  branding, replacing the placeholder generic ventilation-fan icon used
  since 0.1.0.

### Removed

- The `Breeze` switch, added in 0.2.0. Neither Renson's mobile app nor its
  own device web UI ever exposes an on/off control for Breeze (only its
  trigger temperature, which the `Breeze temperature` number entity still
  controls) - the same restraint this integration already applies to
  `fire_protect` and Qmin/Qnom/Offset. Use the Renson app or the device
  itself to turn Breeze on or off.

### Fixed

- **The per-room CO2 threshold number was reading and writing the wrong
  field.** It showed and set `minimum`, but confirmed against a fresh
  device capture cross-referenced with the Renson app, the app displays
  and edits `maximum` - so the value shown/set in Home Assistant since
  0.2.0 didn't match what the app showed, and editing it moved the wrong
  end of the underlying range. Now reads/writes `maximum`, deriving
  `minimum` to preserve the same span as before.
- **The demand control switch was inverted.** It showed ON/OFF as the
  raw `program.enable` device field, but confirmed against a fresh
  device capture cross-referenced with the Renson app, `program.enable`
  tracks the clock/schedule fallback being active - the opposite of
  "demand control is active". The switch now presents and writes the
  negation of that field, so its state matches the Renson app.

## [0.2.0] - 2026-07-09

### Added

- Demand control switch, to toggle automatic (sensor-driven) ventilation
  on or off.
- Minimum ventilation level number, setting the device-wide floor
  ventilation percentage.
- Breeze switch and temperature number, for temperature-triggered night
  cooling.
- Per-room CO2 threshold number, only created for rooms that support
  CO2-triggered demand control.
- Silent schedule switch, reduction number, and start/stop time entities,
  for the reduced-noise schedule.
- Whole-house ventilation level sensor, showing the current aggregate
  ventilation level as a percentage.

  All six require an active API key, the same as the ventilation profile
  selector.

### Changed

- The error messages for "a room was removed from the device while an
  action was in progress" and "boost all partially failed" are now
  translatable into other languages if a translation is ever added
  (still English-only for now, since only an English translation
  exists). Both messages also gained a trailing period.
- Every sensor, the ventilation profile selector, and both boost fan
  entities now show a specific icon instead of a generic fallback -
  including the profile selector showing a different icon per profile
  (eco/health/intense), and both boost fans showing a distinct icon
  when off vs on.

## [0.1.4] - 2026-07-07

### Added

- Per-room airflow sensor, showing current airflow as a percentage of that
  room's rated (nominal) flow. Only created for rooms that report the
  underlying data. Not a 0-100 bounded percentage - boost can drive
  airflow well past nominal, so values can run from roughly 10% up to
  200%.
- Automatic, silent reconnection if a Healthbox 3's IP address changes
  after setup (e.g. a DHCP lease renewal) - no notification, no action
  needed. Only applies once an entry has connected successfully at least
  once; see README "Known limitations" for the one case it doesn't cover.

## [0.1.3] - 2026-07-07

### Added

- Automatic network discovery during setup: the config flow now tries a UDP
  broadcast to find your Healthbox 3 before asking for an IP address.
  Exactly one device found is offered for confirmation; multiple found are
  offered as a selection list; devices already configured are excluded
  from either. If nothing responds within a few seconds - broadcast
  delivery is unreliable on some networks (AP client isolation, IGMP
  snooping, VLAN segmentation) - setup falls through to manual IP entry
  with no error shown, exactly as before.
- After a manually-entered IP passes connectivity validation, setup makes
  a best-effort attempt to also show a confirmation screen with the
  device's MAC address and firmware version. If that probe doesn't
  respond, setup continues straight on exactly as before - the device was
  already verified reachable, so this is purely extra detail, never a
  requirement.

## [0.1.2] - 2026-07-07

### Changed

- Expanded the boost duration preset list from 5 options to 8: `5 min`,
  `10 min`, `15 min`, `30 min`, `45 min`, `1 hour`, `2 hours`, `4 hours`
  (previously `15 min`/`30 min`/`1 hour`/`2 hours`/`3 hours`). Still a
  fixed preset list, not an arbitrary custom duration - 5 minutes is
  also the shortest boost Renson's own app offers.

## [0.1.1] - 2026-07-06

### Changed

- No functional changes. Added hacs/action and hassfest validation
  workflows required for HACS default-store submission.

## [0.1.0] - 2026-07-06

### Added

- Config flow with manual IP entry, v1 connectivity validation, optional
  API key activation with verification, automatic detection of a key
  activated directly against the device (outside this integration), and
  a reauthentication flow.
- Reconfigure flow (Settings → Devices & Services → Reconfigure) for
  updating the device's IP address and/or API key in place, without
  losing entity history from a remove-and-re-add. Re-validates
  connectivity and confirms (by serial number) it's still the same
  device before updating anything; a blank API key field leaves the
  currently stored key untouched.
- `DataUpdateCoordinator` polling `/v1/api/data/current` or
  `/v2/api/data/current` depending on API key status, with automatic
  graceful fallback to v1-only functionality (rather than repeated
  errors) if a previously valid key stops working.
- Per-room sensors for temperature, humidity, CO2, VOC, and air quality
  index, created dynamically to match whatever sensors a given room's
  hardware actually reports, plus a whole-house air quality index sensor.
- Boost control as `fan` entities - one per room plus one device-level
  "Boost all" - with percentage and preset-mode duration mapped onto the
  device's real level/duration ranges, fully automatable via standard
  Home Assistant fan services.
- Ventilation profile selection per room (eco/health/intense), available
  once an API key is active.
- Diagnostics support, with serial numbers, warranty numbers, API keys,
  host/IP, and other identifying fields redacted.
- Local brand icons (a generic ventilation symbol, not Renson's actual
  branding).
- MIT license.
- Automated tests (config flow, coordinator, entities, diagnostics, and
  real Home Assistant automation-engine dispatch) and CI running them on
  every push and pull request.
- README "Use cases", "Examples", and "Troubleshooting" sections.

[Unreleased]: https://github.com/TrojanHorsePower/ha-healthbox3/compare/0.3.3...HEAD
[0.3.3]: https://github.com/TrojanHorsePower/ha-healthbox3/compare/0.3.2...0.3.3
[0.3.2]: https://github.com/TrojanHorsePower/ha-healthbox3/compare/0.3.1...0.3.2
[0.3.1]: https://github.com/TrojanHorsePower/ha-healthbox3/compare/0.3.0...0.3.1
[0.3.0]: https://github.com/TrojanHorsePower/ha-healthbox3/compare/0.2.0...0.3.0
[0.2.0]: https://github.com/TrojanHorsePower/ha-healthbox3/compare/0.1.4...0.2.0
[0.1.4]: https://github.com/TrojanHorsePower/ha-healthbox3/compare/0.1.3...0.1.4
[0.1.3]: https://github.com/TrojanHorsePower/ha-healthbox3/compare/0.1.2...0.1.3
[0.1.2]: https://github.com/TrojanHorsePower/ha-healthbox3/compare/0.1.1...0.1.2
[0.1.1]: https://github.com/TrojanHorsePower/ha-healthbox3/compare/0.1.0...0.1.1
[0.1.0]: https://github.com/TrojanHorsePower/ha-healthbox3/releases/tag/0.1.0
