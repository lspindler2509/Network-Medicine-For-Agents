---
name: netmed
description: "Install and use the netmed CLI to discover and run scientific Python packages, OpenAPI services, GraphQL queries and remote MCP tools. Use for netmed setup, operation search, native arguments, result export, saved objects and background jobs."
---

# netmed

Use netmed as the execution interface. It exposes existing package/API interfaces;
the agent selects operations and combines them into a workflow. netmed provisions
Python runtimes and isolated package environments automatically on first use.
Native signatures, scientific assumptions and output formats remain source-specific.

## Start with the installed CLI

Run `netmed --help` to check availability and the installed interface. If the
command is missing, first check for an existing bundle or a PATH issue. Read
[installation](references/installation.md) when installation or an upgrade is
needed. Use the published bundle for normal use; a repository checkout is not a
ready-to-use installation with its catalog and native binaries.

Discover operations before loading lengthy documentation:

```sh
netmed find "shortest path"
netmed find "identifier mapping" --limit 10 --json
netmed find "shortest path" --offset 10
netmed find "shortest path" --source networkx
```

- Search uses keywords from native names, documentation and source descriptions,
  not semantic reasoning. Prefer a few technical terms, usually in English.
  Terms match as alternatives, so long questions can introduce noisy matches.
- The default is **up to 10 hits**, with **at most 2 per source** to expose
  alternatives across packages. `--source` removes that diversity cap for the
  selected source. `--offset` pages through the ranked results.
- If matches are poor, shorten/rephrase the query or use a native function name.
  Scores rank textual relevance, not scientific suitability or execution success.
- Search covers indexed operations, not every possible dynamic interface. A
  missing hit does not prove a capability is absent. Explore source help when
  appropriate; `netmed sources` gives the full catalog, including disabled sources.
- If `find` or its index is unavailable, inspect the installed version and catalog.
  Use source help meanwhile. Prefer a current bundle for normal users; do not
  start a full catalog build or alter an installed catalog just to repair search.

## Inspect the selected interface

Tell the user which sources you plan to use and briefly why they fit the task,
so they can weigh in on the choice. Name the package or API/provider, not just
netmed; distinguish the client from the underlying database and API instance.
Mention material tradeoffs or alternatives when they affect the answer, such as
coverage, freshness, licensing or known client/server incompatibilities. This is
a concise explanation, not a mandatory approval step before ordinary calls.

```sh
netmed networkx --help
netmed networkx path_graph --help
netmed nedrex core get_edges --help
netmed docs nedrex
```

Read the chosen operation's help before executing it. Familiar package APIs may
already be known, but check the actual signature and version-specific options.
Use `docs <source>` only when package/specification documentation is needed.
Avoid loading the complete catalog's documentation into context.

- **Python (Fire syntax):** submodules use spaces, as in `nedrex core get_edges`. Pass native
  arguments. Quote lists/dictionaries as one shell argument. Fire literal parsing
  uses `True`, `False`, `None`, not JSON boolean/null spellings. Method chaining
  uses a standalone `-`.
- **OpenAPI (Restish syntax):** follow the generated command's native positional
  arguments, flags and body syntax. Body shorthand such as `'nodes: [1, 2]'`
  applies only to operations accepting that body. Use `<operation> --help-all`
  for transport/output options.
  `--rsh-output-format=json` changes rendering, not server content negotiation.
- **GraphQL:** inspect `netmed <source> --help` and
  `netmed <source> schema <Type>`, then use
  `netmed <source> query '<query>' --variables '<JSON>'`. Search results containing
  `...` are navigation hints, not executable queries. Supply required arguments
  and valid selections. Queries are read-only; handle pagination explicitly.
- **MCP:** inspect `netmed <source> <tool> --help` for the server's native JSON
  Schema, then call `netmed <source> <tool> --arguments '<JSON object>'`. Names and
  arguments are discovered automatically. Public remote Streamable HTTP tools are
  supported; login, local stdio servers and prompts/resources are not. Tools may
  have side effects; annotations do not grant permission. Results retain MCP
  `content`, optional `structuredContent` and `isError`; a tool error fails the
  command even if transport succeeded. `sources update <source>` refreshes the
  cached interface. Check installed help because older bundles may lack MCP.

For OpenAPI calls, distinguish the server's media type from CLI rendering:

- `-H 'Accept: application/json'` requests a JSON **response**. Some providers
  reject Restish's default multi-format Accept header; for a JSON endpoint this
  explicit header can resolve the error. Do not force it for FASTA, file or other
  non-JSON responses.
- `--rsh-content-type application/json` sets the **request body's** media type;
  use it when the operation accepts a JSON body, not to request JSON results.
