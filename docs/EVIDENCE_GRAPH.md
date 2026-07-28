# Evidence graph

## Nodes

Each normalized entity is represented by an `EvidenceNode` with:

- stable case-local ID;
- entity type, label, original value, and canonical value;
- confidence score and label;
- source plugin IDs;
- evidence file references;
- attributes;
- first/last seen timestamps;
- manual/root/pivot markers.

Common node types include `username`, `account`, `email`, `domain`, `ip`,
`phone`, `certificate`, `breach`, `repository`, `company`, `url`, `website`,
`document`, `metadata`, and workflow `scan` nodes.

## Edges

An `EvidenceEdge` explains a relationship. It stores:

- source and target IDs;
- machine relation and readable label;
- confidence and confidence label;
- reasons;
- structured confidence factors;
- attributes and provenance.

Examples include `has_account`, `associated_email`, `associated_domain`,
`resolves_to`, `appeared_in`, `owns_repository`, and `triggered_scan`.

`triggered_scan` records a workflow action. It explicitly does not claim that
source and target belong to the same actor.

## Confidence explanations

Each factor has a label, effect (`positive`, `negative`, or `neutral`), weight,
and explanation. Dashboard users can inspect the reasons instead of seeing only
a percentage.

Confidence is a review-priority heuristic. It is not calibrated identity
probability and must not be presented as such.

## Exports

Every rebuilt case writes:

```text
graph/graph.json
graph/graph.graphml
graph/graph.gexf
graph/graph.mmd
```

- JSON preserves the full MIA model.
- GraphML and GEXF support common graph tools.
- Mermaid supports lightweight text rendering.

## Offline dashboard

`reports/index.html` contains no external JavaScript or CSS. It supports:

- graph search and type filtering;
- force-like deterministic layout and reset;
- clickable nodes and edges;
- confidence reasons and factors;
- entity cards and filters;
- timeline;
- assistant summaries with evidence IDs;
- plugin status, logs, warnings, and bounded raw excerpts;
- notes, attachments, screenshots, and export links;
- dark/light themes and keyboard shortcuts.

The dashboard embeds HTML-safe JSON. Raw excerpts are bounded and escaped before
rendering.
