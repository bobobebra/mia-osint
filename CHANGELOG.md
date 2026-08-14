# Changelog

## 4.2.0a10 — Verified unified installer release

- Unified Python, Linux, source, and Windows artifacts under one tag-driven release workflow.
- Prevented the standalone Windows workflow and portable release workflow from racing to create the same GitHub release.
- Added an actual silent install/uninstall smoke test for the generated Windows NSIS setup.
- Made Windows artifact and sidecar version checks derive from the Python package version instead of duplicated hard-coded values.
- Required every expected installer and package artifact to exist and pass SHA-256 verification before publishing the prerelease.

## 4.2.0a9 — Native Windows desktop port

- Added Windows-native `%LOCALAPPDATA%` and `%APPDATA%` storage while retaining one shared MIA Core.
- Added hidden Windows subprocess execution, process-tree cancellation, Windows virtual-environment paths, managed `.cmd` shims, and `winget` prerequisite support.
- Added platform capability reporting and a conservative `windows-core` starter group containing Maigret, Sherlock, and Holehe.
- Added a dedicated frozen desktop sidecar with dynamic localhost-port handshakes and no browser or console-window requirement.
- Replaced the proof-of-concept desktop scaffold with a Tauri launcher for Discover and Workbench, target-triple sidecars, per-user NSIS packaging, and WebView2 bootstrap handling.
- Added PyInstaller and PowerShell build scripts, sidecar smoke tests, Windows regression tests, and a `windows-2025` GitHub Actions build.
- Preserved Linux installation, interfaces, cases, reports, and package behavior without creating a Windows fork.

## 4.2.0a8 — Easier installation and desktop integration

- Added a self-extracting `MIA-Linux-Installer.run` release asset that embeds the complete source release and delegates to the verified isolated installer.
- Added `install-mia.sh`, a small GitHub-release bootstrapper with optional SHA-256 verification.
- Added current-user Linux application-menu entries for MIA Discover and MIA Workbench with their separate product icons.
- Added `mia desktop install`, `mia desktop status`, and `mia desktop remove`.
- Added `mia repair` to validate state directories, database access, packaged UI assets, plugin availability, desktop launchers, and optionally the recommended tool set.
- Added installer options `--no-desktop` and `--launch discover|workbench`.
- Added transactional managed-environment upgrades that restore the previous MIA environment when installation or version verification fails.
- Updated uninstall behavior to remove MIA-managed desktop entries without deleting cases or reports.
- Added release and CI support for the one-file Linux installer and checksum assets.
- Added initial Tauri/PyInstaller Windows desktop packaging scaffolding while retaining one shared MIA Core.

## 4.2.0a8 — Dashboard, application icons, and AI cost guard

- Replaced MIA Discover's landing-page-style home screen with a task-focused search dashboard.
- Removed promotional copy, unlimited/free-search badges, feature-selling panels, and redundant onboarding text from the installed interface.
- Added separate modern application icons for MIA Discover and MIA Workbench, including header marks, SVG favicons, and installable 192/512 px web-app assets.
- Added platform-specific username seeds for TikTok, Instagram, X, GitHub, Reddit, Roblox, YouTube, Twitch, Pinterest, Facebook, Threads, Bluesky, Telegram, VK, Steam, SoundCloud, and Snapchat.
- Reduced interface launch commands to `mia discover` and `mia workbench`; removed `mia ui`, `mia discover ui`, and `mia workbench ui`.
- Split result review into no-AI `Verify & compare` and optional `Explain with AI` actions.
- Added a server-side cost guard: Gemini or any external provider cannot run without an explicit per-request confirmation.
- Added a bounded profile-page evidence context for optional AI review using parsed public metadata, verification reasons, and contradictions rather than raw HTML.
- Updated settings to show which providers are offline or external and whether they may use billable API quota.

## 4.2.0a5 — Account-link false-positive hardening

- Restricted imported identity links to author-declared `rel=me`, JSON-LD `sameAs`, and dedicated profile website fields.
- Rejected ordinary page navigation, documentation, support, business, and user-content links as identity evidence.
- Reworked MIA Discover result cards to distinguish page verification from identity association.
- Added cleanup of legacy false `public-profile-link` nodes during rerun or guided review.
- Added regression coverage for GitHub Gist links, unrelated Sketchfab accounts, and X support/business URLs.

## 4.2.0a4 — MIA Discover dual-interface release

