# Contributing

## Development

See the [README](README.md#development) for running the test suite locally.

## Translations

`custom_components/healthbox3/translations/` has `en.json` (source of
truth, kept byte-identical to `strings.json` - see
`tests/test_strings.py`), `nl.json` (reviewed by a native Dutch
speaker), and `fr.json` (best-effort only, **not yet reviewed by a
native French speaker** - treat any French PR review with extra
scrutiny until someone fluent has checked it). Adding a new
translatable string requires adding it to all four files with the same
key structure (enforced by `tests/test_strings.py`), even if you can
only provide the English text - a native speaker can fill in the rest
later, an inconsistent key structure can't be caught automatically once
it ships.

## Versioning

This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(`MAJOR.MINOR.PATCH`). For an integration, "breaking" means the entity/config
surface a user actually depends on - entity IDs, unique IDs, config entry
data, available services - not internal refactors.

While the version stays `0.x`, breaking changes to that surface are allowed
in a `MINOR` bump (per the SemVer spec: "the public API SHOULD NOT be
considered stable" before `1.0.0`). `MAJOR` bumps are reserved for once the
entity surface is considered stable enough to promise compatibility.

This is separate from `hacs.json`'s `"homeassistant"` field, which tracks
the *minimum Home Assistant Core version* required (Core itself uses
calendar versioning, e.g. `2026.7.0`) - not this integration's own version.

## Keeping the changelog current

Add a [`CHANGELOG.md`](CHANGELOG.md) entry under `[Unreleased]` as part of
finishing any user-facing unit of work - not as a separate cleanup task
done later. Internal-only changes (test coverage, quality-scale
bookkeeping, CI tweaks) don't need an entry; anything a user would
actually notice does.

## Release process

1. Move the relevant [`CHANGELOG.md`](CHANGELOG.md) entries from
   `[Unreleased]` into a new `## [X.Y.Z] - YYYY-MM-DD` section, and add the
   comparison link at the bottom of the file.
2. Bump `"version"` in `custom_components/healthbox3/manifest.json` to
   match `X.Y.Z` exactly.
3. Commit both changes.
4. Tag that commit `X.Y.Z` (**no** `v` prefix - it must match
   `manifest.json`'s version string exactly, which HACS validates) and
   push the tag.
5. Create a GitHub Release from that tag. Paste the new CHANGELOG.md
   section as the release body. Do **not** mark it as a pre-release
   (reserve that for actual beta/testing builds ahead of a version bump,
   e.g. `X.Y.Z-beta.1`), even while the version is `0.x`.

HACS reads GitHub Releases (not just raw tags) to show version history and
release notes to users when they check for updates.
