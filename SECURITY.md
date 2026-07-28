# Security policy

## Supported versions

MIA is pre-release software. Only the newest tagged alpha receives best-effort
security fixes. There is no long-term-support branch or production-readiness
claim.

## Reporting a vulnerability

Do not open a public issue for command execution, path traversal, report
injection, sensitive-data exposure, package-installation compromise, secret
leakage, unsafe uninstall behavior, or another user's safety.

Use GitHub private vulnerability reporting when enabled. Otherwise contact a
maintainer privately through their GitHub profile and share only a sanitized,
minimum reproduction. Never include real investigation data, reports, API keys,
or access tokens.

A useful report includes:

- affected MIA version and commit;
- OS, architecture, and package manager;
- exact sanitized reproduction;
- expected and observed behavior;
- impact and reachable trust boundary;
- whether the issue is in MIA, a catalog recipe, or an upstream project;
- suggested mitigation where known.

Volunteer response times are not guaranteed. Avoid publishing exploit details
until a fix or coordinated advisory is available.

## Scan execution boundary

MIA uses argument-array subprocess execution rather than a shell, bounds raw
capture, applies timeouts, terminates process groups, and escapes report HTML.
These protections do not sandbox executables. A configured or installed tool can
read files, inspect environment variables, use the network, modify user-owned
data, or execute its own dependencies with the current user's permissions.

Do not run MIA or optional tools as root.

## Package-manager boundary

`mia pkg` installs third-party code from package registries, source repositories,
and host package managers. Isolated environments reduce dependency conflicts;
they do not establish trust.

Current limitations include:

- moving versions and `@latest` recipes;
- no general signature or maintainer-identity verification;
- no reproducible-build guarantee;
- no transitive dependency audit;
- no sandbox around build or install scripts;
- catalog license/maintenance metadata can become stale;
- host package installation may require `sudo`.

The catalog is declarative and cannot contain arbitrary shell snippets, and MIA
records its managed roots for targeted uninstall. Still, review recipes and
upstream changes before installation. Use `--dry-run` and an unprivileged test
account first.

System packages are never removed by ordinary `mia pkg uninstall`; explicit
`--remove-system-packages` is required because other software may depend on
them.

## Secrets

MIA supports environment variables and the operating-system keyring for passive
API and assistant credentials. Keys are not written to YAML, reports, package
state, or subprocess command lines. An explicit `--insecure-file` fallback writes
a mode-0600 plaintext file for systems without a usable keyring; it remains
plaintext and should be avoided when possible. Child processes may still inherit
unrelated environment variables. Use scoped, revocable tokens and avoid shell
history, screenshots, logs, raw reports, and public issues containing secrets.

Remote AI use sends bounded normalized evidence to the configured provider. It
can still contain personal information. Raw files are not sent by the current
implementation.

## Sensitive data

Case databases, the shared knowledge index, cache entries, reports, raw output,
notes, attachments, screenshots, logs, API responses, and package metadata can
contain personal information or investigation context. Apply restrictive permissions,
minimal retention, encryption where appropriate, lawful processing, and
redaction before sharing.

See [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md).
