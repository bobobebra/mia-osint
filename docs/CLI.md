# CLI reference

## Global

```console
mia --help
mia --version
mia --config PATH <command>
mia --verbose <command>
mia about
mia doctor
mia plugins [--json]
mia profiles
```


## Local interfaces

```console
mia discover           # guided selector-search dashboard
mia workbench          # advanced investigation workspace
```

Each interface has one public launch command. Both commands accept `--no-browser`, `--port`, `--host`, and the guarded remote-access options.

MIA Discover defaults to `127.0.0.1:8766`. MIA Workbench defaults to
`127.0.0.1:8765`. Both accept `--no-browser`, `--port`, and the guarded remote
options described in [`UI.md`](UI.md).

## Persistent investigations

```console
mia investigate TARGET [OPTIONS]
```

Important options:

```text
--type, -t TYPE          explicit target type; default auto
--case CASE              append to an existing case
--name NAME              name a new case
--profile, -p PROFILE    quick, default, deep, all
--pivot                  enable automatic pivots
--no-pivot               disable configured pivoting
--max-depth N            pivot recursion depth, 0–8
--max-targets N          maximum unique automatic targets, 1–500
--tool PLUGIN            repeatable root-scan include filter
--exclude-tool PLUGIN    repeatable exclusion for all scans
--no-cache               bypass plugin result cache
```

Examples:

```console
mia investigate octocat --type username --name "Octocat"
mia investigate octocat --pivot --max-depth 2 --max-targets 20
mia investigate person@example.com --case case-20260712-ab12cd34
```

## Case management

```console
mia case create NAME [--description TEXT] [--tag TAG]
mia case list [--archived] [--json]
mia case show CASE [--json]
mia case note CASE [TEXT]
mia case add-evidence CASE PATH [--note TEXT]
mia case add-screenshot CASE PATH [--note TEXT]
mia case dashboard CASE
mia case summarize CASE [--provider local|openai-compatible|gemini|ollama] [--model MODEL] [--endpoint URL]
mia case correlations CASE [--json]
mia case archive CASE [--reopen]
```

When note text is omitted, `mia case note` reads standard input.

## API credentials

```console
mia api list [--json]
mia api set SERVICE [--value KEY] [--insecure-file] [--no-enable]
mia api delete SERVICE [--keep-enabled]
mia api enable SERVICE
mia api disable SERVICE
```

By default, `api set` prompts without echo and stores the value in the operating-
system keyring. Environment variables take precedence.

## Community plugins

```console
mia plugin create PLUGIN_ID [--path PATH]
mia plugin list [--json]
mia plugin validate PATH [--json]
mia plugin install PATH [--replace] [--install-dependencies] [--include-mixed] [-y]
mia plugin doctor [--json]
mia plugin uninstall PLUGIN_ID
```

## Shared knowledge

```console
mia knowledge search VALUE [--limit N] [--json]
```

This searches normalized entities already stored in local cases.

## Result cache

```console
mia cache status [--json]
mia cache clear [-y]
```

## Classic scans

```console
mia scan TARGET [--type TYPE] [PROFILE] [TOOL FILTERS]
```

Profile selection:

```console
mia scan TARGET --quick
mia scan TARGET                 # default
mia scan TARGET --default
mia scan TARGET --deep
mia scan TARGET --all
mia scan TARGET --profile deep
```

Only one profile selector may be supplied.

Plugin filters:

```console
mia scan TARGET --tool maigret --tool sherlock
mia scan TARGET --exclude-tool spiderfoot
```

Typed aliases:

```console
mia search USERNAME
mia username USERNAME
mia email ADDRESS
mia domain DOMAIN
mia ip ADDRESS
mia phone NUMBER
mia image PATH
mia file PATH
mia hash VALUE
```

## Optional package manager

```console
mia pkg groups
mia pkg list [--installed] [--group GROUP] [--integrated] [--json]
mia pkg info TOOL [--json]
mia pkg doctor
```

Install:

```console
mia pkg install TOOL [TOOL ...]
mia pkg install --group username
mia pkg install --all
mia pkg install --all --include-mixed
```

Common options:

```text
--group, -g GROUP
--all
--include-mixed
--yes, -y
--dry-run
--no-system
--package-manager apt|dnf|pacman|zypper|apk|brew|none
```

Uninstall and update:

```console
mia pkg uninstall TOOL
mia pkg uninstall --group username
mia pkg uninstall --all
mia pkg uninstall exiftool --remove-system-packages
mia pkg update TOOL
mia pkg update --all
```

System packages are preserved unless removal is explicit.

Package install, update, and uninstall commands show live progress in an
interactive terminal. Add global `--verbose` before `pkg` to stream every
subprocess line, or add `--quiet` to the package command for only overall
progress and the final summary.

## Classic history

```console
mia history [--limit N] [--target TARGET]
mia show SCAN_ID [--json]
mia compare OLDER_SCAN NEWER_SCAN [--output PATH]
```

## Configuration

```console
mia config init [--force]
mia config show
mia config path
```

## Exit behavior

- `0`: command completed successfully;
- `1`: one or more requested scan/package operations failed;
- `2`: invalid command, selection, target, configuration, or catalog request.
- `130`: package operation interrupted with `Ctrl+C` after printing a partial
  summary.

Individual plugin failures are recorded and do not erase independent successful
results or already-persisted case state.


## Assistant providers

```console
mia assistant providers [--json]
mia assistant configure PROVIDER [--model MODEL] [--endpoint URL] [--default|--no-default]
```

Supported provider names are `openai-compatible`, `gemini`, and `ollama`; the
`local` provider needs no configuration.

## Deep Cases and identity review (4.1 alpha)

```console
mia workflows
mia deeps --write-template deep-case.yaml
mia deeps deep-case.yaml
mia deeps --name "Case" --username alice --email alice@example.com
mia deeps --case CASE --username another_alias --address "Context"
```

`mia deeps` accepts repeatable typed seeds and generic `--seed TYPE=VALUE`
inputs. Important controls include `--workflow`, `--profile`, `--no-verify`,
`--no-pivot`, `--max-depth`, `--max-targets`, `--tool`, `--exclude-tool`,
`--analyze`, `--analysis-depth`, and `--thinking-level`.

Case review commands:

```console
mia case verify CASE
mia case cluster CASE
mia case review CASE
mia case review CASE --task TASK_PREFIX --status accepted --note "Manual decision"
mia case analyze CASE --depth exhaustive --provider gemini --thinking-level high
```


## Desktop integration and repair

Install, inspect, or remove the current-user Linux application-menu entries:

```console
mia desktop install
mia desktop status
mia desktop status --json
mia desktop remove
```

Validate the managed state, database, packaged UI assets, plugin availability,
and desktop launchers:

```console
mia repair
```

Also repair the recommended scanner group:

```console
mia repair --install-tools --yes
```
