# Profile verification

Username tools are discovery sources. A returned URL is a **candidate**, not a
confirmed account and never proof of ownership. MIA's verifier adds a second,
separate stage that asks whether the public page appears real and inspectable.

## Pipeline

```text
discovered candidate
  -> HTTP/API reachability
  -> soft-404/login-wall checks
  -> public metadata extraction
  -> bounded snapshot
  -> confidence constraint
  -> cross-profile comparison
```

## Statuses

- `verified`: a platform API returned a concrete account object.
- `likely`: several profile-specific page signals agree.
- `possible`: only one useful signal was available.
- `reachable`: the page loaded but did not identify the candidate account.
- `private`: authentication, CAPTCHA, or access controls prevented inspection.
- `suspended`: the platform reports a suspended/banned account.
- `soft_404`: the server returned a normal page containing a missing-profile
  indicator.
- `false_positive`: a reliable platform endpoint reported no account.
- `unverified` / `error`: the verifier could not reach a defensible conclusion.

## Platform adapters

The release includes dedicated public-data adapters for:

- GitHub public user objects;
- Roblox public username and user-detail APIs;
- Reddit public account metadata.

Other sites use a conservative generic HTML extractor. TikTok and similar sites
frequently return login walls or anti-bot pages, so MIA records that limitation
instead of treating a generic response as a verified profile.

## Extracted public fields

Where available, MIA records bounded normalized fields such as:

- canonical username and numeric platform ID;
- display name and biography/description;
- public location and external website links;
- account creation/update dates;
- public follower/repository/karma counters;
- account type, suspension state, and public badges;
- avatar SHA-256 and optional perceptual dHash.

Install the optional vision extra for perceptual avatar hashes:

```console
python -m pip install 'mia-osint[vision]'
```

The normal project installer may be used without this extra; exact image hashes
still work.

## Snapshots and change detection

Each verification creates a JSON snapshot under `snapshots/<node-id>/`. Repeated
verification compares normalized fields and records changes such as a modified
bio, display name, avatar, or linked website. HTML storage is disabled by
default and can be enabled explicitly with `verification.store_html`.

Verified account dates are added to the case timeline when they parse safely.

## Network safety

By default MIA rejects verifier requests to:

- localhost and local-only hostnames;
- private, loopback, link-local, reserved, multicast, and unspecified IPs;
- URLs containing embedded credentials;
- redirects to blocked destinations.

This reduces SSRF risk from malicious or malformed candidate URLs. The override
`verification.allow_private_networks` exists for controlled laboratories only
and should remain false for ordinary use.

## Run manually

```console
mia case verify CASE_ID
mia case cluster CASE_ID
mia case review CASE_ID
```

Verification remains passive HTTP/API inspection. It does not bypass login
walls, scrape private content, evade anti-bot systems, or prove that accounts
belong to one person.
