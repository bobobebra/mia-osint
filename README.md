# MIA — local-first OSINT investigation platform

> [!WARNING]
> **MIA is an early, vibe-coded alpha.** A substantial part of its architecture,
> code, tests, installer, and documentation was created with generative-AI
> assistance under human direction and review. It has not received a professional
> security audit, broad Windows or Linux certification, or independent accuracy validation.
> Expect bugs, upstream breakage, false positives, false negatives, and breaking
> changes. MIA produces investigative leads, not proof of identity, ownership,
> compromise, intent, or wrongdoing.

MIA is a Windows-and-Linux, local-first OSINT investigation platform. It orchestrates
separately installed tools and passive APIs, normalizes their output, builds a
persistent evidence graph, follows explicit indicators through bounded automatic
pivoting, correlates exact entities across cases, and produces a modern offline
case dashboard.

MIA's defining feature is not the number of tools it launches. The value is what
happens **after** those tools finish: provenance, normalization, explainable
confidence, relationships, timelines, correlations, notes, attachments, and
reusable case history.

MIA is organized as one project with three product layers:

- **MIA Core** — the shared backend, CLI, scanners, storage, verification, and API;
- **MIA Discover** — guided selector search and public-account discovery;
- **MIA Workbench** — advanced cases, evidence review, graphs, packages, and analysis.

```console
mia investigate octocat --type username --name "Octocat research" --pivot
```

## Project status

- Release: **4.2.0 alpha 9** (`4.2.0a9`)
- Stability: **early experimental alpha**
- Development style: **substantially vibe-coded with AI assistance**
- Security review: **no professional audit**
- Accuracy review: **no evidence-grade validation**
- Compatibility promise: **best effort only**
- License: **MIT**

Read [`AI_DISCLOSURE.md`](AI_DISCLOSURE.md), [`DISCLAIMER.md`](DISCLAIMER.md),
[`SECURITY.md`](SECURITY.md), and
[`docs/RESPONSIBLE_USE.md`](docs/RESPONSIBLE_USE.md) before use.

## What changed in v4

MIA v4 keeps the v3 scanner and package manager, then adds an investigation
layer:

- persistent case workspaces with SQLite, notes, evidence, screenshots, logs,
  scans, graph exports, timeline exports, reports, and portable JSON;
- an interactive offline evidence graph with node and relationship inspection;
- explainable relationship confidence with factors that raise, lower, or leave
  confidence unchanged;
- configurable automatic pivoting with target allow-lists, confidence threshold,
  depth and target limits, caching, and loop prevention;
- a shared local knowledge database for exact cross-case correlations;
- an offline dashboard with graph, timeline, filters, statistics, raw excerpts,
  plugin logs, notes, attachments, screenshots, and assistant output;
- a deterministic local investigation assistant plus OpenAI-compatible, Google
  Gemini, and local/cloud Ollama providers that reject statements lacking valid
  evidence IDs;
- opt-in passive integrations for Shodan, VirusTotal, Have I Been Pwned,
  SecurityTrails, Censys, and Intelligence X;
- API-key storage through environment variables or the operating-system keyring;
- a community plugin SDK with manifests, compatibility ranges, package
  dependencies, API requirements, scaffolding, validation, installation, health
  checks, and versioning;
- persistent plugin-result caching and asynchronous bounded tool execution;
- the existing 40-tool optional package catalog and cross-distribution installer.

See [`RELEASE_NOTES.md`](RELEASE_NOTES.md) and
[`docs/MIGRATION_V3_TO_V4.md`](docs/MIGRATION_V3_TO_V4.md).

MIA 4.2 alpha 9 adds the native Windows port: Windows application-data paths, hidden and cancellable process execution, managed `.cmd` tool shims, Windows tool capability checks, a frozen MIA Core sidecar, a Tauri launcher, an NSIS installer build, and Windows CI. Alpha 8 added the one-file Linux installer, application-menu launchers, transactional upgrade recovery, and `mia repair`. Alpha 7 introduced the dashboard-first Discover interface, platform-specific username seeds, separate application icons, and explicit external-AI cost confirmation. Alpha 5 was the account-link false-positive hardening release. **MIA 4.1 alpha 1** adds Deep Cases and an identity-verification workflow: many heterogeneous investigator-supplied leads can live in one case; profile hits are verified separately from discovery; public metadata and snapshots are compared into explainable clusters; contradictions become manual-review tasks; and optional AI analysis runs sequential analyst, skeptic, verifier, planner, and synthesis passes with mandatory evidence citations.

