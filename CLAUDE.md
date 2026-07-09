# Project notes

Standing conventions this project actually follows, kept here so future
sessions don't need them re-explained. This is a living reference, not a
full codebase walkthrough - only genuinely recurring practices belong
here, not one-off decisions.

## Plan before implementing

For non-trivial features, propose a plan - including explicit unknowns
and judgment calls, not just the obvious parts - before writing any
code, and wait for confirmation. This is what caught most of this
session's real design issues before they became code: the
discovery-confirm re-validation guard, the already-configured discovery
filter, and the relocate/reauth mutual-exclusivity check all came out of
this step, not from review after the fact.

## Core invariant: never trust discovered identity

Any device identity learned from something other than a direct,
synchronous HTTP call to the device (a UDP broadcast reply, a unicast
discovery probe, a serial match used to trigger a relocate) must be
re-confirmed via a real HTTP call before it's used to gate anything -
`unique_id`, entry creation, or an existing entry's mutation. This
recurs three times: manual IP entry's post-validation unicast enrichment
probe, the discovery-confirm step's re-validation, and the relocate
flow's `async_get_v1_data_current()` call before ever touching an
existing entry's host. A broadcast/unicast reply is good enough to
*find* a candidate device, never good enough to *act* on directly.

## Release process

1. Bump `custom_components/healthbox3/manifest.json`'s `"version"`.
2. Move whatever's currently under `CHANGELOG.md`'s `## [Unreleased]`
   into a new `## [X.Y.Z] - <date>` section (same format as every prior
   release), leaving `[Unreleased]` empty again. Update the compare-link
   footer at the bottom of the file too (`[Unreleased]: .../compare/X.Y.Z...HEAD`,
   plus a new `[X.Y.Z]: .../compare/<prev>...X.Y.Z` line).
3. Commit both files together as one commit: `"Release X.Y.Z: <short
   description of what's in it>"` (e.g. `"Release 0.1.4: airflow sensor
   and automatic discovery-based reconnection"`).
4. Tag that commit `X.Y.Z` - **no `v` prefix** (`0.1.4`, not `v0.1.4`).
5. Push the commit and the tag, then confirm CI, HACS Validate, Validate
   with hassfest, and mypy all show green **on that exact tagged commit**
   (not just "the workflows pass somewhere") before considering the
   release done.
6. GitHub Release: title is just the version number, body is pulled
   verbatim from that version's `CHANGELOG.md` section (no heading/date
   line), tagged against the already-pushed tag - never create a new tag
   for this step.

## CHANGELOG conventions

- Only genuinely user-facing changes get an entry. CI/tooling-only
  changes (e.g. adding a validation workflow) do **not** - this was
  gotten wrong once (an entry added for the hacs/action + hassfest
  workflows) and explicitly corrected; the rule is now applied
  proactively, not just after a correction.
- Entries describe user-visible behavior, not implementation (no
  internal function/class names) - write them as if for someone deciding
  whether to update, not someone reading the diff.

## Commit splitting

Split commits by what can be committed independently without leaving an
intermediate commit in a broken state - e.g. a feature and its own tests
land together (tests are part of making the feature real, not a
separate unit), but docs-only follow-ups (README/CHANGELOG-only changes)
get their own commit.

The exception: when a docs or test-infra change only exists *because* a
feature needs it, it's bundled into the feature's own commit rather than
split out. Example: `_patch_client`'s missing `autospec=True` in
`tests/test_config_flow.py` only became a real bug once the unicast
probe enrichment feature added a new async method the mock needed to
support - that fix shipped in the same commit as the feature, not as a
separate "test fix" commit.

When a change is self-contained enough that this question doesn't come
up (most single-purpose fixes), it's just one commit - don't manufacture
a split for its own sake.

## Docs-staleness check (do this before declaring a feature done)

Grep `README.md` and `CHANGELOG.md` (and `quality_scale.yaml`, which has
the same failure mode) for future/planned/todo-style language describing
the thing just built - phrases like "a future release may...", "not yet
implemented", "todo". Fix it as part of finishing the feature, not as a
follow-up left for someone else to notice. This project has had this
happen more than once (a stale "future release may add unicast
discovery" note in README survived past the release that actually shipped
it) before this became a standing check.

