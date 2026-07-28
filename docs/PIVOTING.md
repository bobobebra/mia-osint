# Automatic pivoting

Automatic pivoting lets MIA follow explicit indicators discovered during a case.
It is disabled by default because follow-up requests can expand scope, consume
API quotas, and contact additional services.

## Enable it

```console
mia investigate octocat --type username --pivot
mia investigate octocat --pivot --max-depth 2 --max-targets 25
```

Configuration:

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

## Extraction rules

MIA considers:

- findings whose kind directly maps to an allowed target type;
- whitelisted structured attributes such as emails, domains, IP addresses,
  phones, usernames, and hashes;
- explicit email addresses embedded in URLs.

MIA does not automatically pivot to every hostname appearing in a URL. Lookalike
domains are excluded unless explicitly enabled.

## Limits and loop prevention

The queue tracks normalized `(target_type, target)` pairs. It will not enqueue a
visited target twice. It also enforces:

- maximum depth;
- maximum unique targets;
- minimum confidence;
- allowed target types;
- current case root as already visited.

Child scans use the configured lightweight profile by default and can reuse
cache entries.

## Graph representation

A child scan creates a workflow scan node connected to the evidence node that
triggered it. The edge explanation says that the link represents an automated
investigation action, not common identity or ownership.

## Scope guidance

Review allowed types and limits for every investigation. Use passive sources
where possible, exclude active or mixed tools unless authorized, and monitor API
quotas. Stop a running command with Ctrl+C; completed child scans already stored
in the case remain available.