**MIA 4.2 alpha 3** specializes the simple UI in public account discovery. A public social-profile URL is converted into a scan-ready handle, careful formatting variants can be checked, and explicit links from one public profile to another are preserved as strong association evidence. Same-handle or similar-handle results remain leads and never become identity proof on their own.


## Deep Cases and identity verification

Create one case from many possible indicators:

```console
mia deeps --name "Identity review" \
  --username example_handle \
  --email person@example.com \
  --domain example.com \
  --address "Potential address context" \
  --location Stockholm \
  --hypothesis "These leads may be related; this remains unverified"
```

Generate a manifest template or append another batch later:

```console
mia deeps --write-template deep-case.yaml
mia deeps deep-case.yaml
mia deeps --case CASE_ID --username another_handle --email another@example.com
```

For identity workflows, discovery URLs remain candidates until MIA verifies the public page or platform API. GitHub, Roblox, and Reddit have dedicated public-data adapters; generic sites use conservative title/metadata/visible-text checks, soft-404 detection, bounded snapshots, redirect checks, and private-network blocking. Matching usernames alone are capped as weak evidence.

Run deterministic clustering and the review queue:

```console
mia case verify CASE_ID
mia case cluster CASE_ID
mia case review CASE_ID
```

Run sequential evidence-grounded analysis:

```console
mia case analyze CASE_ID --depth thorough
mia case analyze CASE_ID --depth exhaustive --provider gemini --thinking-level high
```

Later passes receive only the grounded output of earlier passes. Remote providers receive bounded normalized case context, which may contain personal data; use the local provider when the case must remain on-device.

Read [`docs/DEEP_CASES.md`](docs/DEEP_CASES.md), [`docs/PROFILE_VERIFICATION.md`](docs/PROFILE_VERIFICATION.md), and [`docs/IDENTITY_ANALYSIS.md`](docs/IDENTITY_ANALYSIS.md).

## Local interfaces

Both interfaces use the same MIA Core installation and local state.

Launch the guided search experience:

```bash
mia discover
```

Launch the advanced investigation workspace:

```bash
mia workbench
```

Each interface has one public launch command. The former `mia ui`, `mia discover ui`, and `mia workbench ui` forms were removed in alpha 7.

MIA Discover provides automatic selector detection, Quick/Standard/Deep modes, live progress, grouped account and data cards, local history, evidence-aware identity labels, graph exploration, and separate no-AI verification and explicitly confirmed optional AI explanation. MIA Workbench provides Deep Cases, evidence uploads, review queues, detailed graph controls, timelines, package management, provider configuration, and exports.

Both bind to localhost by default. See [docs/UI.md](docs/UI.md).

## Quick start

### Windows desktop installer

Download the x64 installer from the GitHub release:

```text
MIA-4.2.0-alpha.9-Windows-x64-Setup.exe
```

Run it, open **MIA** from the Start menu, and choose **MIA Discover** or
**MIA Workbench**. MIA Core, Python dependencies, and the web interfaces are
bundled. The installer uses a per-user location by default and stores cases under
`%LOCALAPPDATA%\MIA`, outside the application directory.

The first public alpha installer is unsigned, so verify its published SHA-256
before running it. See [`docs/WINDOWS.md`](docs/WINDOWS.md) for supported tools,
build instructions, storage paths, and current limitations.

### Easiest Linux release install

Download `MIA-Linux-Installer.run` from the GitHub release and run:

```console
bash MIA-Linux-Installer.run --yes --launch discover
```

The one-file installer creates an isolated user-owned MIA runtime, verifies the
installed version, and adds **MIA Discover** and **MIA Workbench** to the Linux
application menu. It does not install MIA into the system Python environment.

