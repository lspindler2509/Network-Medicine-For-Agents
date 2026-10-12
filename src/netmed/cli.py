import argparse
import json
import sys
import requests
import subprocess
from .catalog import build
from .errors import UserError


class CatalogPath(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        parser.use_updates = False
        setattr(namespace, self.dest, values)


class CatalogHelp(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        parser.catalog_path = namespace.catalog
        parser.print_help()
        parser.exit()


class NetmedParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        from .runtime.layout import default_catalog

        super().__init__(*args, **kwargs)
        self.catalog_path = str(default_catalog())
        self.use_updates = True

    def format_help(self):
        text = super().format_help()
        text += """
Commands:
  build [sources.toml]                 Prepare sources and generate the catalog
  release-bundle <directory>           Export target-specific catalog and dependency locks
  sources                             Show the full catalog, including disabled sources
  sources update [source ...]         Refresh all APIs or only named OpenAPI/GraphQL sources
  sources update [source ...] --dry-run  Preview schema/help changes without activation
  logs [--tail N | --clear]             Show or delete command history
  docs <source>                       Show package descriptions or API spec docs
  prepare <source>                    Install/reuse a Python worker environment
  environments                        List prepared Python environments
  objects [id-or-label] [--full]       List objects or inspect metadata/path
  objects show <id-or-label> [- ...]   Load a snapshot; inspect/export using native Fire
  objects clean [id ...] [--dry-run]   Delete saved objects independently of jobs
  clean --all [--dry-run]              Delete managed data subfolders; keep other contents
  jobs [job-id]                       List jobs or inspect one job's status
  jobs active                         Check recorded background worker processes
  jobs kill <job-id>                   Stop a worker and its tools; retain files
  jobs clean [job-id ...] [--dry-run]  Delete finished/cancelled jobs, or preview
  <source> --help                      List a source's operations
  <source> <operation> --help          Show parameters and documentation
  <source> <operation> [arguments]     Execute an operation

Available sources (from the local catalog):
"""
        try:
            from .runtime.source_updates import active_catalog

            catalog = active_catalog(self.catalog_path, use_updates=self.use_updates)
            sources = catalog["sources"]
            for name, source in sorted(sources.items()):
                metadata = source.get("source_metadata", {})
                title = metadata.get("title") or source.get("package") or name
                if " ".join(title.lower().split()) == "openapi definition":
                    title = name
                summary = source.get("description", "").strip() or metadata.get(
                    "summary", ""
                )
                text += f"  {name:<16} {source['kind']}"
                text += " | " + " ".join(title.split())
                if summary:
                    text += " | " + " ".join(summary.split())
                text += "\n"
            if not sources:
                text += "  No sources configured. Run: netmed build sources.toml\n"
        except (OSError, ValueError, KeyError, TypeError):
            text += f"  Catalog unavailable: {self.catalog_path}\n  Start with: netmed build sources.toml\n"
        text += """
Usage:
  netmed <source> --help                     Find commands
  netmed <source> <operation> --help         Check arguments
  netmed --background <source> <operation>   Start a background job

Invocation and provisioning:
  Put --catalog and --background before the source/command.
  Python submodules use spaces: netmed nedrex core get_edges --help.
  Cached Python overviews hide foreign re-exports; --help --full shows all.
  Overviews above 50 visible operations use hierarchical help groups.
  Groups may follow defining modules; use the exact call paths printed inside.
  Small sources stay flat; explicit operation help remains available.
  The built CLI includes uv, Restish and API specifications.
  Python packages and their runtimes are installed on demand.

GraphQL sources:
  <source> --help          Show query fields from the cached introspection schema.
  <source> schema [Type]   Show root fields/type names or details of one type.
  <source> query '<query>' --variables '{"name": "value"}'
  Queries are direct arguments; no file is required. Only read-only queries run.
  --operation-name selects a query in a document containing multiple operations.
  Output preserves the JSON data/errors envelope; errors exit nonzero even with
  partial data. Background jobs retain that response in result.txt and fail.
  Pagination is explicit; schemas refresh on build or sources update, not per query.

Python results: automatic output and optional export:
  Automatic output follows this order:
    1. Native text via __str__(), or Fire's output for simple values/containers.
    2. Otherwise, a supported to_json() or tolist() method, validated as JSON.
    3. If no exporter is available or export fails, save a Pickle snapshot.
  Snapshot output includes saved_objects (ID, label, type), output_format and reason.
  Reuse the snapshot with @object:<id>; netmed objects <id> shows metadata/path.
  JSON exports do not preserve Python types; --save-object LABEL explicitly saves
  the original object instead. Snapshot failure exits with an error.
  The operation is never rerun by the fallback. Background output is in result.txt.
  Explicit --help and module/class/function navigation retain native help.

  To choose a particular output format, chain a native method with a standalone -:
    netmed stringdb get_interaction_partners '["EGFR"]' --limit 10 - to_csv
    netmed networkx nodes @object:lung_graph - __repr__
  Methods depend on the returned type:
    DataFrame: - to_csv or - to_json --orient=records
    Array:     - tolist
    Text:      - __repr__ (may be only a preview)
  There is no universal CSV/JSON conversion.
  Streaming iterators retain native output; saving a live iterator is unsupported.

Python snapshots: save and reuse:
  --save-object LABEL             Save the final return value explicitly.
  @object:<id> / @object:<label>  Load a saved snapshot in the worker.
  Duplicate labels require an immutable ID; no snapshot is chosen silently.
  Quote labels with spaces and bracket selectors, for example:
    '@object:lung_graph[0]' or '@object:<id>["key"]'
  Argument selectors use brackets: '@object:<id>["z_score"]'.
  Fire navigation uses tokens: netmed objects show <id> z_score - to_csv.
  Bracket selectors are for @object arguments, not objects show command paths.
  Selectors support built-in lists, tuples and dictionaries.
  netmed objects <id-or-label> shows metadata/path and an argument preview.
  Add --full to show complete arguments.
  netmed objects show <id-or-label> displays contents in the original environment.
  If text/JSON is unavailable, it shows metadata and a method-exploration hint.
  Explore with: netmed objects show <id-or-label> --help
  Export with:  netmed objects show <id-or-label> - to_csv --index=False
  --save-updated-object <id-or-label> saves a modified input under a new ID.

Passing objects between Python environments:
  Pickle snapshots preserve types, but do not carry their dependencies.
  A pandas DataFrame requires pandas in the receiving environment.
  Either declare compatible dependencies for the receiver, or explicitly export
  portable lists/dicts or files in the original source before switching sources:
    netmed pandas DataFrame '--data={"gene": ["EGFR"]}' - to_dict --orient=records --save-object genes
  Check source help for native loaders, converters and exporters.
  No automatic conversion, dependency installation from snapshots or environment
  merging occurs.

Python callbacks:
  Quote '@lambda:lambda x: ...'; this executes trusted Python code.
  Results retaining lambdas may not be picklable; copy/materialize explicitly.

Updating API sources:
  netmed sources update                      Refresh all active OpenAPI/GraphQL sources.
  netmed sources update opentargets dgidb    Refresh only these sources.
  Add --dry-run to fetch/validate and preview changes without activation.
  Python packages and locks are excluded; explicit Python selections are rejected.
  Successful changes update help and execution; failed sources keep their previous interface.
  Output reports schema changes, GraphQL query counts and per-source failures.
  Without --catalog, local API overrides are used automatically for help, calls
  and new jobs. Overrides apply only to matching source definitions.
  Explicit --catalog takes precedence; update writes that writable catalog instead.
  Existing jobs retain old snapshot/backend references; no queries are rerun.
  NETMED_DATA_DIR/api-updates holds overrides/snapshots. clean --all removes them.
  No new CLI build is needed. Registry additions and Python upgrades remain builds.

Storage and cleanup:
  NETMED_DATA_DIR controls jobs, objects, environments, runtimes and logs.txt.
  netmed clean --all --dry-run previews deletion of managed subfolders.
  netmed clean --all deletes them, including results; keeps the data root and
  other contents. Active calls/jobs/provisioning prevent cleanup.

Development:
  Rebuild with scripts/build_cli.py after CLI code changes.
"""
        return text


def management_arguments(command, arguments):
    parser = argparse.ArgumentParser(prog="netmed " + command)
    if command == "build":
        parser.add_argument(
            "config", nargs="?", default="sources.toml", help="Source registry TOML"
        )
        parser.add_argument(
            "--source",
            action="append",
            help="Discover only this source; repeat for more",
        )
    elif command in ("prepare", "docs"):
        parser.add_argument(
            "source", help="Source name" if command == "docs" else "Python source name"
        )
    return parser.parse_args(arguments)


def source_from(catalog, name, *, use_updates=False):
    from .runtime.source_updates import active_catalog

    catalog = active_catalog(catalog, use_updates=use_updates)
    sources = catalog["sources"]
    if name in catalog.get("disabled_sources", {}):
        reason = catalog["disabled_sources"][name].get(
            "disabled_reason", "disabled in registry"
        )
        raise UserError(f"Source {name} is disabled: {reason}")
    if name not in sources:
        raise UserError(
            f"Unknown source: {name}. Run netmed sources to list available sources"
        )
    return sources[name]


def jobs_command(arguments):
    from .runtime import jobs

    root = jobs.directory_for()
    parser = argparse.ArgumentParser(
        prog="netmed jobs",
        description="List or inspect jobs; use active, kill or clean to manage them.",
    )
    parser.add_argument("command", nargs="?", help="Job ID, active, kill or clean")
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(arguments)
    if args.command == "active":
        subparser = argparse.ArgumentParser(
            prog="netmed jobs active",
            description="Show verified active workers with their start time and elapsed runtime. Does not change saved job states.",
        )
        subparser.parse_args(args.arguments)
        return jobs.active(root)
    if args.command == "kill":
        subparser = argparse.ArgumentParser(
            prog="netmed jobs kill",
            description="Stop a local worker and its tools. Keep partial results and mark the job cancelled after termination is confirmed. Automatically selects macOS/Linux or Windows process management.",
        )
        subparser.add_argument("job", help="Job ID to stop")
        return jobs.kill(root, subparser.parse_args(args.arguments).job)
    if args.command == "clean":
        subparser = argparse.ArgumentParser(
            prog="netmed jobs clean",
            description="Delete results, logs and execution settings of finished/cancelled jobs. Active or unknown jobs are kept; Python environments are kept.",
        )
        subparser.add_argument(
            "jobs",
            nargs="*",
            help="One or more job IDs; omit to clean all terminal jobs",
        )
        subparser.add_argument(
            "--dry-run", action="store_true", help="Preview without deleting files"
        )
        selected = subparser.parse_args(args.arguments)
        return jobs.clean(root, selected.jobs, selected.dry_run)
    if args.arguments:
        parser.error("unexpected arguments")
    return (
        jobs.inspect_job(root, args.command) if args.command else jobs.list_jobs(root)
    )


def main():
    from .runtime.processes import prepare_external_process

    prepare_external_process()
    from .runtime.command_log import record_command

    try:
        record_command(sys.argv[1:])
    except OSError:
        print(
            "Warning: could not write the command log; execution continues.",
            file=sys.stderr,
        )
    parser = NetmedParser(
        prog="netmed",
        add_help=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Discover and run network medicine Python packages, OpenAPI and GraphQL services.\nRead source/operation help first, then execute using the documented arguments.",
    )
    parser.add_argument(
        "-h",
        "--help",
        action=CatalogHelp,
        nargs=0,
        help="Show commands, available sources and usage examples",
    )
    parser.add_argument(
        "--catalog",
        action=CatalogPath,
        default=parser.catalog_path,
        help="Catalog override (default: bundled catalog; data-directory catalog in source mode)",
    )
    parser.add_argument(
        "--background",
        action="store_true",
        help="Run a detached local job and return its ID after preparation. Agents may stop a slow foreground call and restart with this flag, informing the user. Restart begins from scratch; no automatic timeout/switch.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="help",
        help="Management command or source name listed below",
    )
    parser.add_argument(
        "arguments",
        nargs=argparse.REMAINDER,
        help="Operation path and its arguments; use <source> --help to explore",
    )
    args = parser.parse_args()
    parser.catalog_path = args.catalog
    try:
        import contextlib
        from .runtime.cleanup import activity

        with activity() if args.command != "clean" else contextlib.nullcontext():
            if args.command == "_job-worker":
                sub = argparse.ArgumentParser(prog="netmed _job-worker")
                sub.add_argument("directory")
                from .runtime.jobs import worker

                worker(sub.parse_args(args.arguments).directory)
            elif args.command == "build":
                selected = management_arguments("build", args.arguments)
                result = build(selected.config, args.catalog, selected.source)
                print(
                    json.dumps(
                        {"catalog": args.catalog, "sources": list(result["sources"])}
                    )
                )
            elif args.command in ("prepare", "environments"):
                selected = management_arguments(args.command, args.arguments)
                from .runtime.environments import UvEnvironmentManager

                manager = UvEnvironmentManager()
                if args.command == "environments":
                    print(json.dumps(manager.list(), indent=2))
                else:
                    source = source_from(
                        args.catalog, selected.source, use_updates=parser.use_updates
                    )
                    if source["kind"] != "python":
                        raise UserError("Only Python sources need preparation")
                    print(json.dumps(manager.ensure(source)))
            elif args.command == "sources":
                from .runtime.source_updates import active_catalog, update

                sub = argparse.ArgumentParser(
                    prog="netmed sources",
                    description="Show the catalog or refresh API schemas and help without rebuilding the CLI.",
                )
                commands = sub.add_subparsers(dest="operation")
                refresh = commands.add_parser(
                    "update",
                    help="Refresh all active APIs, or only named sources; Python is excluded",
                )
                refresh.add_argument(
                    "sources",
                    nargs="*",
                    help="OpenAPI/GraphQL source names; omit for all active APIs",
                )
                refresh.add_argument(
                    "--dry-run",
                    action="store_true",
                    help="Fetch and validate schemas; report changes without activating them",
                )
                selected = sub.parse_args(args.arguments)
                if selected.operation == "update":
                    result = update(
                        args.catalog,
                        selected.sources,
                        dry_run=selected.dry_run,
                        use_updates=parser.use_updates,
                    )
                    print(json.dumps(result, indent=2))
                    return (
                        1
                        if any(item["status"] == "failed" for item in result["sources"])
                        else 0
                    )
                print(
                    json.dumps(
                        active_catalog(args.catalog, use_updates=parser.use_updates),
                        indent=2,
                    )
                )
            elif args.command == "release-bundle":
                from .release import export

                sub = argparse.ArgumentParser(
                    prog="netmed release-bundle",
                    description="Export a relocatable catalog and hashed dependency locks for this OS/architecture. May install packages. Does not build a binary or publish anything.",
                )
                sub.add_argument("directory", help="New output directory")
                sub.add_argument(
                    "--source",
                    action="append",
                    help="Select a source; repeat to select more (default: all)",
                )
                selected = sub.parse_args(args.arguments)
                print(
                    json.dumps(
                        export(
                            args.catalog,
                            selected.directory,
                            selected.source,
                            use_updates=parser.use_updates,
                        ),
                        indent=2,
                    )
                )
            elif args.command == "logs":
                from .runtime.command_log import read_commands, clear_commands

                sub = argparse.ArgumentParser(
                    prog="netmed logs",
                    description="Show timestamped command history from logs.txt in the netmed data directory. Includes this invocation; no results or environment variables are recorded.",
                )
                options = sub.add_mutually_exclusive_group()
                options.add_argument(
                    "--tail",
                    type=int,
                    help="Show only the last N lines (N must be positive)",
                )
                options.add_argument(
                    "--clear",
                    action="store_true",
                    help="Delete the complete logs.txt file, including this invocation",
                )
                selected = sub.parse_args(args.arguments)
                if selected.tail is not None and selected.tail <= 0:
                    sub.error("--tail must be positive")
                if selected.clear:
                    clear_commands()
                    print("Command history deleted.")
                else:
                    sys.stdout.write(read_commands(selected.tail))
            elif args.command == "docs":
                selected = management_arguments("docs", args.arguments)
                source = source_from(
                    args.catalog, selected.source, use_updates=parser.use_updates
                )
                if source["kind"] in ("openapi", "graphql"):
                    from .documentation import documentation

                    print(
                        json.dumps(documentation(source), indent=2, ensure_ascii=False)
                    )
                    if source["kind"] == "graphql":
                        print(f"Schema help: netmed {selected.source} schema <Type>")
                        print(f"Query help: netmed {selected.source} query --help")
                    else:
                        print(
                            f"Operation help: netmed {selected.source} <operation> --help"
                        )
                else:
                    from .documentation import documentation

                    documents = documentation(source)
                    if not documents:
                        print("No package description found in distribution metadata.")
                    for document in documents:
                        print(
                            f"{document['name']} {document['version']} — {document.get('origin', 'installed package metadata')}\n"
                        )
                        print(document["text"])
            elif args.command == "clean":
                from .runtime.cleanup import clean_all

                sub = argparse.ArgumentParser(prog="netmed clean")
                sub.add_argument("--all", action="store_true", required=True)
                sub.add_argument("--dry-run", action="store_true")
                selected = sub.parse_args(args.arguments)
                print(json.dumps(clean_all(dry_run=selected.dry_run), indent=2))
            elif args.command == "objects":
                from .runtime import object_store as objects

                if args.arguments[:1] == ["show"]:
                    if len(args.arguments) < 2:
                        raise UserError(
                            "Usage: netmed objects show <id-or-label> [- <method> [arguments]]"
                        )
                    return objects.show(args.arguments[1], args.arguments[2:])

                sub = argparse.ArgumentParser(
                    prog="netmed objects",
                    description="List or inspect local Python object snapshots without loading them. Clean deletes objects independently of jobs.",
                )
                sub.add_argument(
                    "operation",
                    nargs="?",
                    help="Object ID to inspect, or clean; omit to list",
                )
                sub.add_argument(
                    "ids",
                    nargs="*",
                    help="IDs for clean; omit to clean all saved objects",
                )
                sub.add_argument(
                    "--dry-run",
                    action="store_true",
                    help="Preview object deletion without removing files",
                )
                sub.add_argument(
                    "--full",
                    action="store_true",
                    help="Show complete original arguments",
                )
                selected = sub.parse_args(args.arguments)
                if selected.full and (
                    not selected.operation or selected.operation == "clean"
                ):
                    sub.error("--full requires an object ID or label")
                if selected.operation == "clean":
                    result = objects.clean(selected.ids, selected.dry_run)
                elif selected.ids or selected.dry_run:
                    sub.error("IDs/--dry-run require clean")
                else:
                    result = (
                        objects.display_metadata(selected.operation, full=selected.full)
                        if selected.operation
                        else objects.list_objects()
                    )
                print(json.dumps(result, indent=2))
            elif args.command == "jobs":
                print(json.dumps(jobs_command(args.arguments), indent=2))
            elif args.command == "help":
                management_arguments("help", args.arguments)
                parser.print_help()

            else:
                command = args.command
                arguments = args.arguments
                source = source_from(
                    args.catalog, command, use_updates=parser.use_updates
                )
                help_call = not arguments or any(
                    a in ("--help", "-h") for a in arguments
                )
                if source["kind"] == "graphql" and arguments[:1] == ["schema"]:
                    help_call = True
                if not help_call and (
                    args.background or source.get("execution") == "background"
                ):
                    from .runtime.jobs import launch, directory_for

                    print(
                        json.dumps(
                            launch(
                                args.catalog,
                                [command, *arguments],
                                directory_for(),
                                use_updates=parser.use_updates,
                            )
                        )
                    )
                elif source["kind"] == "python":
                    from .importers.python import cached_help
                    from .runtime.python import invoke

                    if cached_help(source, arguments, f"netmed {command}"):
                        return 0
                    return invoke(source, arguments, name=f"netmed {command}")
                elif source["kind"] == "graphql":
                    from .runtime.graphql import invoke

                    return invoke(source, arguments, name=f"netmed {command}")
                else:
                    from .runtime.restish import invoke

                    return invoke(source, arguments, name=f"netmed {command}")
    except UserError as error:
        print(f"Command failed: {error}", file=sys.stderr)
        return 1
    except FileNotFoundError as error:
        print(f"File or executable not found: {error.filename}", file=sys.stderr)
        return 1
    except requests.RequestException:
        print(
            "API request failed; check connectivity and the configured endpoint.",
            file=sys.stderr,
        )
        return 1
    except subprocess.TimeoutExpired:
        print(
            "Command timed out; check the operation and configured timeout.",
            file=sys.stderr,
        )
        return 1
    except (
        ValueError,
        KeyError,
        OSError,
        ImportError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as error:
        # Raw external exception messages may contain URLs or credentials.
        print(
            f"Command failed ({type(error).__name__}). Check source configuration, arguments and installed packages.",
            file=sys.stderr,
        )
        return 1
    return 0
