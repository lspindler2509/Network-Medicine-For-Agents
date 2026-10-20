# File-by-file architecture

The registry describes sources. Discovery produces routing/help metadata, not generated scientific implementations. Python execution imports the package in a uv-managed worker and uses Fire. API execution delegates command generation, help and HTTP to Restish. The agent supplies orchestration; there is no embedded LLM or service to host.

## Configuration and entry points

| File | Responsibility |
| --- | --- |
| `sources.toml` | Default source registry: package/module/version/Python or API spec/base URL, optional descriptions and disabled candidates. No function list. |
| `pyproject.toml` | Core dependencies, Hatchling wheel packaging, `netmed` entry point and pinned PyInstaller build group. Fire/scientific packages are worker dependencies. |
| `uv.lock` | Repository dependency resolution for development/core/build tooling. Separate from exported scientific source locks. |
| `.gitignore` | Excludes environments, generated data, build caches and distribution artifacts. |
| `AGENTS.md` | Project purpose, architectural boundaries and instructions for contributors/agents. Not runtime tool documentation. |
| `src/netmed/__init__.py` | Package marker. |
| `src/netmed/__main__.py` | Source-installed `python -m netmed` entry point; calls CLI main. |
| `installers/install.sh` | Published bundle installation and shell PATH setup for macOS arm64/Linux x64. |
| `installers/install.ps1` | Published bundle installation and user PATH setup for Windows x64. |
| `scripts/cli_entry.py` | PyInstaller entry point; calls the same CLI main and propagates its exit code. |

## Core and importers

| File | Responsibility |
| --- | --- |
| `src/netmed/cli.py` | Argument parsing, source routing, management commands, help and user-facing errors. Internal `_job-worker` mode supports detached execution in source and frozen installations. |
| `src/netmed/catalog.py` | Validates TOML, selects importers, constructs/loads JSON catalogs and computes Python configuration fingerprints. Resolves local paths against registry/catalog locations. |
| `src/netmed/documentation.py` | On-demand package/API documentation dispatch, PyPI metadata and local worker metadata requests. |
| `src/netmed/errors.py` | Defines the local `UserError` type for errors safe to show directly. |
| `src/netmed/importers/__init__.py` | Package marker. |
| `src/netmed/importers/python.py` | Provisions the discovery environment, invokes worker introspection and renders cached help. No scientific package imports in the core. |
| `src/netmed/importers/openapi.py` | Reads JSON/YAML specifications, validates the supported OpenAPI version, extracts overview/docs and delegates operation discovery to Restish. No custom request serializer. |

## Runtime

| File | Responsibility |
| --- | --- |
| `src/netmed/runtime/__init__.py` | Package marker. |
| `src/netmed/runtime/layout.py` | Central data-directory selection and installed read-only assets, bundled uv and the default catalog. Frozen CLI defaults to its bundled catalog; source mode uses the data-directory catalog. |
| `src/netmed/runtime/environments.py` | Install locks, platform/dependency identities, uv provisioning and local editable installs. Supplies interpreter and packaged worker paths. |
| `src/netmed/runtime/python.py` | Shared foreground/background Python preparation and request construction. Checks catalog configuration and routes object/save options. |
| `src/netmed/runtime/restish_binary.py` | Locates bundled Restish or verifies an explicit source-development override; holds pinned release version/checksums. No executable downloads at runtime. |
| `src/netmed/runtime/restish.py` | Materializes native API configuration/cache, invokes Restish, forwards arguments/output and applies the JSON validation default. Used by foreground calls and API jobs. |
| `src/netmed/runtime/processes.py` | Source/frozen worker commands, restricted child environments, explicit external-tool setup, detached startup, worker identity checks and process-tree/group termination. Encapsulates Windows/POSIX differences and waits for confirmed termination. |
| `src/netmed/runtime/jobs.py` | Job directories, atomic status persistence, launch/execution coordination, listing/inspection, active workers, cancellation and cleanup. Uses shared runtimes rather than duplicating source execution. |
| `src/netmed/runtime/object_store.py` | Reserved save flags and local object metadata listing/inspection/cleanup. Never unpickles in the core. |
| `src/netmed/runtime/job_state.py` | Pure job lifecycle rules and terminal states; validates transitions without I/O or process knowledge. |
| `src/netmed/runtime/command_log.py` | Records timestamped command text, reads history with optional tail and clears the history file. |

