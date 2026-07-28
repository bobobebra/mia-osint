# Investigation workspaces

A workspace is a persistent local case. Unlike a standalone report, it can be
updated by multiple scans and manual evidence imports.

## Create or update

```console
mia case create "Case name" --description "Authorized public-source review" --tag demo
mia investigate octocat --type username --case CASE
```

Creating directly from a root target is usually simpler:

```console
mia investigate octocat --type username --name "Octocat research"
```

## Layout

```text
<case>/
├── case.yaml              human-readable metadata
├── case.db                authoritative case SQLite database
├── notes.md               append-only user notes
├── evidence/              copied manual evidence
├── screenshots/           copied images
├── scans/                 complete per-scan reports and raw plugin output
├── graph/                 JSON, GraphML, GEXF, Mermaid
├── timeline/              JSON, CSV, Markdown
├── reports/               offline dashboard and assistant summaries
├── exports/case.json      normalized portable case payload
└── logs/
```

Directories and databases are created with private user permissions where the
host filesystem supports them.

## Notes and attachments

```console
mia case note CASE "Verified manually against the public profile."
mia case add-evidence CASE ./public-document.pdf --note "Source URL recorded in notes"
mia case add-screenshot CASE ./page.png --note "Captured 2026-07-12"
```

MIA copies the file into the case, calculates SHA-256, stores size and note
metadata, and displays the attachment in the dashboard. A digest proves file
consistency, not authenticity or lawful provenance.

## Case identifiers

Commands accept a full case ID, unambiguous ID prefix, slug, or exact case name.
Ambiguous identifiers fail rather than selecting silently.

## Archive

```console
mia case archive CASE
mia case archive CASE --reopen
```

Archiving hides a case from the default list without deleting data or knowledge
records.

## Rebuild outputs

```console
mia case dashboard CASE
```

This regenerates graph exports, timeline exports, the normalized case JSON,
local assistant summary, correlations, and the offline dashboard from the case
database.

## Portability and privacy

`exports/case.json`, graph files, timeline files, reports, and attachments can
contain personal information. Review and redact before sharing. Raw plugin
artifacts remain in each scan directory and may contain more data than the
normalized export.

## Deep Case records

Deep Cases add `deep-case.yaml`, profile snapshots, identity clusters, manual
review tasks, and analysis runs. These are persisted in the case SQLite database
and included in `exports/case.json` and the offline dashboard. Appending a new
Deep Case batch de-duplicates existing seeds and does not rescan unchanged inputs.
