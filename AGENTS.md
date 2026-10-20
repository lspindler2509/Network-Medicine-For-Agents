# Project guide

## Purpose

`netmed` generates CLI access to Network Medicine packages and APIs from a TOML source registry. Python interfaces are discovered in isolated uv environments and invoked through Fire; OpenAPI descriptions generate API operations. Preserve source-native signatures and schemas rather than introducing a universal biomedical data model. The calling agent handles orchestration; this project does not need an embedded LLM or a hosted service.

## Automatic generation concept

The central idea is to declare a source once and derive CLI access from its existing interface. Adding a compatible package or API should normally require a TOML entry, not a handwritten adapter for every function. Preserve different providers' input schemas: an agent can learn them through source and operation help.

The current pipeline is:

1. **Declare sources:** TOML specifies a Python package/module (or local package path), or an OpenAPI specification URL/file and API base URL. Optional source configuration supplies versions, submodule discovery and setup calls. No explicit function list is required.
2. **Build the catalog:** `netmed build sources.toml` validates the registry and runs the appropriate importer. Python discovery provisions a managed environment and introspects public interfaces, signatures and docstrings in the worker. OpenAPI import reads overview metadata and prepares Restish-generated commands from the specification.
3. **Store interface metadata:** The generated catalog contains routing information, overview metadata and, per Python source, a reference to a gzip-compressed discovery file in `<catalog-stem>-discovery/` (checksum, configuration and lock hashes). Discovered help is read from that file only when a help request needs it; ordinary calls and overall help never load it. It does not contain generated implementations of every scientific function. Python supports lazy discovery as an alternative to the build-time snapshot.
4. **Expose commands and help:** The generic CLI routes `netmed <source> ...` to the appropriate runtime. Python execution uses Fire against the actual package; API execution forwards native arguments to the pinned Restish binary. Cached Python help avoids starting a package worker where possible; live Fire help remains available for dynamic interfaces.
5. **Execute with shared infrastructure:** Dependency provisioning, foreground/background execution and job management apply across sources. Pagination and scientific algorithms remain the responsibility of the underlying package or API; generation does not invent these behaviors.

For agents, overall help exposes available sources, `netmed find` ranks operations across sources by keywords, and source/operation help reveals the relevant interface on demand. Search derives its text only from discovered interfaces and source descriptions; do not add search-specific descriptions, synonyms or per-source tuning. Do not preload every operation's documentation into the agent's context. The agent chooses tools, supplies their native arguments and decides whether to run a call in the background.

Generation is programmatic and does not require an LLM to write adapters. Its coverage depends on the source interface: missing docstrings remain missing documentation, unsupported OpenAPI features need improvements to the generic importer/runtime, and complex Python objects or dynamic interfaces may require explicit handling. Do not claim that discovery makes every exposed function usable or documents undocumented nested parameter schemas.

Prefer improving generic support or the upstream package's public interface over adding provider-specific code. Keep optional configuration declarative; exceptions should be explicit and justified rather than silently presented as automatic integration.

The distribution goal is a small CLI installation with a prebuilt catalog and automatic provisioning of the needed Python runtime/packages at first use. Direct API calls need no provider package environment. Development builds a target-specific PyInstaller directory bundle through scripts/build_cli.py. CLI changes require rebuilding. The bundle includes uv, Restish, worker, locks, catalog and self-contained API specs.

Future source discovery is a separate stage: a scheduled search, potentially assisted by an LLM, could propose packages and specification URLs. Candidates would require validation and review before entering the registry. Searching for sources and generating CLI access from accepted sources must remain separate responsibilities. R support would extend the same source/importer/runtime model but is not implemented.

## Structure and responsibilities

