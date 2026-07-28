# Report schema

`report.json` uses schema version `1.0` and contains one `ScanResult`.

Top-level fields include:

- `scan_id`, `target`, `target_type`, and `profile`;
- timestamps and duration;
- requested plugins and complete plugin-run records;
- normalized merged findings;
- generated report paths and scan warnings.

## Plugin run

Each run records command arguments, return code, timeout/truncation flags, raw paths, parser findings, warnings, and errors. The command is represented as an argument array rather than a shell string.

## Finding

Raw plugin findings contain:

- source plugin;
- category and semantic kind;
- title, value, and optional URL;
- status and source confidence;
- structured attributes;
- raw evidence path.

## Merged finding

MIA groups equivalent findings by a canonical deduplication key and records:

- sources and occurrence count;
- merged attributes and conflicts;
- confidence score, label, and human-readable reasons;
- all evidence paths.

Consumers should key integrations on `schema_version`, not the MIA application version.
