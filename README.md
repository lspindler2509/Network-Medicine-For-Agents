# Network Medicine For Agents

Generate agent-friendly CLI access to Python packages, OpenAPI services and GraphQL endpoints from a TOML registry. Python calls use Fire; OpenAPI commands use Restish; GraphQL uses introspection and graphql-core. Sources keep their native arguments and schemas. The calling agent chooses tools and orchestrates calls; netmed requires no embedded LLM or hosted service.

## Expanded source registry

The default registry covers scientific Python packages, public OpenAPI services and introspectable GraphQL APIs. ToolUniverse is not a runtime source. See [source integration and limitations](docs/sources.md), [future biomedical candidates](docs/nice-to-have-sources.md), and the historical [ToolUniverse inventory](docs/tooluniverse-integration-report.md) and [tool mapping audit](docs/tooluniverse-direct-coverage.md).

`sources.toml` is the current source list. Installation and discovery do not guarantee every operation works; inspect native help and actual results. Changes to the registry require a catalog or bundle rebuild. Dependency locks cover all three release targets; local execution was checked on macOS Apple Silicon, while Linux and Windows require native CI validation.

## Install and start

Install with one command. macOS (Apple Silicon) or Linux (x64):

```bash
curl -fsSL https://raw.githubusercontent.com/lspindler2509/Network-Medicine-For-Agents/main/installers/install.sh | sh
```

Windows (x64), in PowerShell:

```powershell
irm https://raw.githubusercontent.com/lspindler2509/Network-Medicine-For-Agents/main/installers/install.ps1 | iex
```

The installer selects the newest published release from GitHub’s release list (including pre-releases, excluding drafts), verifies its SHA-256 checksum and installs the entire bundle without administrator privileges. macOS/Linux uses `~/.local/share/netmed-cli/<version>` and `~/.local/bin/netmed`; Windows uses `%LOCALAPPDATA%\Programs\netmed\<version>`. It adds the command directory to your user shell/PATH configuration. Restart your terminal or agent, then run:

```bash
netmed --help
netmed networkx path_graph 4 - number_of_nodes
```

These commands download and execute this project's installer. You can inspect the [shell script](installers/install.sh) or [PowerShell script](installers/install.ps1) first. `NETMED_INSTALL_DIR` overrides the application directory, and `NETMED_MODIFY_PATH=0` disables persistent PATH changes. Stop jobs before removing an installed version. No scientific package or runtime data is deleted by installation.

To install a specific release on macOS/Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/lspindler2509/Network-Medicine-For-Agents/main/installers/install.sh | sh -s -- --version v0.0.1
```

In PowerShell, pass the parameter to the downloaded script block:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/lspindler2509/Network-Medicine-For-Agents/main/installers/install.ps1))) -Version v0.0.1
```

Omitting the parameter (or specifying `latest`) selects the newest published release.

### Manual download