| Location | Responsibility |
| --- | --- |
| `sources.toml` | Declarative source configuration, including package versions, local paths and API specs. |
| `src/netmed/cli.py` | Argument parsing, command routing, help and user-visible output. No direct job-file access. |
| `src/netmed/catalog.py` | Registry validation and catalog construction. |
| `src/netmed/importers/python.py` | Python interface discovery and cached help. |
| `src/netmed/importers/graphql.py` | Public introspection discovery and immutable schema snapshots. |
| `src/netmed/graphql/` | Generic schema loading/help and GraphQL-over-HTTP transport. |
| `src/netmed/runtime/graphql.py` | Direct read-only queries and shared foreground/background execution. |
| `src/netmed/importers/openapi.py` | OpenAPI overview/docs reading; delegate command generation to Restish. |
| `src/netmed/runtime/object_store.py` | Inspect/list/clean local object metadata and parse reserved save options; never unpickle in the core CLI. |
| `src/netmed/runtime/python.py` | Shared Python invocation and environment compatibility checks for foreground and background execution. |
| `src/netmed/runtime/restish.py` | Isolated Restish configuration, native API discovery/help/execution. |
| `src/netmed/runtime/restish_binary.py` | Locate bundled Restish or an explicit source-development override; no runtime downloading. |
| `src/netmed/runtime/environments.py` | uv provisioning, dependency identities, installation locks and local development environments. |
| `src/netmed/runtime/processes.py` | Child environments, source/frozen launch commands, explicit external setup, detachment, identity checks and platform-specific termination. |
| `src/netmed/runtime/jobs.py` | Job persistence, status transitions, inspection, cleanup and execution coordination. |
| `src/netmed/runtime/command_log.py` | Append timestamped command text to the platform data-directory history. |
| `src/netmed/worker/` | Independent shipped worker package: entry, discovery, metadata, invocation, objects and callbacks; no core imports. |
| `src/netmed/documentation.py` | On-demand package/API documentation, separate from execution. |
| `src/netmed/runtime/job_state.py` | Pure lifecycle transition rules; terminal states are immutable. |
| `src/netmed/runtime/layout.py` | Central data directory and installed resource paths. |
| `src/netmed/errors.py` | Locally authored errors safe to show to users. |
| `tests/` | Unit tests and optional real-process integration tests. |
| `README.md` | Installation, CLI usage and local package development instructions. |
| `docs/architecture.md` | Architecture, limitations and future work. |
| `src/netmed/building/` | Build-only verified native downloads; never runtime provisioning. |
| `scripts/build_cli.py` | Native CLI bundle and archive generation; no publication. |
| `.github/workflows/test.yml` | Linux, macOS and Windows test matrix. |

Catalogs are generated: the built CLI defaults to its installed assets/catalog.json, while source mode defaults to <netmed-data-directory>/catalog.json. Use an explicit writable --catalog path for development generation. Do not edit it manually or commit runtime artifacts. Managed package environments live in the platform data directory, unless `NETMED_DATA_DIR` overrides it. The same data directory holds `jobs/`, `logs.txt`, `environments/` and `runtimes/`. One `NETMED_DATA_DIR` setting controls all locations; `--catalog` changes only the catalog file. Do not tie job paths to a catalog location.

## Architectural boundaries

- Keep source integration generic and configured through TOML. Do not add hardcoded adapters or manually maintained function lists to solve a general discovery problem.
- Configure a Python source's `module` as its package root. Discovery traverses public package submodules generically (bounded by depth, count and time) and invocation imports a named submodule on demand; do not narrow `module` or list functions to work around incomplete discovery.
- Keep importers responsible for discovery and runtime modules responsible for execution. Python discovery imports packages and inspects their interfaces; it is not an AST-only scan and may execute import-time code.
- Scientific packages and Fire belong in managed worker environments, not the core CLI dependencies. Compatible source configurations may reuse an environment; dependency isolation is not a security sandbox.
- Use `runtime/python.py` for both foreground and background Python calls. Do not duplicate request construction in the CLI or job runner.
- Keep OS-specific process behavior in `runtime/processes.py`. Job storage and CLI routing should not contain separate Windows/POSIX process implementations.
- Keep the package worker independent of core imports: it must not require imports from the installed core CLI.
- Preserve native output for now. Do not promise uniform JSON output when a package prints diagnostics or returns other formats.

## Job behavior