- Added a separate **MIA Discover** React interface on top of the existing MIA Core and API.
- Added `mia discover` and `mia discover ui`, defaulting to localhost port 8766, while preserving `mia ui` on port 8765.
- Added one-box selector lookup with automatic username, email, phone, name, domain, and profile-URL detection.
- Added Quick, Standard, and Deep search modes, live WebSocket progress, result metrics, grouped account cards, additional-data cards, local history, graph exploration, raw evidence, and one-click guided review.
- Reused the existing case store, scanners, account discovery, verification, identity clustering, AI providers, operations, and safety boundaries instead of forking the backend.
- Packaged both frontend bundles in the Python wheel and source archive, with regression tests for both UI variants and CLI launch forms.

## 4.2.0a3 — Public account discovery

- Added a dedicated beginner-first **Find matching accounts** workflow.
- Recognizes public TikTok, Instagram, X/Twitter, Threads, YouTube, Reddit, GitHub, Twitch, Pinterest, Snapchat, Facebook, Bluesky, Telegram, VK, Roblox, Steam, and SoundCloud profile URLs and extracts scan-ready handles.
- Added bounded, conservative handle variants for separator and short trailing-number differences, with lower confidence and explicit explanations.
- Imports explicit public cross-profile links as account candidates and verifies newly linked profiles without rechecking the whole case.
- Added strong but non-conclusive direct-link evidence, weak formatting-variant evidence, platform/username normalization in Maigret and Sherlock results, and a dedicated possible-account result grid.
- Added configuration limits for generated leads and public-link hops plus focused parser, expansion, graph, and identity-scoring tests.

## 4.2.0a2 — Beginner-first local workspace UI

- Reworked the default UI for non-technical users with plain-language navigation, a one-box search builder, automatic clue-type detection, and advanced settings hidden by default.
- Added a one-click **Check and explain everything** workflow that verifies candidate profiles, compares similarities and contradictions, and uses the configured AI provider or the private local fallback.
- Renamed case tabs and actions in plain language while preserving the full advanced graph, timeline, package, evidence, and provider controls.
- Added Uvicorn's standard WebSocket dependencies to the core package so live scan, package, and AI-operation progress works immediately after installation.
- Removed the frontend's external Google Fonts request so the local UI remains self-contained.
- Added WebSocket-stream and guided-review regression tests.

## 4.1.0-alpha.1 — 2026-07-12

- Added `mia deeps`, a persistent multi-seed investigation mode for usernames, emails, domains, IPs, phones, people, companies, addresses, locations, URLs, hashes, certificate fingerprints, and files.
- Added YAML/JSON Deep Case manifests, a starter-template generator, generic `TYPE=VALUE` seeds, seed de-duplication, hypotheses/notes, context-only indicators, and batch append to existing cases.
- Added separate candidate-profile verification with conservative generic HTML checks and dedicated GitHub, Roblox, and Reddit public-data adapters.
- Added bounded verification snapshots, field-change detection, optional HTML retention, account-date timeline events, and private-network/localhost/unsafe-redirect blocking.
- Added explainable identity clustering based on external links, exact and perceptual avatar hashes, names, locations, biographies, and account type, while strictly capping username-only evidence.
- Added contradiction edges, isolated/weak/false-positive review tasks, persistent review resolution, and dashboard sections for seeds, verification, clusters, and analysis.
- Added sequential evidence-grounded analyst, profile-reviewer, skeptic, verifier, planner, cluster-critic, and final-synthesis workflows.
- Added quick, standard, thorough, and exhaustive analysis depths; later passes now receive bounded grounded output from earlier passes.
- Added per-run reasoning effort controls. Gemini 3 uses `thinkingLevel`; Gemini 2.5 receives a compatible `thinkingBudget`; Ollama receives its supported thinking flag.
- Added bounded remote-model context, a private-network verification guard, optional Pillow perceptual hashing, new documentation, and regression tests for the complete Deep Case workflow.

### Closed-test hardening

- Preserved existing Deep Case workflow, description, tags, notes, hypotheses, and seeds when appending a new batch.
- Added accurate total-versus-new seed counts and de-duplication scoped by optional candidate subject.
- Added candidate-subject context nodes and explicit non-evidentiary subject-context edges.
- Replaced stale derived identity edges on re-clustering and surfaced strong negative relationships inside transitive clusters.
- Improved profile verification for GitHub and Roblox API errors, visible-text soft-404 detection, private-network blocking, and unsafe redirects.
- Bounded assistant attributes, filtered raw-response-like fields, and strengthened prompt-injection handling for evidence strings.
- Added focused tests for Deep Case manifests, batch appends, snapshots, clustering, contradictions, manual review, and sequential multi-pass Gemini analysis.

