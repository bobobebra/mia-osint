# Roadmap

MIA is pre-1.0. Priorities can change after real-world testing.

## Current product structure

- **MIA Core** — shared backend, CLI, scanners, evidence model, storage, verification, correlation, API, and package inventory.
- **MIA Discover** — guided selector search and cautious public-account discovery.
- **MIA Workbench** — advanced cases, review, graph, timeline, evidence, packages, providers, and exports.

The two interfaces should continue to share one Core rather than duplicating investigation logic.

## 4.2 stabilization

- expand false-positive and soft-404 fixtures across high-traffic social platforms;
- document every confidence label and eliminate percentages that imply unsupported identity certainty;
- improve public-profile metadata extraction without treating ordinary outbound links as identity declarations;
- add manual accept/reject controls for candidate relationships in both interfaces;
- improve history migration for cases created by early alpha interfaces;
- reduce initial JavaScript bundle size and improve very large graph performance;
- add browser-level accessibility and responsive-layout regression tests;
- improve installer upgrade diagnostics and frontend asset verification;
- live-test GitHub, Roblox, Reddit, and generic profile verification against current public responses and anti-bot limitations.

## MIA Discover

- clearer selector-specific result layouts for usernames, emails, phones, names, and domains;
- stronger provenance cards showing exactly which tool produced each lead;
- compact comparison view for possible matching profiles;
- user-controlled search budgets and module explanations without exposing unnecessary complexity;
- exportable, redacted discovery summaries;
- better empty-state guidance when no relevant integration is installed.

## MIA Workbench

- graph merge/split tools and manual node creation;
- case-level bookmarks, decisions, annotations, and verification status;
- selective pivot preview and approval;
- richer timeline extraction and source-specific date semantics;
- improved case backup, redaction, deletion, and portable share bundles;
- pagination and virtualization for very large cases;
- clearer provider diagnostics on headless Linux.

## Plugin ecosystem

- signed community catalog metadata;
- reproducible plugin test fixtures;
- compatibility CI across supported MIA alpha ranges;
- plugin update commands and optional trust policies;
- clearer capability declarations for passive, active, mixed, and credentialed behavior.

## Not planned as silent defaults

- unbounded recursive crawling;
- stealth, evasion, credential attacks, exploitation, or intrusive scanning;
- automatic claims that two accounts belong to the same person;
- automatic remote AI transmission of raw evidence;
- hosted collection of user cases by the MIA project.
