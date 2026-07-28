# Alpha 5 audit remediation matrix

MIA 4.0.0 alpha 5 is a focused remediation release based on a clean-sandbox
audit of the published alpha 4 ZIP and wheel. This record maps each reported
issue to the implemented behavior and regression coverage.

| Audit finding | Alpha 5 behavior | Regression coverage |
|---|---|---|
| Python `httpx` mistaken for ProjectDiscovery httpx | MIA prefers its managed path and requires a tool-specific version signature. Wrong commands remain visible as identity mismatches but are not marked ready. | Plugin detection, package inventory, multiline version output, wrong-PATH fixture. |
| Intelligence X raw evidence retained preview/content | Successful raw responses use a metadata allow-list; provider error bodies are redacted. | Nested preview/content/raw fixture and error-body fixture. |
| SQLite connections leaked | Scan, cache, knowledge, and case connection context managers commit/rollback and always close. | Closed-connection assertions and suite-wide `ResourceWarning` failure mode. |
| Logging handlers leaked | Reconfiguration removes and closes old handlers before adding replacements. | Old file-handler stream closure assertion. |
| Invalid plugin IDs produced tracebacks | CLI catches manifest validation errors and prints a concise error with exit code 2. | Invalid scaffold ID CLI test. |
| Unknown API services entered configuration | Every credential and enable/disable command validates against the supported service registry before changing files or keyring state. | Unknown-service CLI test with unchanged config. |
| No CLI path back to local assistant | `mia assistant configure local --default` is supported; local rejects irrelevant model/endpoint options. | Provider-switch configuration test. |
| Failed investigation left an empty case | Root plugin selection is validated before creation; a newly created workspace is removed if the root scan cannot complete successfully. | Failed-root rollback test. |
| Failed-only classic scan exited 0 | Default exit is 1 when zero plugins succeed; `--allow-empty` is an explicit override. | Failed scan and override CLI tests. |
| Blank `--case` created a new case | Empty or whitespace-only case identifiers are rejected. | Blank-case CLI test. |
| Invalid package manager sometimes escaped validation | Overrides and environment values are normalized and validated during manager construction. | Invalid-manager constructor/CLI coverage. |
| Progress said “Updateing” | Progress uses the correct `Updating` gerund. | Package command output tests. |
| Updating an absent package was ambiguous | Result explicitly says the tool is installed because it was absent. | Absent-update result test. |
| Findomain Cargo recipe failed | Official architecture-specific prebuilt release ZIP. | Catalog assertion and executable ZIP fixture install. |
| dnstwist full extras failed to compile | Portable base PyPI package; compiled optional extras are not forced. | Catalog assertion and dry-run command test. |
| WhatWeb had no Homebrew formula | Official Git checkout with explicit Ruby wrapper. | Git/runtime wrapper fixture. |
| PhoneInfoga `go install` lacked embedded web assets | Official architecture-specific release tarball. | Catalog assertion and executable tar fixture install. |
| VirusTotal CLI root Go module was not a command | Installs `github.com/VirusTotal/vt-cli/vt@latest`. | Catalog assertion and dry-run command test. |
| cloud_enum expected a removed requirements file | Current `uv sync --project` layout and project console command. | uv-project fixture matching current repository layout. |

## Additional hardening

Release archive extraction rejects path traversal, ZIP symlinks, tar symlinks,
hard links, and device entries. The final source suite is also run with
`ResourceWarning` promoted to an error so future connection/handler regressions
fail CI rather than appearing only during shutdown.

This document describes implementation and tests, not a claim that every remote
registry, release asset, API, or Linux repository will remain unchanged.
