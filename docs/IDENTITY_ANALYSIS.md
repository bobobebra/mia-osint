# Identity comparison and multi-pass analysis

MIA compares normalized public profile evidence rather than assuming that equal
handles identify the same person.

## Deterministic clustering

The cluster engine can raise confidence for:

- the same external personal website;
- exact avatar-content hashes;
- visually similar avatar perceptual hashes;
- matching or materially similar display names;
- matching public locations;
- overlapping biography vocabulary;
- shared external domains;
- an exact username, with a strict username-only cap.

It can lower confidence for:

- materially different names;
- visually dissimilar or different exact avatars;
- differing locations that need contextual review;
- personal-versus-organization account-type conflicts.

A username match alone is deliberately insufficient to cross the default
cluster threshold. Scores prioritize review; they are not mathematical identity
probabilities.

Clusters and `likely_unrelated` edges keep supporting reasons, contradictions,
weights, and evidence references. MIA also creates a manual-review queue for
isolated candidates, weak verification, suspected false positives, and
contradictory clusters.

## Multi-pass AI workflow

```console
mia case analyze CASE_ID --depth thorough
mia case analyze CASE_ID --depth exhaustive --provider gemini --thinking-level high
```

Depths:

- `quick`: analyst pass;
- `standard`: analyst -> skeptic -> planner;
- `thorough`: analyst -> independent profile reviewer -> skeptic -> citation
  verifier -> planner;
- `exhaustive`: thorough plus cluster critic and final synthesizer.

Each pass receives normalized evidence and the **grounded output of earlier
passes**. Statements with missing, empty, or unknown evidence IDs are rejected
before they can become part of the analysis. Prior-pass context is bounded to
avoid unbounded prompts.

The AI is used for explanation, contradiction review, prioritization, and next
steps. Deterministic code remains responsible for URL status, hashes, IDs,
normalization, and evidence storage.

## Gemini reasoning controls

`--thinking-level minimal|low|medium|high` controls reasoning effort for
supported Gemini 3 models. Gemini 2.5 models are translated to a compatible
`thinkingBudget`; MIA never sends both settings in the same request.

Analysis depth and thinking level are different:

- depth controls the number and purpose of MIA workflow passes;
- thinking level controls reasoning effort inside an individual provider call.

High/exhaustive modes can be slower and more expensive. All provider output is
still treated as fallible and must remain evidence cited.

## Local provider

The `local` provider performs deterministic summaries without transmitting case
data. It is less nuanced, but useful as a private fallback and for validating
case structure.

## Remote-data warning

Remote providers receive bounded normalized nodes, edges, Deep Case seeds,
verification records, clusters, review tasks, and notes supplied to the analysis
command. This may include personal data. Only transmit data when lawful,
authorized, and permitted by the provider's terms and your own policies.
