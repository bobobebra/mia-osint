# MIA interfaces

MIA ships as one installation with three clearly separated layers:

- **MIA Core** is the shared Python backend, CLI, scanners, normalization, verification, correlation, storage, package inventory, API, and operation engine.
- **MIA Discover** is the guided selector-search interface for straightforward public-source discovery.
- **MIA Workbench** is the advanced investigation interface for Deep Cases, evidence review, graphs, timelines, packages, providers, and detailed controls.

Both interfaces use the same MIA Core state. Searches, cases, installed tools, provider settings, and evidence remain available whichever interface is opened.

## MIA Discover

```bash
mia discover
```

The default address is `http://127.0.0.1:8766`. Discover opens directly to a task dashboard with:

- username, email, phone, name, domain, and public-profile URL input;
- automatic selector detection and manual type override;
- an optional starting-platform selector for username searches;
- Quick, Standard, and Deep scan modes;
- live operation progress, saved-search history, result cards, graph, and raw evidence;
- separate **Verify & compare** and **Explain with AI** actions.

A normal search does not invoke Gemini or another AI provider. **Verify & compare** performs profile verification and clustering without AI. **Explain with AI** asks the user to select a provider. External providers require a confirmation on every run because the configured account may apply quota or charges.

Before optional AI analysis, MIA Core parses bounded public profile evidence such as usernames, display names, biographies, locations, page titles, canonical URLs, identity links, response status, verification reasons, and contradictions. It sends that evidence summary rather than raw HTML. Coverage still depends on installed integrations, upstream rate limits, and what each platform exposes publicly.

## MIA Workbench

```bash
mia workbench
```

The default address is `http://127.0.0.1:8765`. Workbench provides Deep Cases, evidence uploads, review queues, detailed graph controls, timelines, package management, provider configuration, identity clustering, notes, exports, and raw operation inspection.

Each interface has one public launch command. The former `mia ui`, `mia discover ui`, and `mia workbench ui` aliases were removed in alpha 7.

## Browser and port options

Both interfaces open the browser automatically. Use `--no-browser` for SSH sessions or scripts:

```bash
mia workbench --no-browser --port 9000
mia discover --no-browser --port 9001
```

The default server accepts local clients only. A non-local bind requires explicit remote mode and an access token:

```bash
mia discover --host 0.0.0.0 --allow-remote --token 'choose-a-long-random-token'
```

Remote mode does not provide TLS. Use it only on controlled private networks or behind a trusted TLS reverse proxy.

## Shared account-discovery behavior

A handle or supported public-profile URL can become a scan-ready selector while preserving the original platform as context. Selecting a starting platform constructs the canonical public profile URL first—for example, a TikTok username becomes a TikTok profile seed—then MIA Core performs the configured discovery workflow. Matching usernames remain leads, not proof.

MIA Core imports a cross-profile account only from explicit identity metadata, such as `rel=me`, JSON-LD `sameAs`, or a dedicated profile website field that directly points to another supported profile. Ordinary page links do not become identity evidence.

## Architecture

- FastAPI exposes one shared localhost API and WebSocket operation stream.
- `frontend-discover/` contains the MIA Discover React/TypeScript application.
- `frontend-workbench/` contains the MIA Workbench React/TypeScript application.
- Vite builds them into `mia.web.static_discover` and `mia.web.static_workbench`.
- Cytoscape.js renders evidence graphs.
- Framer Motion supplies restrained transitions and progress animation.

The browser never invokes shell commands directly. API routes call the same MIA Core service classes used by the CLI.

## Development

MIA Workbench:

```bash
npm --prefix frontend-workbench install
npm --prefix frontend-workbench run dev
```

MIA Discover:

```bash
npm --prefix frontend-discover install
npm --prefix frontend-discover run dev
```

Build both production bundles:

```bash
npm --prefix frontend-workbench run build
npm --prefix frontend-discover run build
```

The Workbench Vite server proxies to port 8765. The Discover Vite server proxies to port 8766.


## Linux application menu

The Alpha 8 installer creates separate **MIA Discover** and **MIA Workbench**
application-menu entries for the current user. They call the same `mia` command
and share one MIA Core installation and state directory. Manage them with
`mia desktop install`, `mia desktop status`, and `mia desktop remove`.
