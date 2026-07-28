# API integrations and credentials

MIA v4 includes opt-in passive adapters for:

- Shodan;
- VirusTotal;
- Have I Been Pwned;
- SecurityTrails;
- Censys;
- Intelligence X metadata search.

Assistant credential services are also available for OpenAI-compatible
endpoints, Google Gemini, and authenticated Ollama endpoints. Local Ollama does
not require a credential.

Availability, plans, quotas, schemas, and terms are controlled by each provider
and can change independently of MIA.

## Status

```console
mia api list
mia doctor
mia plugins
```

An API plugin is available only when it is enabled and a credential can be
resolved.

## Store a credential

Interactive keyring storage:

```console
mia api set shodan
```

Enable or disable without deleting the key:

```console
mia api enable shodan
mia api disable shodan
```

Delete:

```console
mia api delete shodan
```

## Environment variables

Environment variables take precedence and are recommended for CI or ephemeral
sessions:

```text
MIA_SHODAN_API_KEY
MIA_VIRUSTOTAL_API_KEY
MIA_HIBP_API_KEY
MIA_SECURITYTRAILS_API_KEY
MIA_CENSYS_API_KEY
MIA_INTELX_API_KEY
MIA_ASSISTANT_API_KEY
OPENAI_API_KEY
GEMINI_API_KEY
GOOGLE_API_KEY
MIA_GEMINI_API_KEY
OLLAMA_API_KEY
MIA_OLLAMA_API_KEY
```

## Storage order

MIA resolves a key in this order:

1. documented environment variable;
2. operating-system keyring;
3. explicit mode-0600 fallback file.

The fallback is only created with:

```console
mia api set SERVICE --insecure-file
```

It is plaintext despite restrictive permissions. Prefer an environment variable
or working keyring.

## Configuration

Endpoints, enablement, timeouts, organization IDs, and extra non-secret headers
live in YAML. Keys do not.

```yaml
apis:
  censys:
    enabled: true
    endpoint: https://api.platform.censys.io/v3
    organization_id: null
    timeout: 30
```

Custom OpenAI-compatible, Gemini, and Ollama assistant endpoints and models are configured under `assistant.providers`.

## Data minimization

MIA stores bounded API responses in the scan's raw evidence directory for
provenance. Intelligence X intentionally records metadata only and does not
download record contents. Before sharing a case, inspect raw responses and
exports for personal or sensitive information.
