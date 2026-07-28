# Architecture

## Product layers

- **MIA Core** owns scanning, normalization, verification, correlation, storage, packages, the CLI, and the local API.
- **MIA Discover** is a guided React client for selector searches and cautious result review.
- **MIA Workbench** is an advanced React client for cases, graphs, timelines, evidence, packages, and analysis.

Both clients call the same Core services and never execute shell commands directly.


## Design principle

MIA is evidence-first. External tools and APIs are replaceable data sources; the
long-lived core is the normalized evidence model, persistent workspace,
relationship graph, provenance, correlation index, and offline investigation
experience.

```text
CLI
├── classic scan
│   └── orchestrator → plugins → normalized findings → scan reports/history
├── investigate
│   ├── case workspace
│   ├── root scan
│   ├── graph builder
│   ├── bounded pivot queue
│   ├── child scans
│   ├── shared knowledge index
│   ├── timeline + graph exports
│   ├── grounded assistant
│   └── offline dashboard
├── pkg
│   └── declarative optional-tool lifecycle manager
├── api
│   └── credential and enablement management
└── plugin
    └── community plugin scaffolding, validation, installation, and health
```

## Major components

### CLI (`mia.cli`)

Typer command surface. It validates arguments, resolves runtime configuration,
renders progress, and delegates to services. Tool-specific parsing does not
belong in the CLI.

### Targeting (`mia.targeting`)

Classifies automatic targets and validates explicit target types. Validation is
syntactic; it cannot determine authorization or lawful purpose.

### Plugin registry (`mia.registry`)

Discovers built-in modules, Python entry points in the `mia.plugins` group, and
installed community plugins. Duplicate plugin IDs are rejected.

### Plugin contract (`mia.plugin`)

Defines metadata, target compatibility, dependency detection, execution,
parsing, and structured `PluginRunResult` output. External commands run through
the process runner rather than shell strings.

### Orchestrator (`mia.orchestrator`)

Selects profile-compatible plugins, runs them concurrently with bounded
semaphores, uses the persistent result cache, normalizes findings, writes scan
reports, and records history. Missing optional plugins are skipped unless they
were explicitly requested.

### Process runner (`mia.process`)

Uses argument arrays and `shell=False`, creates process groups, bounds captured
stdout/stderr, records command metadata, handles cancellation, and terminates
process groups on timeout. It is not a sandbox.

### Normalizer (`mia.normalizer`)

Canonicalizes supported values, merges equivalent findings, combines source
lists, and computes a transparent prioritization heuristic. It must not infer
human identity from username equality alone.

### Case workspace (`mia.workspace`)

Owns private directories, `case.yaml`, `case.db`, notes, attachments, scan
artifacts, exports, and retrieval methods. SQLite stores scans, graph nodes,
graph edges, timeline events, and attachment metadata.

### Investigation engine (`mia.investigation`)

Coordinates case creation/resolution, root scans, graph ingestion, pivot queue
execution, graph/timeline exports, knowledge ingestion, correlations, assistant
summaries, and dashboard generation.

### Evidence graph (`mia.graph`)

Transforms normalized findings into typed nodes and explainable edges. Stable IDs
are derived from case ID, entity type, canonical value, and relation. It exports
JSON, GraphML, GEXF, and Mermaid.

### Pivot engine (`mia.pivot`)

Extracts explicit indicators from normalized findings and whitelisted attributes.
The queue enforces confidence, type, depth, target-count, and visited-set limits.
Workflow edges are clearly marked as actions rather than ownership evidence.

### Shared knowledge (`mia.knowledge`)

Stores normalized entities and their case memberships in a separate local
SQLite database. Correlation suggestions are exact normalized-value matches.
No fuzzy identity inference is performed.

### Dashboard (`mia.reports.dashboard`)

Produces one self-contained offline HTML application. It embeds bounded case data
with HTML-safe JSON, contains no CDN dependencies, and offers graph, timeline,
filters, logs, raw excerpts, notes, attachments, assistant output, and exports.

### Assistant (`mia.assistant`)

The local provider is deterministic. The optional OpenAI-compatible provider
receives bounded normalized evidence and requires each statement to cite valid
node or edge IDs. Invalid and uncited statements are discarded.

### Secrets (`mia.secrets`)

Resolves credentials in this order: documented environment variable, operating-
system keyring, then an explicitly requested mode-0600 plaintext fallback.
Secrets are excluded from YAML, reports, package state, and command lines.

### Package manager (`mia.package_manager`)

Reads a fixed declarative catalog, resolves groups and risk labels, uses isolated
per-tool locations, records MIA-owned installs, and removes only unchanged owned
links/wrappers. Catalog recipes and scan adapters are intentionally separate.

### Community plugin SDK (`mia.plugin_sdk`)

Defines `manifest.yaml`, version compatibility, Python requirements, package
catalog dependencies, API services, scaffolding, validation, copying, health
checks, and uninstall behavior.

## Persistence

```text
~/.local/share/mia/
├── mia.db          classic scan history
├── cache.db        plugin result cache
├── knowledge.db    cross-case entity index
├── packages/       package-manager state and roots
└── plugins/        community plugins

~/mia_cases/
└── <case>/         case-local database and evidence artifacts
```

## Trust boundaries

1. CLI targets, imported evidence, notes, and configuration;
2. MIA code and bundled declarative catalog;
3. third-party executables and installers;
4. remote APIs and websites;
5. untrusted tool output and API response data;
6. reports, screenshots, raw files, databases, and logs;
7. environment variables and keyring backends;
8. optional remote AI endpoints.

## Failure semantics

Plugin runs use `success`, `partial`, `failed`, `timed_out`, `unavailable`,
`skipped`, and `cached`. One plugin failure does not invalidate independent
successful evidence. Investigation completion preserves partial case state so an
interrupted or degraded case remains inspectable.

## 4.1 identity-intelligence layer

The Deep Case layer adds four services above normal scan ingestion:

1. `DeepCaseEngine` stores heterogeneous investigator seeds and schedules only
   compatible scanner targets while retaining context-only items.
2. `ProfileVerifier` independently verifies candidate profile URLs, extracts
   bounded public metadata, writes snapshots, and constrains confidence.
3. `IdentityClusterEngine` compares normalized profile features, creates
   explainable positive/negative relationship edges, and generates review tasks.
4. `InvestigationAssistant.analyze` runs bounded sequential evidence-cited
   analyst/skeptic/verifier/planner workflows.

Verification has a separate trust boundary from discovery. Candidate URLs are
not considered confirmed findings, and verifier HTTP requests block private
network destinations and unsafe redirects by default.

## Windows desktop packaging

On Windows, a Tauri shell starts the same MIA Core as a hidden PyInstaller
sidecar. Core selects a random loopback port and writes a short-lived handshake
for the shell. Persistent state is stored under `%LOCALAPPDATA%\MIA` and
configuration under `%APPDATA%\MIA`. See [`WINDOWS.md`](WINDOWS.md).