Download a CLI bundle from [GitHub Releases](https://github.com/lspindler2509/Network-Medicine-For-Agents/releases). Open a release and choose the matching file under **Assets**:

| System | Archive |
| --- | --- |
| macOS, Apple Silicon (M1 or later) | `netmed-darwin-arm64.tar.gz` |
| Linux, Intel/AMD x64 | `netmed-linux-amd64.tar.gz` |
| Windows, Intel/AMD x64 | `netmed-windows-amd64.zip` |

Extract the archive and keep the **entire `netmed/` folder** together. The automatically listed “Source code” downloads contain the repository, not the built CLI. No repository checkout or separate Python, uv or Restish installation is needed for these bundles.

From the directory containing the extracted folder, on macOS/Linux:

```bash
./netmed/netmed --help
./netmed/netmed sources
```

Windows PowerShell:

```powershell
.\netmed\netmed.exe --help
.\netmed\netmed.exe sources
```

Add the absolute directory containing the executable to your user PATH to use `netmed` from any terminal or agent. Keep its supporting files beside it. Scientific packages and their Python runtimes are installed automatically on first use, which requires internet. API calls require internet too.

You can give your agent this instruction:

> Install netmed using the installer linked in https://github.com/lspindler2509/Network-Medicine-For-Agents#install-and-start for my operating system. Verify `netmed --help` and `netmed networkx path_graph 4 - number_of_nodes`. Tell me where the CLI and its managed data are stored.

The application folder holds shipped code and executables; mutable environments, jobs, objects and history use a separate user-data directory, configurable once through `NETMED_DATA_DIR`. Development builds and dependency provisioning execute trusted package code; they are not security sandboxes.

## Build the CLI

Supported initial targets: `darwin-arm64`, `windows-amd64`, and `linux-amd64`. Builds automatically select the versioned locks for the current target. Run from the repository root. The build machine needs Python 3.11+ and **uv 0.12.23**; the build dependency group pins PyInstaller 6.22.3. CI uses Python 3.13.3 for the core CLI.

```bash
uv sync --locked --group build
uv run --group build python scripts/build_cli.py
./dist/netmed/netmed --help
```

Windows PowerShell:

```powershell
uv sync --locked --group build
uv run --group build python scripts/build_cli.py
./dist/netmed/netmed.exe --help
```

The script discovers sources, exports target-specific dependency locks and API specifications, bundles the application with PyInstaller, and creates an archive plus SHA-256 checksum under `dist/`. Build caches are under `.build/`; if `NETMED_DATA_DIR` is already set, discovery environments use that directory. The first build may take minutes because it installs scientific packages for discovery. Later builds reuse dependency environments and discover each selected Python source once. Export reuses metadata when source configuration and dependency lock match; changed inputs trigger fresh discovery. API discovery/export use the same local specification snapshot.

To build only selected sources, select them before installation/discovery:

```bash
uv run --group build python scripts/build_cli.py --source networkx --source reactome
```

The result is a **directory bundle**, not a single-file executable. Keep the complete `dist/netmed/` directory together. It contains the command, core Python runtime/dependencies, packaged worker, uv, Restish, catalog, locks and API specs. Users of the bundle do not need a separate Python, uv or Restish installation. Scientific packages and their exact Python interpreters are installed on demand; those installations and remote API calls need internet.

Build on each target OS/architecture. Locally verified: macOS arm64. Linux and Windows are configured in CI but their artifacts still need validation. A matching version tag (for example `v0.0.1`) or manual release dispatch creates a draft after successful quality checks and all three builds; see [release instructions](docs/releases.md#create-a-release-draft). Publication is manual.

## Run the built CLI

Examples below use `netmed` to mean the built executable. Use `./dist/netmed/netmed` on macOS/Linux, `./dist/netmed/netmed.exe` on Windows, or add its containing directory to PATH. Keep the supporting bundle files beside it.

```bash
netmed --help
netmed drugstone --help
netmed drugstone map_nodes --help
netmed docs drugstone
netmed networkx path_graph 4 - number_of_nodes
netmed reactome --help
netmed reactome get-db-version
```

Overall help shows source names, types and short descriptions without importing packages. Discovered Python interfaces are stored per source as gzip-compressed files in `<catalog-stem>-discovery/` next to the catalog and read only for that source's help; keep this folder together with the catalog when copying it. Use source help to explore the available commands. Python source help lists discovered operations; operation help shows signatures and docstrings. Missing operation help falls back to live Fire. Python submodule paths use spaces, for example `netmed nedrex core get_edges --help`. API command names/arguments use native Restish syntax, including kebab-case names and positional path arguments. Read source help before calling.

`docs <source>` loads PyPI descriptions for the configured/resolved package version without installing the package. Local Python sources use installed distribution metadata. API docs read `info`, `tags` and `externalDocs` from the selected specification; the built CLI uses its bundled snapshot. Documentation links are displayed, not fetched. `sources` prints the full catalog as JSON.

## Develop

### Change the CLI or its default registry

Edit `src/netmed/`, build helpers, or `sources.toml`, then rebuild:

```bash
uv run --group build python scripts/build_cli.py
./dist/netmed/netmed --help
```

The existing binary does not automatically pick up source changes. No automatic rebuild/watch mode is implemented. CLI/worker changes reuse scientific dependency environments when their configuration is unchanged. Build output replaces the existing bundle, so stop jobs using that bundle before rebuilding.

For source-only debugging, `uv run netmed ...` remains available. API discovery/execution then needs an explicit Restish path; after a native build, on macOS/Linux:

```bash
export NETMED_RESTISH="$PWD/.build/native/restish"
uv run netmed --catalog .netmed/source-catalog.json build sources.toml
uv run netmed --catalog .netmed/source-catalog.json --help
```

On Windows set `$env:NETMED_RESTISH = "$PWD/.build/native/restish.exe"`. Source-only execution requires uv on PATH or `NETMED_UV`; the built CLI already contains both executables.

### Develop a local Python package

Use a separate TOML and writable development catalog. Paths are relative to the TOML file:

```toml
# sources.dev.toml
[sources.my_package]
kind = "python"
path = "../my-package"
module = "my_package"
python = "3.11"
dev = true
submodules = true
```

```bash
netmed --catalog .netmed/dev-catalog.json build sources.dev.toml
netmed --catalog .netmed/dev-catalog.json my_package --help
netmed --catalog .netmed/dev-catalog.json my_package some_function --help
```

`dev = true` installs the package editable. Implementation changes in that package are used on the next call without rebuilding the CLI. Rebuild the **development catalog** after changing signatures/docstrings or adding operations. Tracked packaging configuration changes select a new environment. Compiled extensions, new files or changed package layout may require reinstalling through such a configuration change. Custom dependency files are not tracked automatically.

Without `dev = true`, local packages are installed normally; Python-file timestamps and tracked packaging configuration participate in environment identity. Local packages are mutable development inputs and cannot be exported in release bundles. Keep their checkout available while using their environment.

## Add sources

No handwritten function list or per-provider adapter is required for compatible interfaces:

```toml
[sources.example_python]
kind = "python"
package = "distribution-name"
module = "import_name"
version = "==1.2.3"
python = "3.11"
# Optional description overrides distribution Name/Summary metadata.
# description = "Short explanation of the source."
# submodules = true
# discovery = "lazy"
# discovery_timeout = 120
# dependencies = ["additional-requirement==1.0"]
# setup = [{call = "config.set_endpoint", args = ["https://example.org"]}]

[sources.example_api]
kind = "openapi"
spec = "https://example.org/openapi.json" # A local spec path also works.
base_url = "https://example.org"
```

`package` is the installable distribution name; `module` is the Python import name. Python versions are selected per source and may differ from the core CLI. Build discovery always traverses the public submodules of the configured package: attached modules keep their attribute path (for example `scanpy tl leiden`), unattached ones are imported during discovery and imported on demand when a call path names them. Private modules, foreign imports and conventional `test`/`tests`/`testing`/`conftest`/`setup`/`examples`/`benchmarks` packages are skipped; traversal stops at depth 3, 400 modules or half of `discovery_timeout` and records skipped or failed submodules under `omitted`. Objects re-exported under a shorter path are listed once. Configure `module` as the package root unless a narrower import is intended. `submodules = true` additionally imports every public submodule before each call, for packages whose import registers behavior. `setup` runs configured public calls before invocation, not during discovery. `discovery = "lazy"` skips build-time Python introspection and uses live Fire help. API overview metadata comes from `info.title`/`info.summary`. Optional `description` overrides the displayed summary. `netmed --catalog .netmed/experimental.json build sources.toml --source networkx` also supports early selection. `enabled = false` retains a candidate with a `disabled_reason` but excludes it from execution.

Rebuild the CLI to update its bundled default registry. For an experimental registry, generate a separate catalog with `netmed --catalog .netmed/experimental.json build sources.experimental.toml`, then pass the same `--catalog` when calling it. **Always choose a writable catalog path for development builds; the bundled default belongs to the installed application.**

Discovery imports packages and may execute import-time code. It inspects public functions, classes, methods and callable instances without running analysis functions or instantiating classes. Only configure trusted packages and setup calls. No authentication/API-key configuration is implemented.

## Data and dependencies

One `NETMED_DATA_DIR` setting controls mutable data. Without it, netmed uses the platform user-data directory. For repository development:

```bash
export NETMED_DATA_DIR="$PWD/.netmed"
```

Windows PowerShell:

```powershell
$env:NETMED_DATA_DIR = "$PWD/.netmed"
```

Persist an absolute path in your shell configuration if wanted. Existing data is not moved automatically. `--catalog` selects only a catalog, not another data directory.

| Location | Contents |
| --- | --- |
| Installed CLI bundle | Executables, core Python, worker, default catalog, locks and API specs |
| `.build/` | Disposable build caches/resources and PyInstaller log |
| `dist/` | Built application directory, archive and checksum |
| `<data>/environments/` | Managed dependency environments, requirements locks and installed-package metadata |
| `<data>/runtimes/` | uv-managed Python interpreters |
| `<data>/restish/` | Native API configuration/cache referencing the selected specifications |
| `<data>/api-updates/` | Local API overrides and immutable refreshed schema snapshots |
| `<data>/jobs/` | Background status, execution settings and output |
| `<data>/objects/` | Saved Python objects and metadata |
| `<data>/logs.txt` | Timestamped command history |

There are no runtime `tools/` downloads or `workers/` copies. Scientific environments are isolated by Python/dependency configuration and target; compatible configurations can reuse an environment. Environment identity excludes worker code. The built catalog uses exact target-specific locks; source-only catalogs may resolve newer transitive dependencies when rebuilt. `prepare <source>` prepares a Python environment explicitly; `environments` lists existing ones. Avoid removing environments used by running jobs.

## Python and API syntax: a short guide

Python sources retain Fire syntax; API sources retain Restish syntax. Check native operation help before choosing arguments.

```bash
# Fire: a quoted list and a native keyword argument.
netmed stringdb get_interaction_partners '["EGFR"]' --limit=10 - to_csv --index=False
# Fire: dictionary input, then an exporter on the returned DataFrame.
netmed pandas DataFrame '--data={"gene": ["EGFR", "TP53"]}' - to_json --orient=records
# Restish: JSON output (already netmed's API default).
netmed clinicaltrials version --rsh-output-format=json
```

Fire treats return values as navigable Python objects. If the final computed value is not handled as a printable value and lacks a custom `__str__`, netmed intercepts Fire's object-help fallback and tries native JSON export, then a Pickle snapshot if needed. A custom `__repr__` alone does not select Fire's automatic value output. The `-` separator ends the previous call's arguments; following tokens act on its returned object. Use native methods such as `- to_csv --index=False`, `- to_json --orient=records`, `- tolist`, or `- __repr__`, where the returned type supports them. Text representations may truncate; request a native export when the full result is needed.

Choose the result form before a long background call: append the native exporter to retain text/CSV/JSON in `result.txt`, or explicitly use `--save-object LABEL` when the Python object is needed later. Objects are saved automatically only when Fire would otherwise show result-object help and a native JSON export is unavailable or fails. Python-package progress can still appear in normal stdout, so a JSON-returning method alone does not guarantee clean machine-readable output for every package. Job `completed` reports successful process execution, not validation of the scientific result or its output schema.

Fire's literal parsing is not a general JSON decoder: use Python spellings `True`, `False` and `None` for boolean/null arguments. Its Python embedding API supports `serialize=...`, but netmed currently has no general Python `--format json` flag. Restish has output controls such as `--rsh-output-format=json`, `--rsh-output-format=table`, and `--rsh-filter`; these change presentation rather than the server's response negotiation. Native body shorthand such as `'nodes: [1, 2]'` is Restish syntax for an operation accepting that body, not a universal biomedical schema.

Object exchange does not merge environments. For example, loading a saved pandas DataFrame requires pandas in the receiving environment. When the next package only needs rows or edges, convert them with native methods in the producing worker and explicitly save the resulting built-in list/dictionary. If it needs the original class, declare compatible dependencies for the receiving source and update its locks. No object-dependent package installation occurs automatically.

References: [Python Fire guide](https://google.github.io/python-fire/guide/) and [Restish output formats](https://rest.sh/docs/reference/output-formats/).

## Background jobs and history

Global options go before the source. Replace `<job-id>` and `<id>` placeholders in examples with actual returned IDs:

```bash
netmed --background nedrex core get_edges protein_interacts_with_protein --limit=3
netmed jobs
netmed jobs <job-id>
netmed jobs active
netmed jobs kill <job-id>
netmed jobs clean <job-id> --dry-run
netmed jobs clean <job-id>
netmed logs --tail 20
```

Only `--background` calls (or sources configured with `execution = "background"`) create jobs. Preparation happens first; then a detached worker starts and the CLI returns a UUID job ID. stdout is saved as `result.txt`, diagnostics as `stderr.txt`, launcher errors as `worker.log`. Status and execution settings are stored alongside them. Lifecycle transitions are checked centrally: queued → running → completed/failed/cancelled; queued jobs can also fail or be cancelled. Terminal states cannot be restarted or overwritten. Active output includes tool, start time and elapsed duration. `kill` verifies the worker and stops its process group/tree using platform-specific handling, retaining partial output. `clean` accepts multiple IDs or all terminal jobs when no IDs are supplied; it preserves queued/running jobs.

Foreground calls wait. An agent may stop a slow call and restart it with `--background` when repeating it is appropriate; execution starts again from the beginning. There is no automatic timeout/switch, restart recovery or server-side task cancellation. The agent handles polling/cancelling provider tasks through their source interface. After a reboot, persisted job state may remain `running`; `jobs active` reports only recognized live workers.

Every invocation, including help and failed calls, appends `[timestamp] command` to `logs.txt`. No environment variables or working directory are logged. History records commands, not results or complete data provenance. Normal output can be piped to terminal utilities such as `tail`; package-specific progress/output formats are preserved.

## Reuse Python objects

Save a return value when another call needs the actual Python object:

```bash
netmed networkx path_graph 4 --save-object graph
# {"saved_objects": [{"id": "<id>", "label": "graph", "type": "networkx.classes.graph.Graph"}]}
netmed networkx number_of_nodes '@object:<id>'
netmed objects
netmed objects <id>
netmed objects clean <id> --dry-run
```

The label is descriptive; references use the returned ID. Objects are stored separately from jobs using standard-library Pickle protocol 4. `@object:<id>` loads the whole object in the destination worker. Quote selectors such as `'@object:<id>[0]'` or `'@object:<id>["graph"]'` to select built-in tuple/list/dictionary members. Nested selectors work; attributes, slices and arbitrary expressions do not. Bundle metadata shows up to 20 immediate selectors/types without unpickling. The whole Pickle is loaded before selection; repeated references share one root object during a call.

`--save-object LABEL` saves the final return value after Fire method chains; progress goes to stderr and stdout contains saved-object metadata. If a function mutates its input and returns None, use `--save-updated-object <id>` to save the loaded input under a new ID. Original snapshots stay unchanged. Background jobs support the same options. Cleaning jobs does not delete objects, and object cleanup does not protect inputs needed by active jobs.

Required classes must be importable in the destination environment; version differences are not automatically rejected or reconciled. Only use trusted locally generated objects: Pickle loading executes reconstruction code. Graphs, arrays and DataFrames can often be saved; live generators, open connections and some file-backed objects/callbacks cannot. Normal output can consume iterators progressively; iterators are not automatically materialized or saved. Other non-printable results use the conditional JSON/snapshot fallback described below. Use the package's own loaders/converters/exporters through its CLI instead. Dependencies do not become CLI sources automatically; configure another package explicitly if its interface is needed.

For a small callback, an explicit quoted lambda is supported:

```bash
netmed networkx subgraph_view --G='@object:<id>' \
  --filter_node='@lambda:lambda node: node != 1' - number_of_nodes
```

Lambdas execute Python code with worker permissions, with Python builtins but no implicit package aliases. This is not a sandbox. Results retaining lambdas are generally not Pickle-compatible; choose an explicit package-native materialization method if needed.

## API behavior and limitations

- OpenAPI 3.0/3.1 is supported through Restish; Swagger 2 and automatic discovery from a plain REST API URL are not implemented. GraphQL endpoints require public introspection. Existing Python clients are an alternative. Release specs must be self-contained; external `$ref` files need external bundling first.
- JSON request-body validation is enabled for operations exposing Restish JSON validation. It does not validate scientific meaning or every parameter/media type. Explicitly use `--rsh-validate=false` for an inaccurate schema; validation is never silently bypassed. `--rsh-generate-body` shows a schema-derived example. Wildcard media types may require explicit `--rsh-content-type application/json`.
- Restish supports multipart uploads and several query/path array styles including deepObject. URL-encoded body arrays use bracket keys such as `genes[]`; not every provider's form encoding is supported.
- Restish follows recognized next links with a default 25-page cap that warns but exits successfully. `--rsh-max-pages 0` removes that cap, for example `netmed --background <source> <operation> --rsh-max-pages 0`. No generic offset/page/cursor inference is implemented. Packages may handle their own pagination.
- For whole-body API file uploads, use a relative `@file` path (for example `@payload.bin`) from the file's directory. Restish can interpret the colon in a Windows drive-letter path as body shorthand. Multipart field file references are a separate input form.
- Python discovery is a static, potentially incomplete snapshot. Dynamically created interfaces can be absent; known paths remain callable and uncached help falls back to Fire. Live Fire help is also not guaranteed exhaustive.
- Object reuse is not universal JSON-to-object conversion, dependency merging or type reconciliation. Structured stdin-to-Python-argument piping is not implemented.
- Packages requiring Conda/Pixi or separately installed system libraries cannot be provisioned by the current uv backend. Compatible native wheels are supported. R, authentication and checkpoint recovery are not implemented.

## Tests and GitHub Actions

```bash
uv run python -m unittest discover -s tests -v
```

Optional integration checks: `NETMED_PROCESS_TESTS=1` verifies real process management; `NETMED_RESTISH_TESTS=1` verifies native requests against a temporary local capture server; `NETMED_BINARY_TESTS=1` verifies the built executable with no developer tools on PATH. They need network access for initial dependencies and permission to manage test processes/bind a local port as applicable.

After building, on macOS/Linux:

```bash
NETMED_PROCESS_TESTS=1 NETMED_RESTISH_TESTS=1 NETMED_BINARY_TESTS=1 \
  uv run python -m unittest discover -s tests -v
```

Windows PowerShell:

```powershell
$env:NETMED_PROCESS_TESTS = "1"
$env:NETMED_RESTISH_TESTS = "1"
$env:NETMED_BINARY_TESTS = "1"
uv run python -m unittest discover -s tests -v
Remove-Item Env:NETMED_PROCESS_TESTS, Env:NETMED_RESTISH_TESTS, Env:NETMED_BINARY_TESTS
```

[Tests workflow](.github/workflows/test.yml) runs on pushes and pull requests. [CLI build workflow](.github/workflows/build.yml) runs on PRs, main/version-tag pushes and manual dispatch, builds on Linux/macOS/Windows and uploads archives/checksums. Version-tag runs and manual release dispatches create a release draft after all checks pass; publication remains manual. CPU architecture coverage, reviewed release locks, licenses/notices and signing/install/update UX remain distribution work.

See [file-by-file architecture](docs/architecture.md) and [release details](docs/releases.md). Guides: [PyInstaller bundling](https://pyinstaller.org/en/stable/operating-mode.html) and [uv tool installation](https://docs.astral.sh/uv/guides/tools/).

## Quality checks and license

```bash
uv sync --locked --group lint
uv run --group lint ruff check .
uv run --group lint ruff format --check .
uv run python -m unittest discover -s tests -v
```

Ruff checks syntax and selected correctness errors and separately verifies formatting without modifying files. To apply formatting locally, run `uv run --group lint ruff format .`. Pull requests build and test the native bundle on macOS arm64, Windows x64 and Linux x64. Lint and tests run on every push and pull request. The native builds run on pull requests and pushes to main. Checks provide review feedback; no required merge checks or branch restrictions are imposed. Ruff caches development results under `.build/ruff/`, outside the netmed user-data directory.

Update scientific locks deliberately with `uv run python scripts/update_locks.py --all` for all supported platforms, or `--target <target>` for one platform. Commit the complete target directory including its manifest. Resolution for another target is possible, but does not replace a native CI build/test. Ordinary CI builds consume the committed locks and fail on missing locks, changed registry dependency inputs or checksum mismatches. See [release details](docs/releases.md).

`netmed logs --clear` deletes the complete history file, including the clear invocation. Later commands create a new file. Command arguments are recorded verbatim; clearing history is not secret redaction.

This project is distributed under the [MIT license](LICENSE), with attribution to the contributors at daisyBio, Technical University of Munich. Bundled dependencies retain their own licenses; a complete third-party notice inventory is still required before public distribution.

### Fire results, snapshot labels and environment boundaries

A standalone `-` chains methods on the returned Python object. To choose a specific
format instead of the automatic JSON/snapshot fallback, select a native exporter:
`netmed stringdb get_interaction_partners '["EGFR"]' --limit 10 - to_csv`.
DataFrames also support `- to_json`; arrays often support `- tolist`; an object's
`- __repr__` provides its text representation. These methods depend on the returned
type. Automatic output first uses native `__str__()` text or Fire's simple-value/container
output, then supported JSON export, then a Pickle snapshot. Successful JSON export
adds no diagnostic message; use `--save-object LABEL` to keep the original Python
object rather than its text/JSON representation.
There is no universal CSV conversion. When Fire would otherwise show object help
for a computed result, netmed tries a native `to_json()` or `tolist()` exporter. It
validates the exported JSON without converting unknown values to strings. If no
exporter is available or export fails, it saves the original result as a Pickle
snapshot and prints `saved_objects` (ID, label, type), `output_format` and `reason`.
Export does not preserve Python types; use `--save-object` explicitly when you need
the original object. Snapshot failure exits nonzero, and background jobs then fail.
The calculation is never repeated by this fallback. Explicit help and navigation
of modules/classes/functions retain native help. Native printable values and
streaming iterators retain their original output. Background
jobs use the same Fire behavior, with output written to `result.txt`.

After `--save-object lung_graph`, both `@object:<id>` and `@object:lung_graph` work,
including bracket selectors. Repeated labels require an explicit ID; netmed never
silently chooses a snapshot. IDs take precedence over labels that look like IDs.
`objects <label>` and `--save-updated-object <label>` also accept labels. Background
references are resolved when the worker executes; use IDs to pin a particular snapshot.

Pickle preserves complex Python objects but does not include their packages. Loading
a DataFrame requires pandas in the receiving environment. Explicitly convert to
portable built-in containers or export a file in the original source first, or declare
compatible dependencies for the receiver. For example:

```sh
netmed pandas DataFrame '--data={"gene": ["EGFR"]}' - to_dict --orient=records --save-object genes
```

Environments are never merged automatically.

### Remove managed data

`netmed clean --all --dry-run` lists the managed subfolders that would be deleted.
`netmed clean --all` removes `jobs`, `objects`, `environments`, `runtimes` and
`restish` and `api-updates`, including their saved results, caches and local API overrides. The data directory itself,
root files (including `logs.txt` and `catalog.json`) and other folders remain.
Packages will be provisioned again on next use. Active CLI calls, nonterminal jobs,
recognized live job workers and provisioning locks prevent deletion. Cleanup rejects
symlink target folders and unsafe roots; links inside a deleted folder are unlinked
without deleting their external destinations. A crashed operation may leave a
coordination gate or cleanup marker: cleanup refuses rather than assuming it is safe.

### Inspect saved object contents with Fire

```sh
netmed objects <id-or-label>          # metadata and a 500-character argument preview
netmed objects <id-or-label> --full   # complete original arguments
netmed objects show <id-or-label>    # native text or supported JSON export
netmed objects show <id-or-label> --help
netmed objects show <id-or-label> - to_csv --index=False
netmed objects show <id-or-label> - to_json --orient=records
netmed objects show <id-or-label> - __repr__
```

`show` loads the trusted snapshot in its recorded original environment and passes
it directly to Fire. Available methods, parameter parsing and help come from that
object; netmed does not define CSV adapters or per-type method lists. If text/JSON
is unavailable, it prints metadata and an exploration hint, without creating another
snapshot. Explicit native exporters report their own errors. Methods may mutate the
in-memory object; snapshots remain immutable unless a new snapshot is explicitly saved.
The original environment must still exist; inspection does not reinstall dependencies.
Metadata inspection never unpickles, and truncation does not alter stored arguments.

### Filtered and hierarchical cached Python help

Python overviews hide operations whose recorded `defined_in` belongs to a different
top-level import package. Unknown origins remain visible. Package ownership uses an
exact name or dotted-prefix match, never distribution-name guesses or a per-package
allowlist. The catalog retains all operations; explicit operation help and execution
are unaffected. API help remains native Restish help.

```sh
netmed nedrex --help
netmed nedrex --help --full
netmed networkx algorithms --help
netmed networkx algorithms centrality --help --full
```

At most 50 visible operations under a selected help group are displayed flat with
signatures and first docstring lines. Larger overviews show the next help-group level
and direct operations. Groups use defining-module paths for package-owned aliases,
with exposed object paths as a fallback; private definition segments are not exposed.
These are help navigation paths: entries always print their original callable paths,
which may differ from the group path. No synthetic execution aliases are created.
If more than 50 direct operations cannot be further grouped, the first 50 names are
shown, with `--full` providing the rest. `--full` lists all entries under the selected
group, including foreign exports; full class help also includes recorded members.
Small sources retain their flat presentation. Cached data comes from the existing
catalog; missing operation help still falls back to Fire. Lazy discovery remains
native Fire help and does not receive this cached-overview filtering.

The general overview shows executable sources only; `netmed sources` retains disabled
entries. Generic specification titles such as "OpenAPI definition" use the source
name in the overview, preserving the provider metadata itself.

For dictionary/list/tuple snapshots without native text/JSON output, `objects show`
prints a bounded immediate structure first: up to 20 keys/indices and their value
types, total length and completeness. This reuses the generic snapshot structure
helper in the original worker and also works for older snapshots. No DataFrame
contents are evaluated and no new snapshot is created. Fire can independently
explore keys and methods with `objects show <id> --help`.

The two navigation syntaxes have different purposes:

```sh
# An argument reference selects a built-in dictionary entry before an operation:
# '@object:<id>["z_score"]'
# Native Fire navigation on a loaded snapshot:
netmed objects show <id> z_score - to_csv
```


## GraphQL sources

Open Targets, DGIdb, gnomAD and Pharos/TCRD use the same generic GraphQL backend.
Declare a public endpoint; build-time introspection discovers its schema:

```toml
[sources.example]
kind = "graphql"
endpoint = "https://example.org/graphql"
description = "Describe the source purpose here."
# timeout = 60
```

There is no provider adapter, handwritten operation list or schema-file input.
Introspection must succeed before the source enters the catalog. Full schemas
are separate, hashed snapshots; catalog and background jobs reference them.
Release bundles include relative schema paths. Schema help works offline after
building, and a catalog rebuild or `sources update` refreshes the snapshot. Existing background jobs
keep their immutable schema reference.

Explore and execute directly, without a query file (macOS/Linux shells):

```sh
netmed opentargets --help
netmed opentargets schema
netmed opentargets schema Target
netmed opentargets query 'query($id: String!) { target(ensemblId: $id) { id approvedSymbol } }' --variables '{"id":"ENSG00000146648"}'
netmed --background opentargets query '{ target(ensemblId: "ENSG00000146648") { id approvedSymbol } }'
```

In PowerShell, pass the same query and variable strings as single-quoted arguments:

```powershell
netmed opentargets query 'query($id: String!) { target(ensemblId: $id) { id approvedSymbol } }' --variables '{"id":"ENSG00000146648"}'
```

`schema` shows root query fields and available type names. `schema <Type>` shows
native fields, argument types/defaults, input fields or enum/union details, with
provider descriptions. `netmed docs <source>` also shows the cached schema overview.
`query --help` documents the common CLI options. Use `--operation-name NAME` when
supplying more than one named query in the document.

`graphql-core` parses and validates queries and variables against the snapshot
before any request. Only read-only queries are supported; documents containing
mutations or subscriptions are rejected. The shared transport sends the standard
JSON GraphQL request with POST. Authentication, streaming and automatic pagination
are outside the current scope; specify limits/cursors in the native query yourself.

Output preserves the provider JSON envelope (`data`, `errors`, `extensions`).
HTTP failures, GraphQL errors (including partial data), and null/missing data exit
nonzero. Partial data remains visible. Background calls use the same runtime,
retain the response in `result.txt`, and mark such calls `failed`. Invalid local
queries/variables exit 2 without contacting the endpoint. GraphQL responses are
JSON values, not Python Pickle objects; Python snapshots remain a separate feature.

To run generic local HTTP contract tests, set `NETMED_GRAPHQL_TESTS=1`. CI enables
these tests on Linux, macOS and Windows. Live provider checks are manual and are
not part of the deterministic test suite.


## Refresh API schemas and help

```sh
netmed sources update                         # All active OpenAPI/GraphQL sources
netmed sources update opentargets dgidb       # Only these sources
netmed sources update --dry-run               # Preview all API changes
netmed sources update pharos --dry-run        # Preview one source
```

The same commands work in PowerShell. Python packages, versions and dependency
locks are excluded. Explicit Python selections are rejected before making requests;
use a catalog build for Python metadata changes and deliberate package upgrades.

Refresh fetches each original OpenAPI URL or performs GraphQL introspection, then
validates the schema with the existing backend. It does not require a CLI rebuild.
The CLI reports progress on stderr and a JSON summary on stdout, with per-source
status, schema changes, GraphQL root-query counts before/after and elapsed time.
Restish does not reliably expose command counts for local OpenAPI snapshots, so
refresh summaries omit those counts. Any failed
source makes the command exit nonzero, while successful changes are still activated.
Unchanged schemas retain their existing references.

Without `--catalog`, successful changes are stored under
`NETMED_DATA_DIR/api-updates` as a small local overlay and immutable snapshots.
Normal help, execution, docs, source listings and new jobs automatically use them.
The shipped catalog and Python sources are retained. Overrides apply only while
source kind, endpoint/base URL and original specification URL still match the
registry; current registry settings and descriptions are preserved across installs.
An explicit `--catalog PATH` bypasses the overlay; updating then atomically changes
that writable catalog instead. Installed bundled assets remain read-only.

`--dry-run` fetches and validates in temporary directories and reports proposed
changes without activating snapshots, modifying catalogs or updating execution
caches. Normal invocation logging still applies. An update failure retains the
previous working interface. Existing jobs keep their old snapshot/backend references;
no scientific query or previous command is automatically retried. Updates are
serialized, and `clean --all` removes local overrides/snapshots along with the other
managed subfolders. No update is scheduled automatically.

OpenAPI bundles retain `spec_origin` so refresh can retrieve the provider URL rather
than re-read their bundled snapshot. Older catalogs without a remote origin must
first be rebuilt. Local specification files remain build inputs, not remote refresh
sources. New sources and source configuration changes still require a registry build.
