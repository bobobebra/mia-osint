# Deep Cases (`mia deeps`)

Deep Cases collect many heterogeneous leads into one persistent investigation.
They are intended for situations where the investigator already has several
possible usernames, emails, domains, phone numbers, files, names, locations, or
other context and needs MIA to search, normalize, compare, and explain them as a
single case.

A supplied seed is **context, not proof**. MIA records why an item entered the
case and never treats co-membership in a Deep Case as evidence that all items
belong to the same person or organization.

## Create a case from command-line inputs

```console
mia deeps --name "Example identity review" \
  --username example_handle \
  --username example_handle_2 \
  --email person@example.com \
  --domain example.com \
  --person "Example Person" \
  --address "Potential address supplied by the investigator" \
  --location "Stockholm" \
  --hypothesis "The GitHub and Reddit profiles may be related" \
  --workflow identity
```

All repeatable seed options can be mixed in one command. Additional forms:

```console
mia deeps --name "Mixed case" --hash HASH --certificate FINGERPRINT
mia deeps --name "Mixed case" --seed company="Example AB" --seed url=https://example.com/profile
mia deeps --name "File review" --file ./document.pdf --file ./image.jpg
```

Generic seeds use `TYPE=VALUE`. Supported types are the values shown by the CLI,
including `username`, `email`, `domain`, `ip`, `phone`, `person`, `company`,
`address`, `location`, `url`, `hash`, `certificate`, and `file`.

## Append a batch to an existing case

```console
mia deeps --case CASE_ID \
  --email another@example.com \
  --username another_handle \
  --address "New context" \
  --hypothesis "This may connect to the existing subject"
```

MIA de-duplicates normalized seeds already present in the workspace. Existing
case data is preserved and only new scannable seeds are collected.

## Manifest files

Generate a starter manifest:

```console
mia deeps --write-template deep-case.yaml
```

Run it:

```console
mia deeps deep-case.yaml
```

Example:

```yaml
schema_version: "1.0"
name: Example multi-seed investigation
workflow: identity
description: Lawful, authorized public-source review.
tags: [example]
hypotheses:
  - The supplied accounts may be related; this remains unverified.
notes: |
  Record scope, authorization, known facts, and limitations here.
seeds:
  - target: example_handle
    target_type: username
    label: Known username
    confidence: 1.0
    subject: primary
  - target: person@example.com
    target_type: email
    label: Potential email
    confidence: 0.6
    notes: Unverified lead.
  - target: Example City
    target_type: location
    label: Context only
    confidence: 0.5
```

Friendly top-level shorthand is also supported:

```yaml
name: Example
usernames: [example_handle, example_handle_2]
emails: [person@example.com]
domains: [example.com]
addresses:
  - Potential address context
locations: [Stockholm]
```

## Workflows

Use `mia workflows` for the live reference.

- `identity`: profile verification, account comparison, clustering,
  contradictions, and manual review.
- `general`: mixed-indicator collection without assuming one identity.
- `email-enrichment`: email-centered collection; profile verification is skipped
  unless explicitly requested.
- `domain-recon`: domain/infrastructure-centered collection; identity profile
  verification is skipped by default.
- `timeline`: emphasizes dated findings and chronological exports.

Automatic pivots are bounded by depth, target count, allowed types, confidence,
and a visited set:

```console
mia deeps case.yaml --max-depth 2 --max-targets 75
mia deeps case.yaml --no-pivot
```

## Verification and analysis

Identity workflows pass discovered profile candidates through passive
verification before clustering. Disable that step with `--no-verify`.

Run a multi-pass analysis after collection:

```console
mia deeps case.yaml --analyze --analysis-depth thorough
mia deeps case.yaml --analyze --analysis-depth exhaustive \
  --provider gemini --thinking-level high
```

Remote analysis receives normalized case evidence and bounded investigator
context, which can include names, emails, addresses, notes, and hypotheses. Do
not use a remote provider for information you are not authorized to transmit.
The `local` provider keeps data on the machine.

## Case layout

Deep Cases use the normal MIA workspace plus:

```text
case-root/
├── deep-case.yaml
├── snapshots/
├── analysis/
├── reports/investigation-analysis.{json,md}
└── exports/deep-case-result.json
```

The SQLite case database stores seeds, verifications, clusters, review tasks,
and analysis runs. The offline dashboard exposes the same normalized records.
