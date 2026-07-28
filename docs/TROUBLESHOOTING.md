# Troubleshooting

## `No such option: -s`

Commands do not start with a dash:

```console
mia scan bobobebra
```

not:

```console
mia -scan bobobebra
```

## `mia: command not found`

Check the installer-selected directory:

```console
ls -l ~/.local/bin/mia ~/bin/mia 2>/dev/null
```

Add it to PATH, for example:

```console
export PATH="$HOME/.local/bin:$PATH"
```

Add the export to your shell profile after confirming the path.

## A plugin is optional/unavailable

```console
mia doctor
mia plugins
```

Confirm the configured executable and run it directly with `--version` or
`--help`. Re-run the installer or correct `~/.config/mia/config.yaml`.

## SpiderFoot dependency failure

Use the installer-managed `mia-spiderfoot` wrapper, not `python sf.py` from an
unrelated environment. The wrapper selects SpiderFoot's own Python runtime.

Inspect:

```console
command -v mia-spiderfoot
mia-spiderfoot -V
```

## Broken HTML titles

MIA 3.2.0 and later sanitize Maigret metadata and escape third-party text. Old
reports are static files and must be regenerated after upgrading.

## Scan finished with zero findings

Zero findings can mean no matches, blocking, rate limiting, network failure,
parser incompatibility, or an unavailable plugin. Inspect the plugin-run table
and files under `raw/<plugin>/`.

## Installer fails

Read the log:

```console
less ~/.local/state/mia/install.log
```

Then run:

```console
./install.sh --dry-run --yes
```

Report the sanitized OS, package manager, architecture, installer output, and
relevant log lines. Do not upload private reports or target data.

## Reset user environments

```console
./uninstall.sh
./install.sh
```

Configuration and reports are preserved by default.

## Package catalog diagnostics

```console
mia pkg doctor
mia pkg info TOOL
mia pkg list --installed
```

The output distinguishes commands installed by MIA from commands merely found
on `PATH`. MIA will not uninstall an external command it did not record.

## Optional tool install failed

Preview the exact recipe:

```console
mia pkg install TOOL --dry-run --package-manager none
```

Then check common prerequisites:

```console
command -v uv
command -v git
command -v go
command -v cargo
```

Go and Rust tools may require a newer compiler than the distribution repository
provides. MIA reports the upstream build failure rather than silently selecting
an unreviewed binary download.

## Package installation appears stuck

MIA 4.0.0 alpha 4 and later show the current tool, elapsed time, latest build
message, and periodic heartbeat updates. The overall percentage advances after
each catalog tool finishes, so a large Go or Cargo build can remain at the same
percentage for several minutes while the spinner and heartbeat continue.

For full output:

```console
mia --verbose pkg install TOOL
```

For a compact display:

```console
mia pkg install --all --quiet --yes
```

Inspect the detailed log printed in the final summary, or list recent operation
directories:

```console
find ~/.local/share/mia/package-logs -maxdepth 2 -type f -print | sort
```

Pressing `Ctrl+C` stops the active child-process group and prints a partial
summary. Re-running the same install command is supported; already managed
tools are reported as present and incomplete managed roots are rebuilt.

## API-backed tool is installed but unusable

Installation does not authenticate API tools. Inspect:

```console
mia pkg info TOOL
```

Follow the upstream setup documentation and provide a scoped token through the
mechanism expected by that tool. MIA does not store or validate credentials.

## Tool says managed-only

This is expected. `managed-only` means `mia pkg` can install, update, and remove
the command, but MIA scans do not yet have a tested parser. Run the command
directly and consult its upstream help. Do not expect it in an HTML report.

## Uninstall preserved a system package

Ordinary uninstall intentionally preserves apt/dnf/pacman/zypper/apk/Homebrew
packages. Review dependencies, then opt in explicitly:

```console
mia pkg uninstall TOOL --remove-system-packages
```

## Reset only optional packages

```console
mia pkg uninstall --all --yes
```

This keeps the MIA Core and preserves system packages. To remove MIA as well,
use `./uninstall.sh` from a release tree.