This also applies one level deeper than the obvious spot: when a feature
changes behavior that's described *elsewhere* too (not just its own
"known limitations" bullet), check those other descriptions too - e.g.
adding automatic reconnection-on-IP-change required updating the
*existing* "Changing the IP address... later" section, not just adding a
new bullet, because that section's manual-Reconfigure-only framing had
become incomplete, not just outdated.

## Quality Scale hygiene

`quality_scale.yaml` entries flip from `todo` to `done` only once the
rule is actually implemented and tested - never preemptively. Every
`done` entry gets a comment explaining the mechanism and, where
relevant, any deliberate scope gap (cross-referenced to README's "Known
limitations" when the gap is user-visible, not left implicit). The
`test-coverage` entry's test count/percentage gets refreshed whenever
it's touched nearby, so it doesn't quietly drift out of date.

## Verification discipline

Before asserting how a library, API, or Home Assistant internal behaves,
check the actual source or official docs rather than reasoning from
memory or analogy - and say what was checked and how, not just the
conclusion. This project has caught real mistakes this way, not just
theoretical ones:

- Confirmed `ConfigEntry.async_start_reauth` is a sync `@callback`, not
  an awaitable, by hitting a real `TypeError` in a test run - fixed a
  bug memory/assumption would have kept getting wrong.
- Confirmed (via `inspect.getsource` on the installed `homeassistant`
  package) that `_abort_if_unique_id_configured(updates=...)` both
  updates `entry.data` and schedules a reload, and that an aborted flow
  is removed from `FlowManager._progress` synchronously within the same
  step - before claiming the discovery-based reconnect feature was
  "silent, no notification shown."
  Also confirmed (checking the *installed* HA package's `create_datagram_endpoint`
  source) exact `allow_broadcast`/`local_addr` socket behavior before
  writing the broadcast-discovery UDP code.
- Confirmed which `SensorDeviceClass` members even accept a `%` unit,
  and read their actual docstrings, before concluding none fit an
  unbounded-past-100 airflow percentage (rather than assuming by analogy
  to `HUMIDITY`/`AQI`).
- Confirmed the exact `Healthbox3Error` exception hierarchy in `api.py`,
  and specifically that `_async_udp_discover` wraps
  `asyncio.TimeoutError` into `Healthbox3ConnectionError` *before* it can
  ever reach a caller, before writing an except-clause or a test that
  simulated "no reply."

A scratch venv (in the session scratchpad dir, never inside the repo) with
the real `homeassistant` package installed is how HA internals get
verified this way - `pip install homeassistant`, then
`inspect.getsource`/`grep` the installed package directly.

## Autouse fixtures for new background calls

Adding a new unconditional async call into an existing flow/coordinator
method (e.g. wiring in broadcast discovery, or the relocate probe)
breaks every pre-existing test that exercises that code path, because
the test harness hard-blocks real sockets - this has happened twice.
Fix: add an autouse fixture in `tests/conftest.py` that patches the new
call to a safe default (e.g. `AsyncMock(return_value=[])`), so existing
tests are unaffected by default; individual tests that care about the
new behavior override the fixture's `return_value`/`side_effect`
explicitly.

## Push discipline

Commit locally freely, but **never push to origin without an explicit
instruction to push that specific commit** - local commits are for
review first. This applies even when a whole multi-step task (e.g. "cut
a release") was pre-authorized; the push step still gets called out and
waited on separately.

## Local API documentation

The Renson-issued API PDFs for the Healthbox 3.0 are kept locally for
reference but are gitignored (`docs/**/*.pdf` in `.gitignore`) since
they're copyrighted vendor docs, not ours to redistribute:

- `docs/fixtures/SOF_Healthbox 3.0 local API_en.pdf`
- `docs/fixtures/SOF_Healthbox 3.0 third party API_en.pdf`

They are untracked, not missing. Check these directly for any question
about documented API behavior (endpoints, field names/units, valid
ranges, undocumented-vs-documented fields, etc.) rather than assuming the
docs don't exist because `git ls-files`/GitHub shows nothing under
`docs/`.

## Vendor reference JavaScript

`docs/vendor-reference/` (gitignored, not committed) contains JavaScript
from the Healthbox 3's own local web UI, covering several undocumented
endpoints beyond what the two official PDFs describe (demand control,
breeze, silent settings, per-room CO2 threshold, and others). When
working on features not covered by the two PDFs in `docs/`, check this
folder first before assuming something isn't possible via the local API.
Treat this the same as the vendor PDFs: reference material to inform
independently-written code, never quote large verbatim chunks into
commits/comments, never redistribute.