Windows detachment uses native creation flags; termination uses `taskkill` for the verified worker tree. POSIX uses detached sessions and process-group termination. Both check command-line identity as well as PID. Runtime dependency isolation is not a security sandbox. OS-specific behavior belongs in `processes.py`, with explicit external-child DLL setup before CLI execution; `process_environment()` only constructs the environment for the frozen Windows application.

## Independent worker package

| File | Responsibility |
| --- | --- |
| `src/netmed/worker/__init__.py` | Independent package marker; no core imports. |
| `src/netmed/worker/entry.py` | Direct-script entry point and JSON request dispatch for discover/docs/invoke. |
| `src/netmed/worker/discovery.py` | Static public-interface introspection and bounded traversal of package submodules. |
| `src/netmed/worker/metadata.py` | Installed distribution summaries and descriptions; no checkout README fallback. |
| `src/netmed/worker/invocation.py` | Package/submodule imports (eager or on demand for the requested call path), declarative setup and Fire invocation. |
| `src/netmed/worker/objects.py` | Trusted Pickle loading/saving, selectors, atomic artifact publication and saved-output handling. |
| `src/netmed/worker/results.py` | Type-agnostic Fire serialization fallback: native output, supported JSON exporters, then snapshot. |
| `src/netmed/worker/references.py` | Shared pure ID/label resolution; no core dependency or unpickling. |
| `src/netmed/worker/callbacks.py` | Explicit trusted lambda parsing. |

The complete worker source package is shipped as application resources, excluded from the frozen core module collection, and run using the scientific environment's interpreter. It requires neither the core nor copied worker definitions in NETMED_DATA_DIR.

## Build and release export

| File | Responsibility |
| --- | --- |
| `src/netmed/building/__init__.py` | Marks build-only helpers; this package is excluded from the frozen application. |
| `src/netmed/building/locks.py` | Checks target-specific lock manifests against source dependency inputs and file hashes. |
| `src/netmed/building/restish.py` | Downloads/checksum-verifies Restish and extracts only the executable into a chosen build location. |
| `src/netmed/release.py` | Exports a target-specific portable catalog, exact Python versions and hashed scientific dependency locks. Bundles self-contained API snapshots and writes provenance metadata. Rejects local Python sources and external API refs. Does not compile or publish. |
| `scripts/build_cli.py` | Orchestrates discovery, export, native executable inclusion, PyInstaller directory build and platform archive/checksum creation. Requires the pinned uv version. |
| `scripts/update_locks.py` | Explicit scientific lock updates for one target or all three; no native platform testing. |
| `release-locks/<target>/` | Versioned scientific dependency locks and manifest per supported OS/CPU target. |
| `.github/workflows/test.yml` | Ruff plus source/unit/native integration tests on Linux, macOS and Windows for pushes/PRs. |
| `.github/workflows/build.yml` | Native CLI build and executable contract test on each CI OS; uploads archives/checksums on PRs, main pushes and manual runs. Version-tag pushes create a release draft after successful checks; publication remains manual. |

Build flow: `sources.toml` → discovery catalog → portable resources/locks/specs → PyInstaller bundle → archive. Python analysis packages stay outside the application bundle and are installed by bundled uv when used. Fire belongs in those environments. API operations need Restish but no scientific Python environment.

Application code/resources stay in the installed bundle; mutable state uses NETMED_DATA_DIR. `.build/` and `dist/` are checkout-local generated build outputs. `<data>/restish/` is small API configuration/cache; it is not an executable installation. There are no runtime worker copies or executable-download directories.

## Tests and documentation

