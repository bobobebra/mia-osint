# MIA — find and organize public information

> [!WARNING]
> **MIA is new and experimental.** Much of the project was built with AI
> assistance, then reviewed and tested by a human. It has not been independently
> audited, and it can still contain bugs or return incomplete and incorrect
> results. Treat everything it finds as a lead to check yourself, not as proof.

MIA helps you search for publicly available information and keep the results
organized on your own computer. It brings several OSINT tools and optional data
services into one place, cleans up their output, connects related findings, and
builds an offline dashboard you can return to later.

The useful part is what happens **after** a search finishes. MIA remembers where
each result came from and lets you review connections, timelines, notes,
attachments, screenshots, and earlier searches without juggling a pile of
separate reports.

MIA has three parts:

- **MIA Core** runs searches and stores the results;
- **MIA Discover** gives you a simple guided search for public accounts and
  other information;
- **MIA Workbench** is the larger workspace for cases, notes, graphs, files,
  and deeper review.

```console
mia investigate octocat --type username --name "Octocat research" --pivot
```

## Project status

- Release: **4.2.0 alpha 10** (`4.2.0a10`)
- Stability: **early alpha — expect rough edges**
- Development: **built with substantial AI assistance and human review**
- Independent audit: **not yet**
- Accuracy: **important findings must be checked manually**
- Compatibility: **Windows 11 and common Linux distributions are the main focus**
- License: **MIT**

Read [`AI_DISCLOSURE.md`](AI_DISCLOSURE.md), [`DISCLAIMER.md`](DISCLAIMER.md),
[`SECURITY.md`](SECURITY.md), and
[`docs/RESPONSIBLE_USE.md`](docs/RESPONSIBLE_USE.md) before use.

## What MIA can do

MIA can:

- keep each search in a reusable case with notes, screenshots, files, logs,
  and reports;
- show findings and their connections in an interactive graph and timeline;
- explain why a possible connection looks stronger or weaker;
- follow selected public clues automatically while staying inside limits you
  choose;
- notice exact matches that appeared in earlier local cases;
- create an offline dashboard for reviewing and sharing a case;
- summarize a case locally, or use an optional AI provider when you choose;
- connect to optional services such as Shodan, VirusTotal, Have I Been Pwned,
  SecurityTrails, Censys, and Intelligence X;
- install and manage a catalog of optional OSINT tools;
- support community plugins without mixing them into MIA Core.

See [`RELEASE_NOTES.md`](RELEASE_NOTES.md) and
[`docs/MIGRATION_V3_TO_V4.md`](docs/MIGRATION_V3_TO_V4.md).

Version 4.2 alpha 9 adds the native Windows app and installer. Earlier alpha
releases added the one-file Linux installer, application-menu shortcuts,
automatic repair, the guided Discover interface, clearer account matching, and
confirmation before sending data to an external AI service.

The simple interface is designed around finding public accounts. You can paste a
public profile URL, check sensible username variations, and keep links that one
profile openly provides to another. A matching or similar username is still only
a possible lead; it does not prove that two accounts belong to the same person.


## Bring related clues into one case

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

MIA keeps newly discovered profile links as unconfirmed until it can check the
public page or public platform API. GitHub, Roblox, and Reddit have dedicated
connectors. Other websites use careful page checks and small snapshots. A
matching username by itself is always treated as weak evidence.

Group possible matches and open the review queue:

```console
mia case verify CASE_ID
mia case cluster CASE_ID
mia case review CASE_ID
```

Ask MIA to summarize the case while citing its stored findings:

```console
mia case analyze CASE_ID --depth thorough
mia case analyze CASE_ID --depth exhaustive --provider gemini --thinking-level high
```

When you choose a remote AI provider, MIA sends a limited, organized summary of
the case. That summary can still contain personal information. Use the local
provider when the case needs to stay entirely on your computer.

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

Each interface has one launch command. Older commands such as `mia ui` were
removed in alpha 7.

