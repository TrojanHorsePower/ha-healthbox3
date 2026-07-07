# Project notes

## Official API documentation

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