- Only background execution creates managed jobs. Foreground execution waits for the result.
- Persist only the selected execution configuration, command arguments, necessary environment reference, status and output files; do not copy the entire catalog into every job.
- Use the shared atomic status writer. Record failed process startup as `failed`; mark `cancelled` only after termination is confirmed. Preserve partial results and diagnostics.
- Verify worker identity before checking or terminating a process. A matching PID alone is insufficient.
- `jobs active` reports only workers currently recognized as active. Keep its output compact: job ID, tool, short start time and elapsed runtime; no PID or `unknown` section.
- There is no automatic restart, checkpoint recovery or automatic 30-second foreground-to-background switch. An agent may stop a slow call, inform the user and restart it in the background. This starts execution again; ensure the original call has stopped and do not blindly repeat operations with side effects.
- Do not add migration support for old development job formats unless explicitly requested.

## Local package development

Use a Python source with `path` and `dev = true` for editable installation. Source edits are used on subsequent invocations; changed signatures, documentation or discovered functions require a catalog rebuild to refresh cached help. Packaging configuration changes can select a new environment. Editable inputs and their background jobs are mutable, not reproducible release snapshots.

## Development and verification

Windows, Linux and macOS are supported target platforms. Local development on macOS must not lead to macOS-only implementations or instructions. Use portable APIs where possible, encapsulate necessary platform differences in the responsible runtime module, and document shell-specific commands for Windows as well as macOS/Linux. Validate platform-dependent changes through the three-platform CI matrix and report any platforms whose execution has not yet been verified.

```bash
uv sync --locked --group build
uv run --group build python scripts/build_cli.py
./dist/netmed/netmed --help
uv run python -m unittest discover -s tests -v
```

Building may install packages and fetch API specifications. Only build trusted sources. Tests normally use temporary fixtures; do not add persistent smoke packages or source-specific manual test configuration.

The optional real-process integration test starts a temporary background worker with a child process, checks active-job detection, then cancels the job and verifies that both processes stop and output is preserved. Set `NETMED_PROCESS_TESTS=1` to enable it; otherwise it is skipped. It works across macOS, Linux and Windows, subject to the execution environment allowing process inspection and termination. This is an OS/sandbox capability requirement, not an extra user-approval step. CI enables the test on all three platforms.

On macOS/Linux shells:

```bash
NETMED_PROCESS_TESTS=1 uv run python -m unittest discover -s tests -v
```

On Windows PowerShell:

```powershell
$env:NETMED_PROCESS_TESTS = "1"
uv run python -m unittest discover -s tests -v
Remove-Item Env:NETMED_PROCESS_TESTS
```

Run checks appropriate to the change. For process changes, verify identity checks, termination and status behavior. Mocked Windows tests do not establish that the Windows backend works on a real runner; report which platforms were actually tested. Documentation-only changes need a diff check, not a full test run.

## Working rules

- Do not commit, push, publish or create releases unless the user explicitly requests it.
- Do not delete existing jobs, results or managed environments as incidental cleanup.
- Record CLI invocations before parsing/execution, including help and failed calls. History is local `logs.txt` with one `[timestamp] command` line per invocation; quote arguments and escape embedded newlines/tabs. Do not record working directories or environment variables. A logging failure should warn without blocking execution. Command history is not a replacement for release locks or data/source provenance.
- The current scope is public access without API-key/authentication support. Do not add credentials to TOML or forward arbitrary environment variables to workers. Preserve the existing environment allowlist.
- Derive source overview titles/summaries from Python distribution `Name`/`Summary` or OpenAPI `info.title`/`info.summary`; allow an optional TOML `description` to override the displayed summary, falling back to automatic metadata when omitted or blank. Do not summarize long descriptions. Cache only these small overview fields, keeping full descriptions on demand.
- Keep help useful to an agent encountering the CLI for the first time. Document commands and behavior in the README when changing them.
- `netmed docs <source>` loads external Python distribution descriptions from PyPI on demand, using the resolved or exact configured version without installing packages. Local sources with `path` use installed metadata in their managed environment. Descriptions are not cached in the catalog. Do not read local README files or fetch repository documentation as fallbacks, including in development mode; agents should see the documentation distributed by the package. Keep full descriptions opt-in rather than printing them in every help response.
- For OpenAPI sources, `docs` loads the configured specification on demand and exposes its `info`, `externalDocs` and `tags` without storing them in the catalog. Preserve provider descriptions and links; do not automatically fetch linked websites or invent missing documentation.
- Do not present planned features as implemented. Target-specific release-bundle export is implemented; reviewed multi-platform release assets, published downloadable assets, R integration and checkpoint protocols remain future work.

