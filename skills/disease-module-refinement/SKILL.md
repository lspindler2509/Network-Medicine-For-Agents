---
name: disease-module-refinement
description: "Build, refine and interpret a network-medicine disease module together with the user through netmed (drugstone, NeDRex): discuss settings, expand seeds, prune by SPD with a distribution plot, pathway enrichment, clustering, OmniPath directions, localisation, tissue expression, drug repurposing, and a shareable Drugst.One network link. Use for Drugst.One DREAM-style module refinement and mechanism-based drug candidate search."
---

# Disease module refinement and drug repurposing

Read the `netmed` skill first for CLI mechanics (help, Fire syntax, saved objects,
background jobs). This skill turns the workflow of
[Drugst.One DREAM](https://doi.org/10.1111/bph.70495) into netmed calls.

Refinement is an expert dialogue, not a pipeline. An automatically inferred module is
a hypothesis; the user decides what stays. Work in rounds: run a step, show the
result (plot, table, link), propose a decision with its evidence, and **wait for the
user at every checkpoint marked ⏸** before continuing. Keep the user able to
continue in the web interface at any point by giving the Drugst.One links.

## Tools and conventions

```sh
netmed docs drugstone                     # algorithms and parameters ("Available Parameters")
netmed drugstone new_task --help          # signature only
netmed drugstone network --help           # pruning, plots, OmniPath overlay, stored networks
netmed drugstone fetching --help          # datasets, tissues/expression, pathway networks
netmed nedrex --help                      # DIAMOnD, DOMINO, ROBUST, MuST, TrustRank, validation
```

- drugstone runs on the configured Drugst.One server (default public `drugst.one`,
  web interface `https://drugst.one/standalone`). The algorithms here need drugstone
  2.0.0 and a server with the DREAM features (`first-neighbor`,
  `pathway-enrichment`, `louvain-clustering`, `leiden-clustering`,
  `adjacentDisorders`); check `new_task --help`.
- **Save every task as an object** and read it afterwards; it keeps the token for
  the web link and the results:

  ```sh
  netmed drugstone new_task '<seeds>' '<parameters>' --quiet=True --save-object fn_task
  netmed objects show fn_task get_token                               # task token
  netmed objects show fn_task get_result - get_raw_result --save-object fn   # result dict
  ```

  Later calls read parts with selectors such as `'@object:fn["network"]["nodes"]'`.
  `netmed objects show <label>` prints a saved dict as `key: JSON` lines; redirect
  large outputs to a file instead of printing them into the context.
- Results of expression, `adjacentDrugs` and `adjacentDisorders` use internal protein
  IDs (`p…`, several per symbol); map them back through the nodes' `drugstoneId`.
  `isSeed` in a result marks that task's input nodes, so keep the original seed list
  yourself.
- **Task links:** after each task give the user
  `https://drugst.one/standalone?taskId=<token>` (or the standalone page of the
  server in use) together with the algorithm and parameters, and keep a running list
  of all task links for the final report. The links let the user reopen and continue
  an analysis later. Opening tasks by `taskId` needs a web interface version that
  supports it; if the link opens an empty view, say so and rely on the network link
  of step 7.

## Workflow

### 1. Seeds, disease context and advanced settings ⏸

This skill starts from seed genes/proteins the user provides (validated risk genes,
GWAS hits, a module from another method). Ask for their provenance and record it.
Use HGNC symbols (`"identifier": "symbol"`) unless the input is in another ID space.

**Disease context.** Use what the user tells about the disease, or ask: indication,
relevant tissue(s) and cell types, compartments, the expected direction of
dysregulation (loss or gain of function), known drugs and the goal (mechanism,
repurposing, combination). Offer to gather missing context with other netmed
sources, e.g. a literature search (`europepmc`, `pymed`), disease-gene evidence and
known drugs (`opentargets`, `gwas_mcp`, `monarch`), or disease ontology IDs
(`ols4`). Use `netmed find "<keywords>"` and `netmed sources` to see what the
installed catalog offers; name the sources and what they contributed. The context
guides the refinement decisions later, and the same sources can be offered again at
any later step.

**Advanced settings.** Before the first task, list the available datasets with
versions (`netmed drugstone fetching get_datasets`) and **discuss the advanced
settings with the user**, with a recommendation and its reason. They stay fixed for
the whole analysis and are passed to **every** task, so changing them later means
starting over:

| Setting | Task parameter | Points to discuss |
|---|---|---|
| PPI network | `ppiDataset` (`NeDRex`, `iid`, `biogrid`, `intact`, `STRING`, `OmniPath`, `APID`) | Coverage vs. specificity; experimental only; directed (OmniPath); the interactome of a study to reproduce |
| Custom PPI | `custom_edges` + `"exclude_drugstone_ppi_edges": True` | Instead of a server PPI, e.g. a filtered NeDRex PPI (see `nedrex-ppi`), saved once as an object and passed as `"custom_edges": "@object:<label>"` in every task, including enrichment, clustering and drug search |
| Drug-target data | `pdiDataset` (`NeDRex`, `drugcentral`, `ChEMBL`, `DGIdb`, licensed `drugbank`) | Source and version of drug targets |
| Licensed data | `licenced` | Licensed NeDRex/DrugBank/OMIM data need an accepted licence |
| Approved drugs only | `includeNonApprovedDrugs` | Repurposing usually starts with approved drugs |
| Indirect drugs | `includeIndirectDrugs` | Drugs reaching the module through non-module targets |
| Hub handling | `maxDeg`, `hubPenalty` | Limits promiscuous hubs in expansion and drug ranking |
| ID space | `identifier` | Must match the seeds |

### 2. Expand the seeds into a candidate module

Propose the expansion method and let the user choose:

- **First neighbours + SPD pruning** (hypothesis-free):
  `"algorithm": "first-neighbor", "target": "drug-target"`. The result contains the
  subnetwork induced by the seeds and all their neighbours in `networkInitial`. Each
  node gets `properties` with `degreeInNetwork`, `degreeInPpi` and `spd`
  (subnetwork participation degree = degree in the module / degree in the PPI),
  plus `layer` and `cellularComponent`. Seeds keep all their neighbours, so their SPD
  should be 1. With more than 250 nodes the server also prunes automatically:
  `network` then holds the nodes with the highest SPD below 250 nodes, and `cutoff`
  plus `automaticCutoff: true` record that cutoff. Tell the user both sizes. With
  many or highly connected seeds the task can take tens of minutes and the result
  is large; start it with `netmed --background` and poll `netmed jobs <id>`.
- **Connector algorithms** adding few proteins between seeds: `multisteiner`,
  `keypathwayminer`, or `trustrank`/`closeness` with `"target": "drug-target"`.
- **Module detection on NeDRex**: `nedrex diamond`, `domino`, `robust`, `must`
  (submit, poll the status, download), e.g. DOMINO as in the Crohn's disease case of
  DREAM.

Report the size of the candidate module and its task link.

### 3. Prune topological artefacts ⏸

Show the distribution before choosing a cutoff. Write the plot to a file the user can
open and display it (send the image, or give its path):

Use the complete first-neighbour network (`networkInitial`), not the automatically
pruned `network`, for the distribution and for percentile rules:

```sh
netmed drugstone network get_pruning_distribution '@object:fn["networkInitial"]["nodes"]' spd --path=<dir>/spd_distribution.png --cutoff=<proposed> > <dir>/spd_distribution.txt
```

The text output contains `count`, `min`, `max`, bins and all `sorted_values` (large:
read the values from the file). Propose a cutoff with its rule (e.g. keep nodes at
or above the 80th percentile of SPD, as in [Elbatreek et al. 2020](https://doi.org/10.1371/journal.pbio.3000885)),
and include the automatic cutoff as a candidate. State how many nodes and which
seeds each candidate keeps or removes. Seeds should not be pruned: if a seed has
SPD < 1 or a node has SPD > 1, the PPI degree is inconsistent with the network
(report it, keep the seeds and treat SPD values with care). Let the user choose or
adjust; re-plot with the new cutoff if asked. Then prune within the task, as the web
interface does: prune the complete network, recalculate the statistics on the
pruned module and write it back to the task:

```sh
netmed drugstone network prune_network '@object:fn["networkInitial"]' spd --cutoff=<c> --save-object pruned
netmed drugstone network recalculate_statistics '@object:pruned["prunedNetwork"]' '{"identifier": "symbol", "interactionProteinProtein": "<ppi>", "interactionDrugProtein": "<pdi>", "licensedDatasets": False}' --save-object pruned_nodes
netmed drugstone network update_result_network <token> '{"nodes": "@object:pruned_nodes", "edges": "@object:pruned[\"prunedNetwork\"][\"edges\"]"}' --cutoff=<c>
```

`recalculate_statistics` needs both datasets in its config (it selects the server's
graph file by them); with a custom PPI add `"custom_edges": True,
"exclude_drugstone_ppi_edges": True`. `update_result_network` replaces the network
stored with the task, so the task link shows the pruned module; it overwrites the
previous network of that task and removes the automatic-cutoff flag. Very large
networks can fail in `prune_network` (HTTP 502); then prune `network` instead if the
chosen cutoff is at or above the automatic one. Ask whether isolated proteins should
go (`prune_orphan_nodes=True`): an isolated seed is a result (not connected to the
mechanism) and is better kept visible. Other numeric or categorical node properties
can be pruned the same way (`unique_values` for categories), e.g. `degreeInPpi`.

### 4. Annotate and interpret ⏸

Run these on the pruned module: pass its node list as seeds, together with the
advanced settings of step 1. Save each task and give its link.

| Question | Call |
|---|---|
| Which pathways does the module represent? | `new_task <nodes> '{"algorithm": "pathway-enrichment", "target": "gene", "kegg": True, "reactome": True, "wiki": True}'`; table in `filteredDf`/`tableView`; `fetching get_pathway_network <token> <geneset> <pathway>` for one pathway's network |
| Which sub-mechanisms does it contain? | `"algorithm": "louvain-clustering"` (`resolution`) or `"leiden-clustering"` (`max_nodes`), `"target": "clustering"`, fixed `"seed"`, `"ignore_isolated": True`; clusters in `network.nodes[].cluster`, modularity in `modularity` |
| Is there a causal direction? | `network overlay_directed_edges '@object:pruned["prunedNetwork"]'` (OmniPath direction, stimulation/inhibition) |
| Where are the proteins? | node `layer` and `cellularComponent` (GO) from the first-neighbour result |
| Are they expressed in the relevant tissue? | `fetching get_tissues`, then `fetching get_tissue_expression <tissue-id> '<symbols>'` (GTEx median TPM) |
| Which diseases are linked? | `"algorithm": "adjacentDisorders"` on the module or a cluster |

Present the results compactly (top pathways with overlap and genes, clusters with
members and the seeds they contain, directed edges, compartments, expression) and
ask the user which enrichment databases, clustering resolution or tissue to try
next. Pathways can also extend the module: proteins of an enriched pathway that are
missing from the module are candidates to add (with the user's consent). For
proteins whose role is unclear, offer a literature search or evidence from other
netmed sources (e.g. `europepmc`, `opentargets`, `uniprot`) linking them to the
disease or the mechanism.

### 5. Refinement decision ⏸

Propose a refined module as a table: protein, keep/remove/add, evidence (SPD,
pathway, cluster, direction, compartment, expression, seed status). Typical reasons
to remove: low SPD, a single unspecific edge, no pathway support, pathway or
compartment unrelated to the disease. Missing annotation alone is no reason to drop
a seed. Expression is supporting evidence, not a filter: bulk GTEx can miss
cell-type or disease-induced expression (NOX5 is nearly absent in GTEx arteries
although it is the causal protein of the NOX5 module). Apply only what the user
confirms. Optionally repeat expansion and annotation from the refined core.

### 6. Drug repurposing on the refined module ⏸

Ask whether to search on the whole refined module or on selected clusters, then run
the drug search there (not on the raw first-neighbour network). **TrustRank is the
default**; use other algorithms only when the user asks or as a comparison:

```sh
netmed drugstone new_task '<refined symbols>' '{"algorithm": "trustrank", "target": "drug", <advanced settings>, "resultSize": 20}' --quiet=True --save-object drugs_trustrank
```

- TrustRank ranks drugs by propagated trust from the module through the PPI to drug
  targets (`damping_factor`, default 0.85). `netmed objects show drugs_trustrank
  get_result - get_drugs` lists each drug with `status`, normalized `score`,
  `score_raw` and its targets in `hasEdgesTo`.
- Alternatives on request: `closeness`, `degree`, `proximity` (drugstone), or
  `adjacentDrugs` for drugs that directly target module proteins (raw `pdis` link
  internal drug `dr…` and protein `p…` IDs). `adjacentDrugs` and
  `adjacentDisorders` run without a server task, so they have no token or link, and
  `adjacentDrugs` may return non-approved drugs despite
  `"includeNonApprovedDrugs": False`; filter on `status`. Comparing TrustRank with direct
  targets shows which candidates act on module members and which only reach
  the module through the network.
- Check every candidate's targets. Network ranking favours promiscuous drugs that
  reach the module through hub proteins (e.g. kinase inhibitors through broadly
  connected kinases). Prefer drugs whose targets are refined module members.
- Group candidates by target and mechanism. The OmniPath directions and the disease
  mechanism decide whether an activator or an inhibitor makes sense; the network
  does not. Discuss this with the user.
- A module protein without an approved drug is a finding (a target for new drugs).
  Check investigational drugs with `"includeNonApprovedDrugs": True`.
- Current indications of the candidates: `fetching get_adjacent_disorders_of_drugs`
  (`drugstone_ids=True` keeps internal IDs).

**Additional evidence from other netmed sources.** Offer these to prioritise and
check the candidates; find the operations with `netmed find` and their help, and use
only sources available in the installed catalog:

| Question | Example sources |
|---|---|
| Mechanism of action, potency, development phase | `chembl_webresource_client`, `pharos`, `dgidb` |
| Known drugs and target evidence for the disease | `opentargets`, `opentargets_mcp` |
| Existing or past trials for drug + indication | `clinicaltrials` |
| Published evidence for drug + disease or target | `europepmc`, `pymed` |
| Network proximity of drug targets to the module | `netmedpy`, drugstone `proximity` |
| Benchmark against drugs known for the indication | `nedrex validation drug_validation_submit`, `module_validation_submit` |
| Pharmacogenomics, safety | `clinpgx` |

Present the candidates as a table: drug, targets in the module, mechanism
(activates/inhibits), approval status, existing indication or trials, supporting
literature, and network artefacts flagged.

### 7. Publish the refined network

Always finish by storing the refined module on the server and giving the user its
link, so the result can be opened, shared and refined further in the web interface:

```sh
netmed objects import refined_network.json --label refined_network
netmed drugstone network create_network '@object:refined_network' '{"identifier": "symbol", "interactionProteinProtein": "<ppi>", "interactionDrugProtein": "<pdi>", "autofillEdges": True, "licensedDatasets": False}'
netmed drugstone network get_network_link <network-id>
```

The network is `{"nodes": [{"id", "label", "group"}], "edges": [{"from", "to"}]}`
with the refined proteins and their module edges; mark seeds with the group
`seedNode` and other proteins with `default` (or custom `groups`). The config uses
the web interface's names and should repeat the advanced settings of step 1, so the
view uses the same datasets. With a custom PPI, the web view autofills edges from
its own PPI setting; include the module edges in the network and say so. Tell the user that anyone with the ID can load the
network. Drugs can be shown in the web view with its drug option; the drug
candidates belong in the report.

## Reporting

Report seeds and their source, the advanced settings with dataset versions, the
server, every task with algorithm, parameters and link, the pruning rule and cutoff
(with the plot), module size before and after refinement, each removed or added
protein with its reason and the user's decision, enrichment and clustering results
(with random seed), the drug candidates with targets, approval status and
mechanism, and the final network link. State clearly that candidates are network
hypotheses that need experimental and clinical validation.
