# Evidence-grounded assistant

MIA's assistant summarizes a case; it is not an autonomous attribution engine
and must never be treated as a source of evidence.

Supported providers:

- `local` — deterministic, offline, and credential-free;
- `openai-compatible` — any compatible chat-completions endpoint;
- `gemini` — Google Gemini API through `generateContent`;
- `ollama` — local Ollama or Ollama Cloud through the chat API.

All remote providers receive the same bounded normalized evidence and pass
through the same citation validator. Provider output is not trusted merely
because it is valid JSON.

## Inspect and configure providers

```console
mia assistant providers
mia assistant configure gemini --model gemini-3.5-flash --default
mia assistant configure ollama --model gemma3 --default
```

The command writes only non-secret settings. Credentials stay in environment
variables or the operating-system keyring.

A one-off model or endpoint override is also available:

```console
mia case summarize CASE --provider gemini --model gemini-3.5-flash
mia case summarize CASE --provider ollama --model gemma3
mia case summarize CASE --provider ollama --model gemma3 \
  --endpoint http://127.0.0.1:11434/api
```

When `--provider` is omitted, MIA uses `assistant.provider` from the user
configuration.

## Local provider

The default provider is deterministic, offline, and does not call an AI service:

```console
mia case summarize CASE
```

It reports entity counts, strongest normalized findings, low-confidence and
single-source warnings, exact cross-case correlations, and conservative next
steps. Statements cite case node or edge IDs.

## OpenAI-compatible provider

Configure it without editing YAML manually:

```console
mia assistant configure openai-compatible \
  --model your-model-name \
  --endpoint https://api.example.com/v1/chat/completions \
  --default
mia api set assistant
mia case summarize CASE
```

`OPENAI_API_KEY` is accepted as an alias for `MIA_ASSISTANT_API_KEY`.

MIA requests a JSON object and includes the exact output schema in the prompt.
It intentionally uses the broadly supported `json_object` response mode rather
than assuming every compatible server implements strict JSON-schema mode.

## Gemini provider

Store a key using the keyring:

```console
mia api set gemini
```

Or use one of the supported environment variables:

```console
export GEMINI_API_KEY='...'
# Also accepted: GOOGLE_API_KEY or MIA_GEMINI_API_KEY
```

Configure and run:

```console
mia assistant configure gemini --model gemini-3.5-flash --default
mia case summarize CASE
```

MIA calls the Gemini `generateContent` API with JSON output enabled and sends a
JSON schema for the expected sections. The provider's response is still parsed
and independently checked against the case's valid node and edge IDs.

The Gemini model name is deliberately configurable because model availability
and naming can change. The packaged configuration does not force a model.

## Ollama provider

Run Ollama and pull a model using Ollama's own installation and model-management
instructions. Then configure MIA:

```console
mia assistant configure ollama --model gemma3 --default
mia case summarize CASE
```

The default endpoint is:

```text
http://localhost:11434/api
```

Local Ollama does not require a key. MIA sends non-streaming chat requests with
temperature zero, disables separate thinking output, and requests a JSON-schema
structured response where supported.

For Ollama Cloud or another authenticated endpoint:

```console
export OLLAMA_API_KEY='...'
mia assistant configure ollama \
  --model your-cloud-model \
  --endpoint https://ollama.com/api \
  --default
```

`MIA_OLLAMA_API_KEY` is also accepted. Because Ollama Cloud may not support the
same structured-output options as local Ollama, MIA falls back to the explicit
schema embedded in the prompt and still validates every returned statement.

## YAML format

```yaml
assistant:
  provider: local
  enabled: true
  timeout: 90
  send_raw_evidence: false
  max_nodes: 200
  providers:
    openai-compatible:
      endpoint: https://api.openai.com/v1/chat/completions
      model: ""
      api_service: assistant
      requires_key: true
    gemini:
      endpoint: https://generativelanguage.googleapis.com/v1beta
      model: ""
      api_service: gemini
      requires_key: true
    ollama:
      endpoint: http://localhost:11434/api
      model: ""
      api_service: ollama
      requires_key: false
```

The alpha.1 top-level `assistant.endpoint`, `assistant.model`, and
`assistant.api_service` fields remain supported for OpenAI-compatible user
configurations.

## Grounding contract

The remote provider receives bounded normalized nodes and edges. Each returned
item must contain:

```json
{
  "text": "...",
  "evidence_ids": ["node-...", "edge-..."],
  "confidence": "medium"
}
```

MIA validates every ID against the supplied case evidence. Malformed, uncited,
or unknown-ID statements are discarded and counted. All providers are prompted
with temperature zero where their API supports it.

This reduces unsupported statements but cannot guarantee truth, model security,
provider privacy, correct interpretation, or resistance to prompt injection in
normalized source data.

## Privacy

Raw evidence is not sent by default. Normalized evidence can still contain
personal information. Use only an endpoint and account appropriate for the data,
and understand the provider's retention, training, regional, and account terms
before enabling it.

For the strongest local privacy boundary, use `local` or a local-only Ollama
instance and verify that Ollama cloud features are disabled according to your
own deployment policy.

## Sequential case analysis

`mia case summarize` remains a one-pass summary command. For identity review use:

```console
mia case analyze CASE --depth thorough
mia case analyze CASE --depth exhaustive --provider gemini --thinking-level high
```

The analysis workflow runs distinct grounded passes. Later passes receive the
validated statements from prior passes, allowing the skeptic to challenge the
analyst and the verifier to audit earlier conclusions. Unknown or missing
evidence IDs are rejected after every pass.

Gemini 3 models receive `thinkingLevel`; Gemini 2.5 models receive a compatible
`thinkingBudget`. MIA does not send both controls in one request. The `local`
provider performs deterministic analysis without external transmission.

Deep Case context may include investigator-supplied names, emails, locations,
addresses, hypotheses, and notes. Remote use is explicit and should only occur
when the data is lawful and authorized to transmit.
