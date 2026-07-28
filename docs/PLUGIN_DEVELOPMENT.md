# Plugin development

MIA discovers built-in plugins and external packages registered in the
`mia.plugins` entry-point group.

## Responsibilities

A plugin should:

- declare a stable lowercase plugin ID and display name;
- declare supported target types;
- detect its dependency without changing the system;
- construct a subprocess argument list without a shell;
- write evidence only inside its raw directory;
- parse bounded output into `Finding` objects;
- return uncertainty instead of inventing a positive result;
- include parser tests and sanitized fixtures.

## Distribution

An external package can expose an entry point conceptually like:

```toml
[project.entry-points."mia.plugins"]
example = "example_package.plugin:ExamplePlugin"
```

See `examples/plugins/example_plugin.py` and `docs/PLUGINS.md`.

## API stability

The plugin API is alpha and may break. External packages should pin a compatible
MIA range and test against every supported version.

## Safety restrictions

Plugins adding credential attacks, authentication bypass, exploit execution,
malware, covert persistence, or rate-limit evasion are out of project scope.