To install MIA without the optional scanner group:

```console
bash MIA-Linux-Installer.run --mia-only --yes
```

### Install from the source archive on Linux

```console
unzip MIA-v4.2.0-alpha.9-windows-port.zip
cd mia-osint-4.2.0-alpha.9
bash install.sh
```

The Linux source installer supports `--mia-only`, `--no-desktop`, tool groups,
transactional upgrades, and optional launch after setup. The existing Linux
release workflow remains supported.

### Repair and verify

Linux managed installations provide:

```console
mia repair
mia repair --install-tools --yes
mia desktop status
```

On either platform, verify MIA Core with:

```console
mia about
mia --version
mia doctor
mia profiles
mia pkg doctor
mia api list
```

## Investigations and cases

Create a persistent case and run one root scan:

```console
mia investigate octocat --type username --name "Octocat research"
```

Enable bounded automatic pivoting:

```console
mia investigate octocat --type username --name "Octocat research" \
  --pivot --max-depth 2 --max-targets 25
```

Append a later scan to the same case:

```console
mia investigate person@example.com --type email --case case-20260712-ab12cd34
```

Manage cases:

```console
mia case list
mia case show CASE
mia case note CASE "Manually verified the GitHub profile."
mia case add-evidence CASE ./document.pdf --note "Publicly published source"
mia case add-screenshot CASE ./capture.png --note "Page as viewed on 2026-07-12"
mia case dashboard CASE
mia case summarize CASE
mia case correlations CASE
mia case archive CASE
```

A case is stored under `~/mia_cases` by default:

```text
case-name-<id>/
├── case.yaml
├── case.db
├── notes.md
├── evidence/
├── screenshots/
├── scans/<scan-id>/
├── graph/
│   ├── graph.json
│   ├── graph.graphml
│   ├── graph.gexf
│   └── graph.mmd
├── timeline/
│   ├── timeline.json
│   ├── timeline.csv
│   └── timeline.md
├── reports/
│   ├── index.html
│   ├── assistant-summary.json
│   └── assistant-summary.md
└── exports/case.json
```

Read [`docs/WORKSPACES.md`](docs/WORKSPACES.md),
[`docs/EVIDENCE_GRAPH.md`](docs/EVIDENCE_GRAPH.md), and
[`docs/PIVOTING.md`](docs/PIVOTING.md).

## Evidence graph and confidence

Each normalized entity becomes a node. Examples include usernames, accounts,
emails, domains, IP addresses, phone numbers, certificates, breaches,
repositories, companies, URLs, documents, and metadata records.

Relationships are explicit edges such as `has_account`, `associated_email`,
`resolves_to`, `appeared_in`, or `triggered_scan`. Every relationship stores:

- source and target node IDs;
- a relation type and human-readable label;
- confidence score and label;
- plain-language reasons;
- structured factors explaining positive, negative, or neutral effects;
- provenance and attributes.

A displayed percentage is a prioritization heuristic, **not identity
probability**. Matching usernames alone do not prove that two records belong to
the same person. See [`docs/CONFIDENCE.md`](docs/CONFIDENCE.md).

## Automatic pivoting

Pivoting is off by default. MIA only queues explicit normalized indicators and
never treats a workflow edge as proof of common ownership.

```console
mia investigate TARGET --pivot --max-depth 2 --max-targets 25
```

Controls include:

- allowed target types;
- minimum source confidence;
- maximum recursion depth;
- maximum unique targets;
- child scan profile;
- duplicate and loop prevention;
- optional exclusion of lookalike domains;
- result caching.

Review every scope before enabling pivots. See [`docs/PIVOTING.md`](docs/PIVOTING.md).

## API integrations and credentials

Supported opt-in passive API adapters:

```text
Shodan · VirusTotal · Have I Been Pwned · SecurityTrails · Censys · Intelligence X
```

List their status:

```console
mia api list
```

Store a key in the operating-system keyring and enable the integration:

```console
mia api set shodan
mia api enable shodan
```

Environment variables are preferred in automation:

```console
export MIA_SHODAN_API_KEY='...'
export MIA_VIRUSTOTAL_API_KEY='...'
```

Keys are never written to MIA YAML, reports, subprocess command lines, or package
state. An explicit `--insecure-file` fallback exists for systems without a
usable keyring and writes a mode-0600 plaintext file after warning the user.

See [`docs/API_INTEGRATIONS.md`](docs/API_INTEGRATIONS.md).

## Evidence-grounded assistant

The default `local` provider is deterministic and network-free:

```console
mia case summarize CASE
```

Optional OpenAI-compatible, Gemini, and Ollama providers can be configured from
the CLI:

```console
mia assistant providers
mia assistant configure gemini --model gemini-3.5-flash --default
mia api set gemini

mia assistant configure ollama --model gemma3 --default
```

Local Ollama does not require a key. Gemini accepts `GEMINI_API_KEY`,
`GOOGLE_API_KEY`, or keyring storage through `mia api set gemini`. Remote
summaries receive bounded normalized evidence, not raw files by default.
Every returned factual statement must cite valid case node or edge IDs; invalid
or uncited statements are discarded. This reduces hallucination risk but does
not eliminate it. See [`docs/AI_ASSISTANT.md`](docs/AI_ASSISTANT.md).

## Classic scans remain available

The v3-style standalone scanner is preserved:

```console
mia scan octocat
mia scan octocat --quick
mia scan octocat --deep
mia username octocat --deep
mia email person@example.com
mia domain example.com
mia ip 203.0.113.10
mia phone '+46...'
mia image ./photo.jpg
mia file ./document.pdf
mia hash d41d8cd98f00b204e9800998ecf8427e
```

Commands do not begin with a dash: use `mia scan TARGET`, not
`mia -scan TARGET`.

## Optional OSINT package manager

MIA retains a declarative catalog of 40 third-party tools:

```console
mia pkg groups
mia pkg list
mia pkg info subfinder
mia pkg install --group username
mia pkg install subfinder gau waymore
mia pkg update --all
mia pkg uninstall blackbird
mia pkg doctor
```

Catalog presence means MIA knows an installation recipe. It does not mean the
upstream project is audited, currently maintained, safe for every environment,
or fully parsed into MIA reports. Read
[`docs/PACKAGE_MANAGER.md`](docs/PACKAGE_MANAGER.md) and
[`THIRD_PARTY.md`](THIRD_PARTY.md).

## Community plugin SDK

```console
mia plugin create my-plugin
mia plugin validate ./my-plugin
mia plugin install ./my-plugin --install-dependencies
mia plugin doctor
mia plugin list
mia plugin uninstall my-plugin
```

A generated plugin includes `manifest.yaml`, `plugin.py`, `README.md`, and tests.
The manifest declares a plugin version, compatible MIA range, target types,
Python requirements, MIA package-catalog dependencies, API services, license,
and homepage. See [`docs/PLUGIN_SDK.md`](docs/PLUGIN_SDK.md).

## Local knowledge and cache

Search exact and partial normalized entities observed in local cases:

```console
mia knowledge search alice@example.com
mia knowledge search example.com --json
```

Inspect or clear the plugin-result cache:

```console
mia cache status
mia cache clear
```

MIA correlations are exact normalized-value matches. They are suggestions for
review, not claims that different cases concern the same person or organization.

## Security boundaries

MIA uses `shell=False`, bounded output capture, process-group timeouts, HTML
escaping, private default permissions, isolated tool environments, and
credential separation. These are defense-in-depth controls, **not a sandbox**.
Third-party tools run with the current user's permissions and may contact remote
services according to their own behavior.

Cases, raw outputs, screenshots, API responses, and knowledge databases may
contain personal or sensitive information. Minimize collection, protect files,
respect authorization and applicable law, and delete data when no longer needed.

## Development

```console
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
ruff check .
ruff format --check .
```

MIA supports Python 3.11–3.13. See [`CONTRIBUTING.md`](CONTRIBUTING.md),
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), and
[`docs/PLUGIN_DEVELOPMENT.md`](docs/PLUGIN_DEVELOPMENT.md).