## API backend

Use pinned Restish for API commands. Do not reintroduce a custom OpenAPI operation parser, parameter serializer or per-provider adapter. Swagger 2 is intentionally unsupported; the pinned release supports OpenAPI 3.0/3.1. Forward native help and argument syntax rather than recreating it in netmed. The catalog contains backend references and operation counts, not duplicate schemas. Native execution spec caches are necessary for Restish; full `docs` descriptions remain on demand. Restish configuration/cache belongs below NETMED_DATA_DIR; native binaries belong in the installed CLI bundle. Background jobs reference this prepared backend instead of copying a complete specification. Build-only binary downloads must verify pinned release checksums and publish only completed executables; runtime must not download binaries. Target macOS/Linux/Windows and both amd64/arm64; report platforms actually tested. Restish transport/output behavior differs from the former custom runner and must be documented accurately.

Release preference: bundle the pinned Restish executable with each platform-specific netmed release instead of downloading it at first API use. One user-facing command may ship multiple internal executables. Native executable downloads happen only at build time. Python environments/packages remain on demand.

Remote OpenAPI preparation must explicitly run Restish `api sync`; source help alone can silently expose only generic HTTP access for an uncached remote API. Local specification files are loaded through native source help. Enable JSON body validation by default; callers may explicitly disable it with `--rsh-validate=false`. Do not automatically bypass validation failures. Native API help must explain this netmed default. Restish follows recognized same-origin next links automatically, with a default 25-page cap that warns but exits successfully; do not claim complete retrieval merely from exit code zero. No universal offset/cursor inference is implemented.

Native request-contract tests are in `tests/test_restish_integration.py`, enabled with `NETMED_RESTISH_TESTS=1`. They use a temporary local HTTP capture server and the pinned binary, never permanent smoke packages or provider-specific adapters. CI enables these tests on all three operating systems. Local test execution needs permission from the host environment to bind a loopback port, not an additional product approval workflow. Report platforms actually executed. Restish 2.3.0 form-body arrays use bracket keys (`genes[]`); query array serialization and multipart file arrays are separate, tested behaviors.

## Python object snapshots

Objects are independent artifacts under NETMED_DATA_DIR/objects, not jobs. The standalone worker resolves @object:<id> arguments using trusted local Pickle files and saves return values through Fire's serialize hook. Pickle belongs to the standard library; scientific classes stay in the managed environments. Keep the mechanism type-agnostic, preserve identity of repeated references within one invocation, and do not infer constructors/converters from ambiguous JSON. Saved snapshots are immutable: --save-updated-object writes a new ID. Publish completed object/metadata directories atomically. Never unpickle to list/inspect/clean metadata. Reject invalid IDs and symlink artifacts. No automatic version rejection, environment merging, arbitrary external pickle input, dependency installation based on object contents. Object cleanup is explicit and independent of job cleanup; it does not protect inputs of active jobs yet. Saved-object mode uses stdout for its JSON response and stderr for package progress; normal native output remains unchanged. Reserved save flags are parsed in the shared Python runtime for foreground and background calls.

Object references support explicit bracket selectors for built-in lists, tuples and dictionaries; parse literal integer/string keys without evaluating expressions. Preserve shared identity through a single loaded root per ID. New bundle metadata includes a bounded immediate structure overview without loading Pickle in the core.

## Release foundation

Worker code stays in the CLI package, outside dependency environments; execute its absolute path directly without data-directory copies. Environment identity excludes worker content and includes platform and optional lock hash. Background execution persists the packaged worker path; live development edits are not frozen. Cached discovery validates source configuration, not machine environment IDs. release.py exports relative lock references, exact Python patch versions and target hashes; do not claim exported locks are reviewed automatically. API release references materialize local Restish config on demand, without build-machine paths. Keep release export separate from binary packaging/publishing; docs/releases.md describes native bundle builds and remaining distribution validation. Old development catalogs require rebuilding; no migration is needed.

