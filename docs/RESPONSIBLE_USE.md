# Responsible use

MIA aggregates public-source and locally supplied evidence. Aggregation can make otherwise scattered personal data easier to interpret, so use it with care.

## Appropriate uses

- reviewing your own public exposure;
- authorized security assessments and red-team engagements;
- fraud, brand, trust-and-safety, or incident investigations with a lawful basis;
- journalistic or academic research performed under applicable ethical and legal standards;
- metadata inspection of files you are authorized to examine.

## Prohibited project scope

MIA does not include credential attacks, password guessing, session theft, authentication bypass, malware delivery, exploit execution, automated rate-limit evasion, or covert persistence.

## Interpretation

- A username match does not establish common identity.
- Registration checks do not provide access to an account.
- WHOIS privacy proxies and stale records are common.
- DNS data changes over time.
- Metadata can be removed, rewritten, or forged.
- Captchas, blocking, and network errors must be treated as unknown.

Record the date, tool versions, raw evidence, and manual verification steps in any consequential investigation.

## Data handling

Raw outputs may include names, locations, contact hints, and identifiers. Use restrictive filesystem permissions, limit retention, encrypt sensitive case archives, and redact before sharing. Do not commit reports or the MIA SQLite database to a public repository.

## Multi-seed identity investigations

Putting usernames, emails, addresses, names, or locations in one Deep Case does
not establish that they refer to one person. Treat hypotheses and user-supplied
context as unverified. Do not use MIA to harass, stalk, discriminate, publish
private addresses, bypass access controls, or make automated adverse decisions.

Remote AI analysis can transmit normalized personal data and investigator notes
to the configured provider. Use the deterministic local provider for cases that
must remain on-device and follow all applicable privacy, employment, research,
and investigative policies.