## 4.0.0-alpha.5 — 2026-07-12

- Fixed executable-name collisions by preferring MIA-managed paths and validating tool-specific version signatures; Python's unrelated `httpx` CLI is no longer accepted as ProjectDiscovery httpx.
- Enforced Intelligence X's metadata-only policy for both successful raw responses and HTTP error bodies.
- Closed SQLite connections deterministically across scan history, cache, knowledge, and case databases; also closed replaced file-log handlers.
- Replaced traceback-heavy community-plugin ID failures with concise CLI validation errors.
- Rejected unknown API service names before modifying configuration or credential storage.
- Added a supported CLI path for switching the default assistant back to the deterministic `local` provider.
- Rolled back newly created case workspaces when root plugin selection or the root scan fails.
- Made classic scans exit non-zero when no plugin completes successfully, with an explicit `--allow-empty` override for automation that expects empty/degraded results.
- Rejected blank `--case` identifiers and unsupported package-manager overrides consistently.
- Corrected package progress wording (`Updating`) and clarified that updating an absent tool installs it.
- Repaired six catalog recipes found during live Bazzite testing: Findomain release archives, basic dnstwist installation without compiled optional extras, WhatWeb from its Git/Ruby entry point, PhoneInfoga release archives, the VirusTotal CLI Go command package, and cloud_enum's uv project layout.
- Added archive traversal/symlink protections to release-binary extraction.
- Added regression and fixture tests for every audited defect, package archive installation, Git/Ruby wrappers, current uv-project layouts, and ResourceWarnings.

## 4.0.0-alpha.4 — 2026-07-12

- Added live Rich package-operation progress with overall percentage, queue position, elapsed time, current activity, bounded output, and quiet/verbose modes.
- Streamed Go, Cargo, uv, Git, and system-package output instead of buffering it until completion.
- Added heartbeats for silent builds, private per-tool logs, clean process-group cancellation, exit code 130, and partial summaries after interruption.
- Continued package operations after individual failures and produced duration-aware final outcome tables.

## 4.0.0-alpha.3 — 2026-07-12

- Fixed upgrades from an existing MIA installation: the installer now backs up the old core virtual environment, creates a clean replacement, verifies the new version, and rolls back automatically on failure.
- Replaced `python -m pip check` with `uv pip check --python`, because uv-created virtual environments do not necessarily contain the `pip` module.
- Made installer command failures visible in the terminal with a bounded log excerpt instead of stopping silently after redirecting details to the install log.
- Added PATH-shadowing diagnostics when another `mia` launcher appears before the newly installed command.
- Added installer regression tests for successful upgrades and rollback behavior.
- Added the missing `pytest-asyncio` development dependency required by the assistant-provider test suite.

## 4.0.0-alpha.2 — 2026-07-12

- Added first-class Google Gemini and Ollama assistant providers alongside the existing local and OpenAI-compatible providers.
- Added a shared evidence payload, JSON schema, and citation-validation path for every remote provider.
- Added Gemini `generateContent` requests with JSON-schema output and `x-goog-api-key` authentication.
- Added local and cloud Ollama chat support, local JSON-schema structured output, keyless localhost operation, and optional bearer authentication.
- Added `mia assistant providers` and `mia assistant configure` for non-secret provider configuration.
- Added one-off `--model` and `--endpoint` overrides to `mia case summarize`.
- Added Gemini and Ollama keyring/environment integration, including standard environment-variable aliases.
- Preserved alpha.1 OpenAI-compatible configuration fields and public method compatibility.
- Added provider request, grounding rejection, credential alias, configuration, and CLI tests.

## 4.0.0-alpha.1 — 2026-07-12

- Added persistent case workspaces with private directories, `case.yaml`, case-local SQLite, notes, scans, evidence, screenshots, graph, timeline, reports, logs, and exports.
- Added `mia investigate` with root scans, case append mode, bounded automatic pivoting, cache control, and case dashboard generation.
- Added typed evidence nodes, explainable relationship edges, confidence factors, stable IDs, and JSON/GraphML/GEXF/Mermaid exports.
- Added timeline extraction from structured dates plus JSON, CSV, and Markdown timeline exports.
- Added the shared local knowledge database, exact cross-case correlation suggestions, and `mia knowledge search`.
- Added the self-contained offline case dashboard with graph, timeline, entity filtering, statistics, notes, attachments, screenshots, plugin logs, bounded raw evidence excerpts, assistant output, and exports.
- Added deterministic local summaries and an optional OpenAI-compatible evidence-grounded assistant that rejects malformed, uncited, and unknown-ID statements.
- Added opt-in Shodan, VirusTotal, HIBP, SecurityTrails, Censys, and Intelligence X metadata adapters.
- Added environment/keyring credential handling and `mia api` lifecycle commands.
- Added the community plugin SDK, manifest versioning, compatibility ranges, dependency declarations, scaffolding, validation, installation, health checks, and uninstall commands.
- Added persistent plugin-result caching and cache inspection/clear commands.
- Preserved classic v3 scans, reports, history, package manager, and cross-distribution installer behavior.
- Hardened dashboard JSON embedding against script-terminator injection and retained offline HTML escaping.
- Added v3-to-v4 migration, workspace, graph, pivoting, API, assistant, and plugin SDK documentation.