- `--rsh-output-format=json` renders the response as JSON (netmed's API default).
  It does not replace the Accept header. Provider-specific `--format` or
  `--result-type` parameters, when present, follow that operation's help.

For example, a small UniProt annotation request with explicit response negotiation:

```sh
netmed uniprot get-by-accession P00533 --fields accession,protein_name -H 'Accept: application/json'
```

For nested GraphQL selections, follow the exact return types printed by `schema`,
not guessed singular/plural type names. For example, if a root field returns
`[Record!]!`, inspect `netmed <source> schema Record`; if its `references` field
returns `[Reference!]!`, inspect `schema Reference` before choosing child fields.
The brackets and `!` describe lists/nullability, not parts of the type name.
These type names illustrate the process; use the source's actual names. Request
only needed fields, and inspect count/limit options before fetching a collection.

Choose a small, bounded first call for unfamiliar sources. For a minimal local
smoke test, `netmed networkx path_graph 4 - number_of_nodes` should print `4`.
First-use package preparation can take longer than subsequent calls.

## Choose useful results

There is no universal Python JSON flag or uniform biomedical output schema.
Use the returned type's native export methods when portable output is needed,
for example `- to_csv --index=False`, `- to_json --orient=records` or `- tolist`.
Check that the returned type actually supports the chosen method. Package
progress messages can coexist with normal output.

Fire can print a returned list one item per line: a path containing nodes
`[0, 1, 2, 3]` may appear as four lines rather than a JSON array. This is not
necessarily truncation. Use a supported native export when a downstream step
requires a particular serialization.

Save the actual Python object when a later call needs its type:

```sh
netmed networkx path_graph 4 --save-object demo_graph
netmed networkx number_of_nodes @object:demo_graph
```

Use the immutable ID returned by the save operation if labels are ambiguous.
`netmed objects <id>` inspects metadata; `netmed objects show <id> --help` explores
the saved object in its original environment. Automatic serialization may export
JSON or fall back to a saved object, so inspect the actual response.

Object reuse does not merge environments. Receiving environments must support
the object's classes; otherwise export portable lists/dictionaries or files in
the original source. Do not install arbitrary dependencies based on a snapshot.
Only load trusted netmed snapshots. Live iterators/connections may not be savable.

Arguments are limited in size (about 1 MB on macOS, 128 KB per argument on Linux,
32 KB on Windows). Pass larger inputs, e.g. edge lists, as imported JSON objects;
`@object:` references also work inside dict/list arguments:

```sh
netmed objects import edges.json --label ppi      # or "-" to read stdin
netmed drugstone new_task '["P04637"]' '{"identifier": "uniprot", "custom_edges": "@object:ppi"}'
```

## Longer work and result checks

Global options such as `--catalog` and `--background` go **before** the source.
For a call expected to be long, use `netmed --background <source> ...`, keep the
returned job ID, and inspect `netmed jobs <job-id>` or `netmed jobs active`.
Job details identify output locations, including `result.txt` and `stderr.txt`.
Choose object saving or native export before launching the job.

Background execution is local job management, not automatic recovery. Moving a
foreground call to the background starts it again; stop the original and assess
whether repeating the operation is appropriate. Stopping a local worker does not
automatically cancel a provider's remote task. Preserve results and existing
environments; cleanup is separate from running an analysis.

Check content as well as exit status: required identifiers, returned errors,
missing records, output truncation and pagination warnings. Restish follows
recognized next links with a default 25-page cap that can warn yet exit
successfully; no generic offset/cursor inference exists. Inspect native paging
options before claiming complete retrieval. A completed job means successful
process execution, not a scientifically validated result.

Record the relevant commands, source/package versions, parameters and input/output
files for the user. `netmed logs --tail 20` shows command history, not complete data
provenance. `NETMED_DATA_DIR` controls mutable data; changing it does not move
existing results. `--catalog` changes the selected catalog only.

In the final answer, name the sources actually used and what each contributed,
with links to the provider/API or package where available. Include the version,
API instance or data release when known and relevant; do not invent missing
metadata. Distinguish results obtained from a source from failed attempts and
sources merely considered. Explain any fallback or source change that materially
affects interpretation, so the user can judge whether the evidence is suitable.

## Cleanup requires user confirmation

Always ask the user before deleting or clearing netmed folders, saved results,
objects, environments, caches or installation/test directories, including ones
created during the current task. Explain the exact paths or IDs and what will be
lost, then wait for explicit confirmation for that scope. A general request to
test, install, upgrade or fix netmed is not cleanup approval. Do not include a
destructive cleanup command in an unattended workflow or run it automatically
after a test. Read-only inspection and `--dry-run` previews can run before asking.

Inspect `netmed clean --help`, `netmed jobs clean --help` or
`netmed objects clean --help` for the installed version. Prefer targeted cleanup:

```sh
netmed jobs clean <job-id> --dry-run
netmed objects clean <object-id> --dry-run
netmed clean --all --dry-run
```

Resolve the actual data directory (`NETMED_DATA_DIR` or the platform default;
see [installation](references/installation.md)) and show the preview to the user.
Only after confirmation, run the approved command without `--dry-run`.
`netmed clean --all` removes managed `jobs`, `objects`, `environments`, `runtimes`,
`restish` and `api-updates` subfolders, including results and local API overrides.
It keeps the data root, root files such as `logs.txt` and `catalog.json`, and
unrelated folders. Packages/runtimes must be provisioned again on subsequent use.
Deleting jobs does not delete saved objects; deleting objects can break references
needed by jobs. Omitting IDs from job cleanup selects all terminal jobs, so prefer
explicit IDs. Active calls/jobs and provisioning locks can block full cleanup;
do not bypass these protections or remove lock files to force deletion.

Keep this skill about CLI operation. Domain-specific workflows can use these
mechanics while adding their own scientific decisions and validation criteria.
