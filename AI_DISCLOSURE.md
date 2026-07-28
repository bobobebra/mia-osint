# AI and vibe-coding disclosure

MIA is intentionally described as **vibe-coded**.

## What that means

A substantial portion of the project's architecture, implementation, tests,
installer logic, and documentation was drafted or transformed with generative
AI assistance. Human direction, review, testing, and revisions were applied,
but that process is not equivalent to a professional security audit, formal
verification, or long-term maintenance by domain experts.

## What users should assume

Users should assume that:

- plausible-looking code may still contain subtle defects;
- tests may encode the same mistaken assumptions as the implementation;
- upstream output formats may not be represented completely;
- Linux distribution support may fail on an untested derivative or release;
- security controls may be incomplete;
- documentation may lag behind behavior;
- confidence values may be misunderstood or miscalibrated;
- third-party tools may change without notice.

## Human-review expectation

Before using MIA in consequential work:

1. Review the source and configuration.
2. Pin and review third-party tool versions.
3. Test with known fixtures and negative controls.
4. Inspect raw output rather than trusting only normalized results.
5. Independently verify every significant lead.
6. Apply your organization's legal, privacy, and security review.

## Contribution disclosure

Contributors are welcome to use AI-assisted tools, but they remain responsible
for every submitted line. Pull requests should disclose meaningful AI use,
include tests, identify uncertainty, and avoid claims that cannot be supported.
Generated code must not introduce incompatible licensing or copied proprietary
material.

## No authorship concealment

This document exists so that the project's development process is not hidden or
marketed as something it is not. The label “vibe-coded” is not a quality claim;
it is a warning to review, test, and verify.

## Package-manager disclosure

The optional-tool catalog and many installation recipes were also created with
AI assistance. A plausible package name, executable, or build command can still
be wrong, stale, maliciously squatted, or incompatible with a current upstream
release. Catalog review and automated dry runs do not replace inspecting the
canonical upstream source and resolved dependencies before installation.

## AI assistant disclosure

MIA v4 includes a deterministic local summary and an optional OpenAI-compatible
provider. The remote provider is constrained to cite existing evidence IDs and MIA
discards malformed, uncited, or unknown-ID statements. This is a safety mechanism,
not a guarantee against hallucination, prompt injection in source data, provider
retention, or mistaken interpretation. Remote AI is optional and normalized evidence
can still contain personal information.