| File | Coverage/purpose |
| --- | --- |
| `tests/test_core.py` | Registry/OpenAPI import boundaries and generic docs behavior. |
| `tests/test_discovery.py` | Worker introspection, callable instances, metadata, submodules and setup. |
| `tests/test_environments.py` | Environment identities, install failure/reuse, editable inputs and child environment. |
| `tests/test_python_runtime.py` | Shared Python invocation and catalog compatibility. |
| `tests/test_documentation.py` | PyPI/local metadata documentation without accidental installation or checkout fallback. |
| `tests/test_help.py` | CLI parsing, cached/source help and on-demand descriptions. |
| `tests/test_command_log.py` | Text history, tail, clearing and failure behavior. |
| `tests/test_jobs.py` | Job persistence, launch, status, active reporting and cleanup. |
| `tests/test_job_state.py` | Invalid transitions, immutable terminal states and cancelled-worker startup prevention. |
| `tests/test_processes.py` | Worker identity, platform handling and opt-in real process-tree cancellation. |
| `tests/test_objects.py` | Generic Pickle flow, metadata/selectors, mutation, callbacks and failure cleanup. |
| `tests/test_restish.py` | Backend configuration/invocation and verified build-time native extraction. |
| `tests/test_restish_integration.py` | Opt-in real HTTP capture tests for multipart/forms/arrays/refs/validation/pagination. |
| `tests/test_installers.py` | Temporary bundle installation and checksum failure without changing real user PATH/data. |
| `tests/test_build_locks.py` | Registry input, target and checksum consistency for versioned build locks. |
| `tests/test_release.py` | Relocatable release resources, target/lock checks and release input restrictions. |
| `tests/test_built_cli.py` | Opt-in frozen executable provisioning, objects, API help and detached completion/active/cancellation with developer tools absent from PATH. |
| `README.md` | Current build/run/development instructions and generic limitations. |
| `docs/architecture.md` | This file-by-file map and architecture assessment. |
| `docs/releases.md` | Build/export internals and remaining public distribution decisions. |
| `docs/sources.md` | Generic integration rules and maintained native-source limitations. |
| `docs/nice-to-have-sources.md` | Deferred biomedical candidates and future upstream work. |

## Architectural constraints

- Native bundles are specific to OS/CPU. Supported initial targets are macOS arm64, Linux x64 and Windows x64; CI runs native build checks for each.
- Ordinary builds consume versioned scientific locks. Explicit updates may change transitive dependencies; cross-target resolution must be followed by native CI validation.
- Discovery can execute import-time package code and remain incomplete for dynamic interfaces. The independent worker protocol must stay compatible with both source and frozen execution.
- Restish defines API serialization, pagination and native argument behavior. JSON-validation default detection depends on its pinned help format. The configured API base URL is a default, not an enforced origin boundary.
- Rebuilding replaces the bundle used by running jobs. Stop those jobs first. Object cleanup does not track active job inputs, and automatic job recovery is intentionally absent.


## GraphQL boundary

GraphQL is a separate source kind. `importers/graphql.py` obtains a standard
introspection response, lets graphql-core validate/build the schema, and writes
an immutable content-addressed snapshot. `graphql/schema.py` verifies the snapshot
checksum and formats provider-native type metadata for help; `graphql/transport.py`
implements the standard JSON POST envelope. `runtime/graphql.py` owns direct-query
argument parsing, read-only validation and execution, shared by foreground calls
and jobs. Neither Fire nor Restish interprets GraphQL documents.

The catalog holds endpoint, snapshot reference and small overview metadata.
Release export copies snapshots with relative paths; jobs retain references rather
than copying schemas. A build requires public introspection, and normal query execution does not
fetch or silently refresh a schema. An explicit `sources update` can refresh it. Unknown fields therefore require a schema refresh or rebuild
when the provider changes its schema. There are no source-specific queries,
parameter mappings, biomedical response transforms or automatic cursor traversal.


## Explicit API refresh

`runtime/source_updates.py` coordinates OpenAPI/GraphQL refresh through the existing
importers. OpenAPI retains its remote `spec_origin` even in release snapshots;
Restish validates the fetched local snapshot in a temporary backend directory.
GraphQL discovers its schema in staging. Dry-run discards all staging artifacts.
Only successful changed interfaces are published as immutable snapshots, followed
by an atomic overlay/catalog write. Source failures do not block successful peers.

Default routing merges the bundled/data catalog with a small API-only overlay,
bound to each source definition's endpoint/base URL/origin. Explicit catalog selection
bypasses it. Python configuration is never copied into the overlay. Foreground help,
docs and execution, new jobs, and explicit release export use the active interface;
existing jobs retain persisted references. API update locks serialize publishers.
Managed `api-updates` files are included in explicit `clean --all` cleanup.