## Refactoring boundaries

The worker lives in worker/ and is shipped as ordinary source resources, independently of core imports. Keep metadata management in runtime/object_store.py and Pickle operations in worker/objects.py. Documentation belongs to documentation.py; runtime/python.py only prepares and invokes calls. Data paths belong to runtime/layout.py. Process environment construction is pure; Windows frozen DLL setup is explicit in processes.py at CLI startup.

Source selection happens before installation/discovery. Native builds snapshot self-contained API specs once for both discovery and export. Export reuses Python discovery only when configuration and observed lock match, and refreshes otherwise; a changing lock during refresh must fail without publishing. Do not add a persistent discovery cache without a demonstrated need.

Use the job lifecycle transition rules for state changes. Do not resurrect or overwrite terminal jobs, and only cancel after confirmed process termination. This is a small state machine, not a new workflow engine or an implementation of biomedical DDD. Logical responsibilities are sources, executions/environments, jobs and artifacts; retain native upstream biomedical schemas.

## Release lock and quality policy

Initial supported native targets are darwin-arm64, windows-amd64 and linux-amd64. Version target locks under release-locks/; update them explicitly using scripts/update_locks.py. Native builds automatically consume the current target locks and reject stale registry inputs. Cross-target resolution does not establish native compatibility: all three PR build checks provide review feedback; do not configure mandatory merge restrictions unless requested. Always run both uv run --group lint ruff check . and uv run --group lint ruff format --check ., plus the relevant tests. CI runs both checks on pushes and pull requests; apply formatting locally with uv run --group lint ruff format . when needed. CI checks do not enforce merge restrictions without GitHub branch rules. Keep LICENSE in shipped assets and maintain separate third-party notices.

Version-tag pushes run the build workflow and create a draft only after lint, formatting, unit tests and all three native builds succeed. Only the release job, gated on version tags or explicit manual release dispatch on main, has contents: write. Tag must match project.version. Do not push tags, create releases remotely or publish without user authorization; preparing the workflow does not authorize publishing.

Manual workflow release dispatch on main may create a matching version tag at the tested commit and a draft; the default dispatch remains build-only. Existing tags pointing to another commit must be rejected.

## User installation

installers/install.sh and installers/install.ps1 install published OS/CPU bundles into versioned user directories, verify SHA-256 and configure command lookup. Keep existing version files for active jobs, never delete managed data, and never require Python or admin privileges to install. Default installation discovers the newest public release, including pre-releases; the --version/-Version parameter explicitly pins a release. Do not select drafts. Installer tests isolate all filesystem changes and disable real PATH modification; Windows runs in native CI.


## GraphQL backend

GraphQL sources require public introspection at build time. Keep discovery in
importers/graphql.py, common schema/transport behavior in graphql/, and invocation
in runtime/graphql.py. graphql-core owns parsing, schema construction, query and
variable validation; do not write a GraphQL parser or provider-specific queries.
Read-only query documents are direct CLI arguments, with JSON variables and an
optional operation name. Preserve the data/errors/extension envelope. GraphQL errors
must fail even with HTTP 200 and partial data; foreground/background share the same
runtime. Schemas are immutable hashed files referenced by catalogs/jobs and copied
with relative paths for release bundles. No credentials, schema-file fallback,
automatic pagination, mutations or subscriptions in the current scope.


## API source refresh

`runtime/source_updates.py` owns explicit `sources update [names...] [--dry-run]`.
Only OpenAPI/GraphQL sources participate. Preserve original remote OpenAPI URLs in
spec_origin when building/exporting snapshots. Reuse importers and native Restish
validation in isolated staging; dry-run must not activate interfaces or alter live
backend caches. Publish immutable snapshots and atomically activate only successful
changes. Keep old job references valid and never retry user queries automatically.
Default CLI routing uses API-only overrides bound to matching source definitions;
explicit --catalog bypasses overrides. Keep Python versions/locks outside refresh.
