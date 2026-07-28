# Threat model

## Assets

- local reports and raw OSINT output;
- SQLite history;
- configuration and executable paths;
- user identity and network address;
- files supplied for metadata analysis;
- integrity of normalized findings.

## Adversaries and hazards

- malicious or compromised upstream packages;
- hostile output designed to break parsers or HTML;
- unexpected redirects and oversized responses;
- malicious local configuration;
- accidental disclosure through Git, cloud sync, or support logs;
- false attribution caused by parser or normalization defects;
- supply-chain changes after installation.

## Existing controls

- subprocess argument arrays with no shell interpolation;
- process-group timeouts and cancellation;
- bounded stdout/stderr capture;
- separate raw evidence directories;
- HTML escaping and defensive title handling;
- user-owned environments rather than root execution;
- restrictive permissions where supported;
- no embedded web server in MIA;
- no automatic third-party updates during scans.

## Out of scope or incomplete

- strong sandboxing of third-party tools;
- reproducible builds of every upstream dependency;
- signed plugin ecosystem;
- malicious package-manager mirrors;
- endpoint compromise;
- multi-user isolation;
- encrypted report storage;
- formal parser verification.

Run MIA as a dedicated unprivileged user for higher-risk work and isolate the
host according to your organization's policy.
