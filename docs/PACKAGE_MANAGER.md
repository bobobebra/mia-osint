# Optional OSINT package manager

MIA includes an early-alpha package manager for optional third-party command-line
OSINT tools. It is a convenience layer, not an app store, sandbox, trust system,
or security endorsement.

```console
mia pkg groups
mia pkg list
mia pkg info subfinder
mia pkg install --group username
mia pkg uninstall blackbird
mia pkg update --all
mia pkg doctor
```

## Important distinction: installation versus integration

Every catalog entry has one of three integration levels:

| Level | Meaning |
|---|---|
| `full` | MIA has a structured adapter and normalizes supported output into reports. |
| `raw` | MIA can run the tool and extract a conservative subset of output; raw files remain authoritative. |
| `managed-only` | MIA can install/remove/update the command, but scans do not invoke it automatically yet. |

Installing a `managed-only` tool does not silently add it to MIA reports. Run it
directly until a tested parser is added.

## Catalog safety labels

| Risk | Meaning |
|---|---|
| `local` | Works only on local files or values. |
| `passive` | Primarily queries public datasets, APIs, archives, or normal service endpoints. It still creates network traffic. |
| `mixed` | May make broader direct DNS, TLS, HTTP, cloud, or fingerprinting requests. Use only with authorization. |

`mia pkg install --all` intentionally excludes `mixed` entries. Any explicit tool or group that contains a mixed entry also requires `--include-mixed` after reviewing the selected tools and scope.

## Commands

### List and inspect

```console
mia pkg groups
mia pkg list
mia pkg list --group domain
mia pkg list --installed
mia pkg list --integrated
mia pkg list --json
mia pkg info ghunt
mia pkg doctor
```

`doctor` reports catalog state, executable discovery, whether MIA manages the
installation, API/setup requirements, maintenance warnings, and the selected
host package manager.

### Install

```console
mia pkg install maigret sherlock
mia pkg install --group username
mia pkg install --group domain --include-mixed
mia pkg install --all
mia pkg install --all --include-mixed
```

Useful controls:

```console
mia pkg install subfinder --dry-run
mia pkg install subfinder --yes
mia pkg install exiftool --package-manager apt
mia pkg install waymore --no-system
```

`--no-system` forbids use of `sudo` and host package managers. The operation
fails if a prerequisite such as Go, Cargo, or a distribution package is absent.

### Live progress and logs

Interactive terminals show two live rows while packages are installed, updated,
or removed:

- an overall bar and percentage based on completed catalog tools; and
- the current tool, queue position, spinner, elapsed time, and latest bounded
  output line.

When a compiler or package manager is silent, MIA prints a periodic
`Still working…` heartbeat so a long Go or Cargo build does not look frozen.
The percentage is per tool rather than per downloaded byte, so it may remain at
one value during a large single-tool build.

Use the global verbose option to stream all child-process output above the live
display:

```console
mia --verbose pkg install subfinder
mia --verbose pkg update --all
```

Use `--quiet` when only the overall bar and final summary are wanted:

```console
mia pkg install --all --quiet --yes
```

`--quiet` and the global `--verbose` option are mutually exclusive. In a
non-interactive terminal or redirected log, MIA falls back to plain per-tool
start, heartbeat, and completion messages.

Every command writes a private per-tool log under:

```text
~/.local/share/mia/package-logs/<operation-id>/<tool-id>.log
```

The final table reports each tool's outcome and elapsed time, followed by the
log directory. Pressing `Ctrl+C` terminates the active subprocess group, marks
the current tool as interrupted, lists unstarted tools as skipped, prints the
partial summary, and exits with status 130.

### Uninstall

```console
mia pkg uninstall blackbird
mia pkg uninstall --group username
mia pkg uninstall --all
```

MIA removes only paths recorded in its state file. Distribution/Homebrew
packages are preserved by default because other applications may depend on
them. To request system package removal explicitly:

```console
mia pkg uninstall exiftool --remove-system-packages
```

Review the package manager's dependency plan before confirming.

### Update

```console
mia pkg update subfinder
mia pkg update --group username
mia pkg update --all
mia pkg update --all --include-mixed
```

For MIA-managed Python, Git, Go, Cargo, and release-binary tools, update currently means a clean
reinstall from the catalog recipe. Updating an absent tool is reported explicitly as an installation. Distribution-managed packages should normally
be updated with the distribution's normal upgrade command.

## Installation layout

Default locations:

```text
~/.local/share/mia/
├── package-state.json
├── package-logs/
│   └── <operation-id>/
│       └── <tool-id>.log
├── packages/
│   └── <tool-id>/
├── package-backups/
├── python/
└── uv-cache/

~/.local/bin/                 # or ~/bin when already preferred by PATH
├── mia
└── managed tool links/wrappers
```

Override for testing or separate profiles:

```console
export MIA_STATE_DIR="$HOME/.local/share/mia-work"
export MIA_BIN_DIR="$HOME/.local/bin"
export MIA_PACKAGE_MANAGER=none
```

The state file records only installations made by MIA. Tools discovered elsewhere
on `PATH` are shown as external and are not removed by `mia pkg uninstall`.

## Install methods

Catalog recipes are declarative data rather than shell snippets. Supported
methods are:

- isolated Python environments through `uv`;
- source projects synchronized through `uv`;
- Go modules with a per-tool `GOBIN`;
- Cargo crates with a per-tool install root;
- reviewed Git repositories with a dedicated Python environment and wrapper;
- reviewed Git scripts with an explicit runtime wrapper;
- upstream ZIP or tar.gz release binaries selected by Linux architecture;
- host packages through apt, dnf, pacman, zypper, apk, or Homebrew;
- dedicated compatibility recipes for Holehe and SpiderFoot.

Commands are executed as argument arrays without `shell=True`.

## API keys and authentication

Some tools are useful only after upstream authentication. `mia pkg info TOOL`
shows common environment-variable names, but MIA does not collect, encrypt, or
store secrets. Configure the tool according to its upstream documentation.
Never paste tokens into issue reports, command screenshots, reports, or shell
history.

Examples of setup-required entries include GHunt, Shodan, Censys, VirusTotal,
Chaos Client, github-subdomains, uncover, h8mail, and Mosint.

## Supply-chain limitations

The catalog points to third-party package registries and repositories. Unless a
recipe pins an exact release, the code resolved today may differ from a future
installation. MIA does not currently verify maintainer identity, signatures,
source archives, transitive dependencies, or reproducible builds.

Before sensitive use:

1. inspect the catalog entry and upstream repository;
2. pin a reviewed version or commit in a private fork;
3. verify checksums/signatures where upstream publishes them;
4. inspect dependency locks and licenses;
5. install under an unprivileged account;
6. test with non-sensitive targets;
7. retain the exact tool/version inventory with the report.

## Adding a catalog package

A catalog pull request must include:

- canonical upstream homepage;
- license or `unknown` when genuinely unclear;
- target categories and risk label;
- installation recipe using an existing declarative method;
- setup/API/maintenance warnings;
- dry-run and catalog-validation tests;
- explicit integration level;
- no embedded tokens, arbitrary shell fragments, or automatic consent bypasses.

A package entry is not the same as a scan adapter. Structured adapters require
fixtures, parser tests, failure behavior, and documentation in addition to the
catalog entry.

## Windows behavior

Windows-managed Python tools use isolated virtual environments with executables
under `Scripts\`. MIA exposes stable `.cmd` shims under
`%LOCALAPPDATA%\MIA\bin`, hides child console windows, and terminates scanner
process trees on cancellation. `winget` is used only for catalog entries with an
explicit verified package mapping. Other Linux-only entries are reported as
unsupported. The default starter group is `windows-core`.