MIA Discover recognizes what you enter, offers Quick, Standard, and Deep search
modes, shows live progress, groups results into readable cards, and keeps a
local history. MIA Workbench adds larger cases, uploaded files, review queues,
graphs, timelines, optional-tool management, AI settings, and exports.

Both bind to localhost by default. See [docs/UI.md](docs/UI.md).

## Quick start

### Windows desktop installer

Download the x64 installer from the GitHub release:

```text
MIA-4.2.0-alpha.10-Windows-x64-Setup.exe
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
unzip MIA-v4.2.0-alpha.10.zip
cd mia-osint-4.2.0-alpha.10
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

Start a case with one search:

```console
mia investigate octocat --type username --name "Octocat research"
```

Let MIA follow related public clues, with limits:

```console
mia investigate octocat --type username --name "Octocat research" \
  --pivot --max-depth 2 --max-targets 25
```

Add another search to the same case later:

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

By default, MIA stores each case under `~/mia_cases`:

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

MIA turns each useful finding into a point on the graph. A point might be a
username, account, email address, domain, phone number, company, URL, document,
repository, or metadata record.

Lines between those points show how MIA found a possible connection. Every
connection keeps:

- the two findings it connects;
- a readable connection type;
- a confidence label and score;
- plain-language reasons for the score;
- the source of the information and any useful details.

The percentage helps you decide what to review first. It is **not** the chance
that two accounts belong to the same person. A matching username alone proves
nothing. See [`docs/CONFIDENCE.md`](docs/CONFIDENCE.md).

## Automatic pivoting

Automatic follow-up searches are off by default. When enabled, MIA only follows
clear, supported clues and never treats a connection as proof that two records
have the same owner.

```console
mia investigate TARGET --pivot --max-depth 2 --max-targets 25
```

You choose:

- which kinds of clues MIA may follow;
- how strong a clue must be;
- how many steps and unique searches it may run;
- which search mode follow-up searches use;
- whether to exclude lookalike domains.

MIA avoids duplicate loops and reuses recent results when possible.

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

Save a key in your operating system's secure key store and enable the service:

```console
mia api set shodan
mia api enable shodan
```

Environment variables are preferred in automation:

```console
export MIA_SHODAN_API_KEY='...'
export MIA_VIRUSTOTAL_API_KEY='...'
```

MIA does not put API keys in its configuration files, reports, command lines,
or package records. If a secure key store is unavailable, there is an explicit
`--insecure-file` fallback that warns you before creating a private plaintext
file.

See [`docs/API_INTEGRATIONS.md`](docs/API_INTEGRATIONS.md).

## Evidence-grounded assistant

The default local summary works without an internet connection:

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
`GOOGLE_API_KEY`, or secure key storage through `mia api set gemini`. Remote
summaries receive an organized selection of case findings, not raw files by
default. MIA requires each factual statement to point back to a stored finding
and drops statements that do not. This helps, but AI can still make mistakes.
See [`docs/AI_ASSISTANT.md`](docs/AI_ASSISTANT.md).

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

If a tool appears in the catalog, MIA knows one way to install it. That does not
guarantee that the tool is audited, actively maintained, safe on every system,
or fully understood by MIA. Read
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
Its manifest records the version, supported MIA versions and input types,
dependencies, API services, license, and homepage. See
[`docs/PLUGIN_SDK.md`](docs/PLUGIN_SDK.md).

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

MIA only links cases here when the cleaned values match exactly. These matches
are suggestions to review, not claims that two cases involve the same person or
organization.

## Security boundaries

MIA avoids shell command interpolation, limits captured output, stops tools that
run too long, escapes report content, keeps files private by default, and
separates credentials. These protections reduce risk, but MIA is **not a
sandbox**. Optional third-party tools still run with your account's permissions
and may contact their own online services.

Cases, original results, screenshots, API responses, and local history can
contain personal information. Collect only what you need, protect the files,
respect the law and other people's privacy, and delete the data when you are
finished with it.

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
