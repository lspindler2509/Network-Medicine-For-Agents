---
name: nedrex-ppi
description: "Query protein-protein interactions (PPIs) from NeDRex through the netmed CLI: evidence and quality filters, paging, background jobs for large downloads and conversion to edge lists. Use when an agent needs NeDRex PPI edges, for example as a custom PPI for network analyses."
---

# NeDRex PPIs through netmed

Read the `netmed` skill first for general CLI usage. This skill covers the two
NeDRex PPI operations and how to use them for large downloads.

```sh
netmed nedrex ppi ppis --help
netmed nedrex ppi iter_ppis --help
```

This skill describes `nedrex` 0.2.0. Check the help before calling: if `iter_ppis`
is missing, the installed netmed ships an older `nedrex` without these filters.

## Operations

- `ppis(evidence, skip=0, limit=None, ...)` returns **one page** of edges.
  `limit` is capped by the server's pagination limit
  (`netmed nedrex core get_pagination_limit`, 10000 on api.nedrex.net).
- `iter_ppis(evidence=('exp',), ..., page_size=None, skip=0, max_records=None)`
  pages through **all** matching edges with the same filters. Use it for
  complete downloads; bound test runs with `max_records`.

netmed prints each edge as one JSON line. Redirect stdout to a file; progress
messages go to stderr.

## Filters

| Parameter | Meaning |
|---|---|
| `evidence` | Required list of `"exp"` (experimental), `"pred"` (predicted), `"ortho"` (orthologous). An edge matches if it has one of them. |
| `reviewed_proteins` | `[True]` for edges between UniProt-reviewed proteins only; default both. |
| `sources` | Source databases, e.g. `["biogrid"]`, `["intact"]`, `["iid"]`. Edges reported by at least one of them. |
| `num_sources` | Minimum number of supporting source databases. |
| `hippie_methods_score_cutoff` | Minimum `hippie_methods_score` on api.nedrex.net (not a 0–1 scale; observed values such as 0, 5, 12.5). |
| `methods_score_cutoff` | Corresponding filter on the TUM instance; not for api.nedrex.net. |
| `skip_proteins`, `limit_proteins` | Window over the protein collection in storage order (not by gene or relevance); only edges with **both** members inside the window are returned. Small windows therefore return few or no edges, and splitting a download into protein windows loses the edges between windows. Leave the defaults; page with `skip`/`iter_ppis` instead. |
| `nodes` | Edges involving the given nodes (`uniprot.` IDs). Currently **ignored** by api.nedrex.net, which returns unrelated edges; a fix in the API is announced. Until then filter downloaded edges instead, and check that returned edges contain the requested nodes. |

Lists are passed as quoted Python literals (Fire syntax), booleans as `True`/`False`:

```sh
netmed nedrex ppi ppis '["exp"]' --limit=5 --num_sources=3
netmed nedrex ppi iter_ppis --evidence='["exp"]' --reviewed_proteins='[True]' --max_records=1000 > ppi_sample.jsonl
```

## Edge format

Each line is one edge, for example:

```json
{"memberOne": "uniprot.P45985", "memberTwo": "uniprot.Q14315",
 "dataSources": ["biogrid", "iid"], "evidenceTypes": ["exp", "pred"],
 "hippie_methods_score": 12.5, "methods": ["Two-hybrid", ...],
 "tissues": [...], "subcellularLocations": [...], "type": "ProteinInteractsWithProtein"}
```

Members are UniProt accessions with a `uniprot.` prefix. Edges are undirected;
deduplicate pairs regardless of order when converting.

## Complete downloads in the background

All experimental edges between reviewed proteins are about 1.1 million edges
(19,000 proteins), 2 GB of JSON lines and about 20 minutes on api.nedrex.net.
Run such downloads as a background job:

```sh
netmed --background nedrex ppi iter_ppis --evidence='["exp"]' --reviewed_proteins='[True]'
netmed jobs <job-id>          # state and output location
netmed jobs active            # running jobs
```

The edges are in the job's `result.txt` (see `netmed jobs <job-id>`), stderr in
`stderr.txt`. Check the job state and the line count before using the file:
a stopped job leaves a partial file. Restarting a download starts from the
beginning; use `skip` to continue after the last complete page if needed.

## Converting to an edge list

For tools that take `{"from", "to"}` edges (e.g. drugstone `custom_edges` with
`"identifier": "uniprot"`), strip the prefix, drop self-loops and deduplicate
undirected pairs with a short script:

```python
import json, sys

edges = set()
for line in open(sys.argv[1]):
    if not line.startswith("{"):
        continue
    e = json.loads(line)
    a = e["memberOne"].removeprefix("uniprot.")
    b = e["memberTwo"].removeprefix("uniprot.")
    if a != b:
        edges.add(tuple(sorted((a, b))))
json.dump([{"from": a, "to": b} for a, b in sorted(edges)], open(sys.argv[2], "w"))
```

The converted list of that download is about 40 MB. It is too large for a command-line
argument (about 1 MB on macOS), so it cannot be passed to another netmed call directly.

Report the filters, the NeDRex instance (`netmed docs nedrex`, package
version) and the edge count with any result that uses the downloaded PPI.
