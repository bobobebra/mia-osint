# Migration from MIA v3.4 to v4

## Compatibility

Classic commands remain available:

```console
mia scan TARGET
mia search USERNAME
mia pkg ...
mia history
mia compare ...
```

Existing standalone scan history and report directories are not automatically
converted into cases. They remain readable through v3-compatible commands.

## New default workflow

Use `mia investigate` for persistent work:

```console
mia investigate TARGET --type TYPE --name "Case name"
```

A case can contain multiple scans, manual evidence, notes, graph relationships,
timeline events, correlations, and assistant summaries.

## Paths

New defaults:

```text
~/mia_cases                         case workspaces
~/.local/share/mia/knowledge.db     cross-case entity index
~/.local/share/mia/cache.db         plugin result cache
~/.local/share/mia/plugins/         community plugins
```

Override with YAML or `MIA_CASES_DIR` / `MIA_STATE_DIR`.

## Configuration additions

v4 adds top-level sections:

```yaml
pivoting: {}
workspaces: {}
assistant: {}
apis: {}
```

Old user configuration is deep-merged with v4 defaults, so missing sections use
safe defaults. Pivoting and external APIs remain disabled unless enabled.

## Credentials

Do not add keys to YAML. Move them to documented environment variables or run:

```console
mia api set SERVICE
```

## Reports

Standalone scans still write HTML/JSON/Markdown/text. Cases additionally write
an offline dashboard, case JSON, graph formats, and timeline formats.

## Package manager

The v3.4 package catalog and managed state are retained. Run:

```console
mia pkg doctor
```

after upgrading to verify executable paths and ownership state.

## Recommended upgrade

```console
./install.sh --mia-only --yes
mia --version
mia doctor
mia pkg doctor
mia api list
```

Back up existing reports, cases, and state databases before replacing an alpha
release.
