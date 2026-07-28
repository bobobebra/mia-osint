# Configuration

MIA deep-merges the packaged defaults with an optional user YAML file.

Default user path:

```text
~/.config/mia/config.yaml
```

Create it:

```console
mia config init
mia config path
mia config show
```

Override for one command:

```console
mia --config ./config.yaml investigate octocat
```

## Paths

```yaml
paths:
  output_dir: ~/mia_reports
  state_dir: ~/.local/share/mia
  log_dir: ~/.local/state/mia/log
  cases_dir: ~/mia_cases
  user_plugins_dir: ~/.local/share/mia/plugins
```

Environment overrides:

```text
MIA_CONFIG
MIA_OUTPUT_DIR
MIA_STATE_DIR
MIA_CASES_DIR
MIA_BIN_DIR
MIA_PACKAGE_MANAGER
```

## Execution and cache

```yaml
execution:
  max_concurrency: 3
  max_capture_bytes: 52428800
  default_timeout: 600
  keep_negative_findings: false
  cache:
    enabled: true
    ttl_seconds: 86400
    api_ttl_seconds: 3600
    reuse_failed: false
```

API entries use the shorter API TTL. `--no-cache` bypasses reads and writes for
one investigation.

## Reports and dashboard

```yaml
reports:
  html: true
  json: true
  text: true
  markdown: true
  create_latest_symlink: true
  dashboard_raw_excerpt_bytes: 12000
```

Raw excerpts are bounded; complete authoritative files remain in scan `raw/`
directories.

## Profiles

Profiles list plugin IDs. `all: ['*']` selects all compatible discovered plugins.
Unavailable optional plugins are skipped unless explicitly requested.

## Tool settings

```yaml
tools:
  maigret:
    enabled: true
    executable: maigret
    timeout: 900
    extra_args: []
    profile_args:
      quick: [--top-sites, "100"]
```

Executable values beginning with `~`, `.`, or `/` are expanded as paths.

## Pivoting

```yaml
pivoting:
  enabled: false
  max_depth: 2
  max_targets: 25
  min_confidence: 0.65
  child_profile: quick
  allowed_types: [username, email, domain, ip, phone, hash, certificate]
  include_lookalike_domains: false
```

## Workspaces

```yaml
workspaces:
  auto_update_dashboard: true
  auto_correlate: true
  graph_max_nodes_in_dashboard: 1500
```

The full graph remains in SQLite and export files when dashboard display is
capped.

## Assistant

```yaml
assistant:
  provider: local
  enabled: true
  timeout: 90
  send_raw_evidence: false
  max_nodes: 200
  providers:
    openai-compatible:
      endpoint: https://api.openai.com/v1/chat/completions
      model: ""
      api_service: assistant
      requires_key: true
    gemini:
      endpoint: https://generativelanguage.googleapis.com/v1beta
      model: ""
      api_service: gemini
      requires_key: true
    ollama:
      endpoint: http://localhost:11434/api
      model: ""
      api_service: ollama
      requires_key: false
```

Configure providers with `mia assistant configure` and inspect them with
`mia assistant providers`. Secrets remain outside YAML. The alpha.1 top-level
OpenAI-compatible fields remain supported for migration.

The remote implementations send normalized evidence only. Keep
`send_raw_evidence: false`; raw evidence transmission is intentionally not
implemented in this alpha. See [`AI_ASSISTANT.md`](AI_ASSISTANT.md).

## Deep Case, verification, and identity settings

```yaml
verification:
  enabled: true
  timeout: 15
  max_profiles: 60
  max_concurrency: 5
  max_response_bytes: 2097152
  store_html: false
  avatar_download: true
  allow_private_networks: false

identity:
  cluster_threshold: 0.58
  strong_cluster_threshold: 0.78
  contradiction_threshold: 0.28
  username_only_cap: 0.38
  max_pairwise_profiles: 250

deep_cases:
  profile: deep
  verify_profiles: true
  enable_pivoting: true
  max_depth: 2
  max_targets: 75
  analysis_depth: thorough
  workflow: identity
  continue_on_seed_failure: true
```

`allow_private_networks` should remain false outside a controlled laboratory.
Remote assistant context is bounded with `assistant.max_context_items` and
`assistant.max_text_chars`.
