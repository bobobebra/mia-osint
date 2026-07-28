# Confidence heuristic

MIA's confidence score is a sorting aid. It is not a calibrated statistical
probability and must not be described as one.

## Inputs

The current normalizer considers:

- the adapter's source-level assessment;
- a configured reliability baseline;
- independent plugins that normalize to the same finding;
- positive, uncertain, or conflicting status;
- whether the evidence is direct local metadata or remote automation.

## Corroboration limits

Two tools may rely on the same website response, database, redirect, or shared
logic. MIA counts distinct plugins, but that does not guarantee independent
underlying evidence. Corroboration raises triage priority, not identity proof.

## Appropriate wording

Good:

> This URL was reported by Maigret and Sherlock and received a high MIA triage
> score. Manual verification is required.

Bad:

> MIA is 94% certain that the person owns the account.

## False-positive controls

- test known-unclaimed usernames;
- inspect final URLs and redirects;
- open profiles manually where lawful;
- compare profile content, dates, and identifiers;
- record network errors and blocks as unknown;
- retain raw evidence and tool versions.

## Relationship confidence in cases

Case graph edges carry structured factors with an effect, weight, and plain-language
explanation. Factors can raise, lower, or leave the relationship score unchanged.
A workflow edge such as `triggered_scan` uses a neutral factor and explicitly says
that the edge records an automated action rather than common ownership.

Cross-case correlations currently use exact normalized values and a confidence of
1.0 for the fact that the same normalized value was observed. That does **not** mean
the cases concern the same human or organization.
