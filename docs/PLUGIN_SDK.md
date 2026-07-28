# Community plugin SDK

## Scaffold

```console
mia plugin create my-plugin
```

The generated directory contains:

```text
my-plugin/
├── manifest.yaml
├── plugin.py
├── README.md
└── tests/test_plugin.py
```

## Manifest

```yaml
manifest_version: "1"
plugin_id: my-plugin
name: My Plugin
version: 0.1.0
description: Community MIA plugin
entrypoint: plugin.py
requires_mia: ">=4.0.0a1,<5"
license: MIT
homepage: null
target_types: [username]
package_dependencies: []
python_dependencies: []
api_services: []
```

- `requires_mia` is a Python version specifier checked against the running MIA.
- `package_dependencies` reference IDs from `mia pkg`.
- `python_dependencies` use normal Python requirement syntax and are diagnosed,
  not silently installed into MIA's environment.
- `api_services` declare configured MIA API services required by the plugin.

## Validate and install

```console
mia plugin validate ./my-plugin
mia plugin install ./my-plugin
mia plugin install ./my-plugin --install-dependencies
mia plugin doctor
```

Mixed/direct-request package dependencies require `--include-mixed`.
Installation copies a validated local plugin into MIA's private plugin directory.
It does not download arbitrary marketplace code.

## Plugin entrypoint

The module must expose `PLUGIN_CLASS` or `PLUGIN_CLASSES` and implement MIA's
`BasePlugin` contract. Return structured `Finding` and `PluginRunResult` models,
preserve authoritative raw evidence, use the process runner or bounded HTTP
client, and never place secrets in commands or findings.

## Versioning and publishing

Community plugin APIs are pre-1.0. Pin a compatible MIA range, maintain parser
fixtures, test malformed and empty output, document data sources and terms, and
state false-positive behavior. A plugin's presence is not endorsement or audit.
