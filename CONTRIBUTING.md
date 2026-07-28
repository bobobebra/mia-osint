# Contributing to MIA

Thank you for helping improve an early, vibe-coded alpha. Contributions are
welcome, but safety, reproducibility, and honest uncertainty take priority over
feature count.

## Before contributing

Read:

- `AI_DISCLOSURE.md`
- `CODE_OF_CONDUCT.md`
- `SECURITY.md`
- `docs/ARCHITECTURE.md`
- `docs/RESPONSIBLE_USE.md`
- `docs/PACKAGE_MANAGER.md`

Do not include real targets, private reports, credentials, API tokens, personal
data, or proprietary datasets in issues, commits, fixtures, or pull requests.

## Development setup

```console
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
ruff check src tests
pytest
```

Optional local checks:

```console
ruff format --check src tests
mypy src/mia
bash -n install.sh uninstall.sh
python -m build
```

## Pull-request expectations

- Explain the problem and the behavior change.
- Add or update tests.
- Use sanitized, minimal parser fixtures.
- Document new configuration and report fields.
- Preserve raw evidence and distinguish failure from a positive finding.
- State which distributions/tool versions were actually tested.
- Disclose meaningful AI assistance in the pull-request description.
- Confirm that submitted code and text are license-compatible.

## Plugin rules

Plugins should contain dependency detection, command construction, parsing, and
metadata—not report-specific presentation logic. Commands must be argument
arrays and must not invoke a shell with user-controlled text.

Do not add:

- credential guessing or stuffing;
- authentication bypass;
- session theft;
- exploit or malware execution;
- covert persistence;
- rate-limit or platform-control evasion;
- features designed for harassment, stalking, or mass targeting.


## Package catalog contributions

Catalog additions require a canonical upstream source, license review, explicit
`local`/`passive`/`mixed` classification, honest `full`/`raw`/`managed-only`
integration level, setup/API/maintenance warnings, and dry-run tests. Recipes
must use an existing declarative install kind; arbitrary shell snippets are not
accepted.

Do not claim a tool is integrated merely because it can be installed. New scan
adapters require sanitized fixtures, positive and negative parser tests, failure
semantics, and documentation of the upstream versions tested.

## Distro installer changes

Installer changes require:

- `bash -n install.sh uninstall.sh`;
- updated dry-run tests;
- documentation of package names;
- an exact distribution/release/architecture test report when claiming support;
- no `sudo pip` or system-Python mutation.

## Review standard

AI-generated or human-written code is reviewed by the same standard. A passing
test suite is necessary but not sufficient; reviewers may request simpler code,
additional negative tests, source citations, or removal of unsupported claims.
