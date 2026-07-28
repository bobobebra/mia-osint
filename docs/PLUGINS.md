# MIA scan plugin API

## Package entries are not plugins

`mia pkg` can manage many commands that MIA does not invoke automatically.
Catalog integration levels are:

- `full`: structured scan adapter;
- `raw`: adapter with conservative parsing;
- `managed-only`: lifecycle management only.

Adding a catalog recipe must never be represented as adding a report parser.

## Contract

Plugins subclass `mia.plugin.BasePlugin` or `mia.plugin.ExternalCommandPlugin`.

Required metadata:

```python
plugin_id = "example"
name = "Example"
target_types = frozenset({TargetType.USERNAME})
```

External adapters normally implement:

```python
def build_command(self, context, config, executable) -> list[str]: ...
def parse(self, context, process) -> list[Finding]: ...
```

Optional hooks include bounded stdin data. The base implementation handles
availability, raw folders, command recording, subprocess execution, timeouts,
stdout/stderr capture, parser errors, and `parsed_findings.json`.

## Rules

- Never use `shell=True`, `bash -c`, `eval`, or target interpolation into shell text.
- Pass every argument as a separate list item.
- Preserve raw evidence and set `evidence_path` on findings.
- Prefer machine-readable upstream output.
- Treat captchas, blocks, rate limits, and ambiguous output as unknown.
- Do not turn parser exceptions or HTTP errors into positive findings.
- Use stable finding kinds and conservative source-confidence values.
- Confidence describes evidence quality, not human identity.
- Add positive, negative, malformed, and upstream-change fixtures.
- Document the upstream versions represented by fixtures.

## Built-in module discovery

A built-in module may export one class:

```python
PLUGIN_CLASS = ExamplePlugin
```

or several:

```python
PLUGIN_CLASSES = [PluginOne, PluginTwo]
```

## External entry points

A third-party package can expose a plugin in `pyproject.toml`:

```toml
[project.entry-points."mia.plugins"]
my_plugin = "my_package.plugin:MyPlugin"
```

The object may be a plugin instance or a no-argument plugin class.

## Context

`PluginContext` provides the validated target, target type, scan/profile IDs,
scan and raw paths, timeout, and merged profile-specific arguments.

## Compatibility

External CLIs change independently. Keep command construction conservative,
tolerate additional fields, reject malformed positives, and preserve raw output.
The plugin API is unstable during alpha; external packages should pin MIA.
