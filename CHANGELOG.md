# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

  All five require an active API key, the same as the ventilation profile
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

[Unreleased]: https://github.com/TrojanHorsePower/ha-healthbox3/compare/0.1.4...HEAD
[0.1.4]: https://github.com/TrojanHorsePower/ha-healthbox3/compare/0.1.3...0.1.4
[0.1.3]: https://github.com/TrojanHorsePower/ha-healthbox3/compare/0.1.2...0.1.3
[0.1.2]: https://github.com/TrojanHorsePower/ha-healthbox3/compare/0.1.1...0.1.2
[0.1.1]: https://github.com/TrojanHorsePower/ha-healthbox3/compare/0.1.0...0.1.1
[0.1.0]: https://github.com/TrojanHorsePower/ha-healthbox3/releases/tag/0.1.0
