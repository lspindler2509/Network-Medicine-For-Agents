# Network Medicine For Agents

Generate CLI access to network medicine Python packages and OpenAPI services from a TOML source registry. Agents choose and orchestrate tools; this project preserves each source's native interface.

## Development installation

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). This initial version is a Python CLI package, not yet a standalone downloadable binary.

```bash
uv sync
uv run netmed --help
```

## Generate from TOML

Edit `sources.toml`, then build the catalog:

```bash
uv run netmed build sources.toml
uv run netmed sources
uv run netmed drugstone --help
uv run netmed drugstone map_nodes --help
uv run netmed reactome --help
```

The default catalog lives at `.netmed/catalog.json` and is ignored by Git. Use `netmed --catalog /path/catalog.json build sources.toml` to change it. No hand-written function list is needed: Fire discovers Python members at invocation time; OpenAPI operations are extracted during build. `build` creates a catalog, not compiled executables or individually generated source files.

Python packages must currently be installed in the same environment. To add Drugst.one for development:

```bash
uv pip install --python .venv/bin/python drugstone
uv run netmed drugstone map_nodes --help
```

Installing a package executes third-party code; the current environment is not a security sandbox. Package dependencies and managed isolated runtimes are a next step. Fire also exposes public imported members, not only scientifically relevant functions.

An API source needs a spec and an explicit HTTPS `base_url`. Specs may be JSON/YAML or local files relative to the TOML. Operation IDs become command names; missing IDs receive deterministic method/path names. View operation help with `netmed reactome <operation-id> --help`. Scalar path/query/header parameters and JSON request bodies are supported. Original schemas are included in help. External schema references, complex parameter serialization, secured endpoints and complete request-body validation are not implemented; unsupported cases fail rather than guessing.

## Long-running processes

Any source command can use the same detached-job utility:

```bash
uv run netmed --background drugstone map_nodes ...
uv run netmed jobs
uv run netmed jobs <job-id>
```

Use real arguments from the generated help in place of `...`. Jobs write `status.json`, `result.txt`, `stderr.txt` and `worker.log` under `.netmed/jobs/<id>/`. Fire results retain their native text format; HTTP results are JSON-encoded. Workers survive closing the invoking terminal, but not a machine restart. There is no cancellation or checkpoint/resume yet. Files may contain sensitive inputs/results; use a trusted local directory.

To always use a job for one source, add `execution = "background"` inside its TOML section. Help stays in the foreground. This is an automatic **configured policy**, not prediction of runtime. We cannot reliably know in advance whether an arbitrary function will take seconds or hours. Later we can add per-operation policies and optional timeout-based detachment without rerunning the call.

## Security boundary

The initial HTTP runtime disables redirects, pins the base URL independently of the specification and does not bind API credentials yet. It does not print raw upstream exception strings. Python packages still run with the invoking process's permissions and inherited environment; only execute trusted packages. Restricted environments and provider-scoped credential injection are required before automatic execution of discovered packages.

## Roadmap and tests

See [architecture](docs/architecture.md) and [discovery](discovery/README.md). R/GraphQL, weekly web discovery, managed runtimes and release binaries are planned, not implemented.

```bash
uv run python -m unittest discover -s tests -v
```