## 3.4.0-alpha.1 — 2026-07-11

- Added the `mia pkg` optional OSINT package manager with list, groups, info,
  install, uninstall, update, doctor, JSON inventory, and dry-run commands.
- Added a declarative 40-tool catalog with integration, risk, API/setup,
  maintenance, license, target, and installation metadata.
- Added isolated Python, uv-project, Go, Cargo, Git/Python, system-package,
  Holehe, and SpiderFoot install recipes.
- Added package groups for core, username, email, domain, phone, metadata, API,
  cloud, frameworks, and passive tooling.
- Added full adapters for Subfinder, Assetfinder, gau, httpx, and dnstwist.
- Added conservative raw adapters for Blackbird, Social Analyzer, theHarvester,
  and PhoneInfoga.
- Changed the installer to delegate optional tool installation to `mia pkg`.
- Added `--with`, `--tool`, `--all-tools`, and `--include-mixed` installer options.
- Made unavailable optional profile plugins skip cleanly while preserving
  explicit missing-tool diagnostics.
- Added package state, targeted uninstall, system-package preservation, command
  backups, expected-executable checks, failed-install cleanup, and protection
  for user-replaced commands.
- Fixed duplicate package-group expansion and Bash `GROUPS` variable collision.
- Added package-manager, catalog, CLI, parser, registry, installer, and uninstall
  safety tests.
- Expanded public documentation, third-party inventory, supply-chain warnings,
  contribution guidance, and release transparency.

## 3.3.0-alpha.1 — 2026-07-11

- Prepared the project for an honest public GitHub alpha release.
- Added prominent vibe-coding and AI-assistance disclosure in the README, CLI,
  release documentation, and contribution policy.
- Reclassified the package from beta to alpha (`3.3.0a1`).
- Added MIT/open-source release documentation, disclaimer, notice, code of
  conduct, support guide, roadmap, citation file, and maintainer checklist.
- Added complete architecture, CLI, configuration, confidence, threat-model,
  installation, plugin-development, and troubleshooting documentation.
- Reworked the full installer for Debian/Ubuntu (`apt`), Fedora/RHEL (`dnf`),
  Arch (`pacman`), openSUSE (`zypper`), Alpine (`apk`), and Homebrew Linux.
- Added immutable Fedora-family detection and Homebrew preference.
- Added user-owned managed Python runtimes through a constrained uv bootstrap,
  avoiding `sudo pip`, system-Python mutation, and PEP 668 conflicts.
- Added package-manager override and system-package skip options.
- Made ExifTool and WHOIS host packages best-effort so missing optional
  repository packages do not abort the core installation.
- Added GitHub Actions CI/release workflows, Dependabot, issue templates, and a
  pull-request template.
- Added `mia about` to show alpha status and responsible-use boundaries.

## 3.2.0 — 2026-07-11

- Fixed Maigret simple-JSON parsing when site metadata is serialized as a
  dictionary key.
- Replaced raw site dictionaries in reports with friendly labels.
- Enabled unconditional Jinja HTML escaping and defensive title sanitization.
- Added balanced `default`, `quick`, `deep`, and `all` scan profiles and flags.
- Added `mia profiles`.

## 3.1.0 — 2026-07-11

- Added the first full host installer for MIA and external tools.
- Isolated Python OSINT applications in separate environments.
- Added stable Holehe and SpiderFoot wrappers.

## 3.0.0 — 2026-07-11

- Complete Python rewrite with typed plugin API and autodiscovery.
- Added Maigret, Sherlock, SpiderFoot, Holehe, ExifTool, WHOIS, DNS, and hash
  plugins.
- Added normalized findings, duplicate merging, confidence explanations,
  reports, SQLite history, diagnostics, and tests.
