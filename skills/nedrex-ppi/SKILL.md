---
name: nedrex-ppi
description: "Query protein-protein interactions (PPIs) from NeDRex through the netmed CLI: evidence and quality filters, paging, complete edge-list downloads as saved objects and background jobs. Use when an agent needs NeDRex PPI edges, for example as a custom PPI for network analyses."
---

# NeDRex PPIs through netmed

Read the `netmed` skill first for general CLI usage. This skill covers the
NeDRex PPI operations and how to use them for large downloads.

```sh
netmed nedrex ppi ppis --help
netmed nedrex ppi iter_ppis --help
netmed nedrex ppi ppi_network --help
```

This skill describes `nedrex` 0.2.0. Check the help before calling: if `iter_ppis`
or `ppi_network` is missing, the installed netmed ships an older `nedrex`.

## Operations

- `ppis(evidence, skip=0, limit=None, ...)` returns **one page** of edges.
  `limit` is capped by the server's pagination limit
  (`netmed nedrex core get_pagination_limit`, 10000 on api.nedrex.net).
- `iter_ppis(evidence=('exp',), ..., page_size=None, skip=0, max_records=None)`
  pages through **all** matching edges with the same filters, with all fields.
  Bound test runs with `max_records`.
- `ppi_network(evidence=('exp',), ..., compact=False)` downloads all matching edges
  like `iter_ppis` but returns only the protein pairs: UniProt accessions without the
  `uniprot.` prefix, undirected, deduplicated, without self-loops. `compact=True`
  returns `{"nodes": [...], "edges": [[i, j], ...]}` with positions in `nodes`.
  Use it when the PPI is the input of another tool.

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

## Using the PPI as input of another tool

Save the edge list as an object instead of printing it; the complete PPI is too
large for a command-line argument. `@object:` references also work inside dict
arguments:

```sh
netmed --background nedrex ppi ppi_network --evidence='["exp"]' --reviewed_proteins='[True]' --compact=True --save-object nedrex_ppi
netmed jobs <job-id>                     # wait for completed; the result names the object
netmed drugstone new_task '["P04637"]' '{"algorithm": "trustrank", "identifier": "uniprot", "custom_edges": "@object:nedrex_ppi", "exclude_drugstone_ppi_edges": True}' --quiet=True
```

The compact form of all experimental edges between reviewed proteins is about 14 MB
(19,000 proteins, 1.1 million edges). drugstone accepts the compact form only from
servers that support it; the `{"from", "to"}` form of the complete PPI (about 40 MB)
exceeds the 25 MB request limit of drugstone servers. Pass `compact=False` for tools that need
`{"from", "to"}` edges. If edges were downloaded with `iter_ppis` instead, convert them
with a script and import the JSON with `netmed objects import <file> --label <label>`.

Report the filters, the NeDRex instance (`netmed docs nedrex`, package
version) and the edge count with any result that uses the downloaded PPI.
