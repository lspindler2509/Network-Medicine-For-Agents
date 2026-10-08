import argparse
import json
import sys
import requests
import subprocess
from .catalog import build, load
from .errors import UserError


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

    def format_help(self):
        text = super().format_help()
        text += """
Commands:
  build [sources.toml]                 Prepare sources and generate the catalog
  release-bundle <directory>           Export target-specific catalog and dependency locks
  sources                             Show the full source catalog (verbose JSON)
  logs [--tail N | --clear]             Show or delete command history
  docs <source>                       Show package descriptions or API spec docs
  prepare <source>                    Install/reuse a Python worker environment
  environments                        List prepared Python environments
  objects [object-id]                  List objects or inspect metadata/path
  objects clean [id ...] [--dry-run]   Delete saved objects independently of jobs
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
            catalog = load(self.catalog_path)
            sources = catalog["sources"]
            for name, source in sorted(sources.items()):
                metadata = source.get("source_metadata", {})
                title = metadata.get("title") or source.get("package") or name
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
            if catalog.get("disabled_sources"):
                text += "\nDisabled sources (not executable):\n"
                for name, source in catalog["disabled_sources"].items():
                    text += f"  {name}: {source.get('disabled_reason', 'disabled in registry')}\n"
        except (OSError, ValueError, KeyError, TypeError):
            text += f"  Catalog unavailable: {self.catalog_path}\n  Start with: netmed build sources.toml\n"
        text += """
Usage:
  netmed <source> --help                     Find commands
  netmed <source> <operation> --help         Check arguments
  netmed --background <source> <operation>   Start a background job

Put --catalog and --background before the source/command.
Python submodules use spaces: netmed nedrex core get_edges --help.
The built CLI includes uv, Restish and API specifications.
Python packages and their runtimes are installed on demand.
Python: --save-object LABEL saves a return value for reuse; @object:<id> loads it.
Use normal output for streaming iterators; saving a live iterator is unsupported.
For complex objects, check source help for native loaders, converters and exporters
(e.g. NetworkX graph readers/converters). Required types may come with the package;
other packages must be configured explicitly, and worker dependencies must match.
Object selection: quote @object:<id>[0] or @object:<id>["key"] for bundle items.
netmed objects <id> shows structure metadata for newly saved bundles.
--save-updated-object <id> saves a modified input as a new object.
Python callbacks: quote @lambda:lambda x: ... (executes trusted Python code).
Results retaining lambdas may not be picklable; explicitly copy/materialize if needed.
Jobs, objects and logs.txt are stored in the netmed data directory (NETMED_DATA_DIR).
Development: rebuild with scripts/build_cli.py after CLI code changes.
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


def source_from(catalog, name):
    catalog = load(catalog)
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


def jobs_command(catalog, arguments):
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
        description="Discover and run network medicine Python packages and OpenAPI services.\nRead source/operation help first, then execute using the documented arguments.",
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
                source = source_from(args.catalog, selected.source)
                if source["kind"] != "python":
                    raise UserError("Only Python sources need preparation")
                print(json.dumps(manager.ensure(source)))
        elif args.command == "sources":
            management_arguments("sources", args.arguments)
            print(json.dumps(load(args.catalog)["sources"], indent=2))
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
                    export(args.catalog, selected.directory, selected.source), indent=2
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
            source = source_from(args.catalog, selected.source)
            if source["kind"] == "openapi":
                from .documentation import documentation

                print(json.dumps(documentation(source), indent=2, ensure_ascii=False))
                print(f"Operation help: netmed {selected.source} <operation> --help")
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
        elif args.command == "objects":
            from .runtime import object_store as objects

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
                "ids", nargs="*", help="IDs for clean; omit to clean all saved objects"
            )
            sub.add_argument(
                "--dry-run",
                action="store_true",
                help="Preview object deletion without removing files",
            )
            selected = sub.parse_args(args.arguments)
            if selected.operation == "clean":
                result = objects.clean(selected.ids, selected.dry_run)
            elif selected.ids or selected.dry_run:
                sub.error("IDs/--dry-run require clean")
            else:
                result = (
                    objects.inspect_object(selected.operation)
                    if selected.operation
                    else objects.list_objects()
                )
            print(json.dumps(result, indent=2))
        elif args.command == "jobs":
            print(json.dumps(jobs_command(args.catalog, args.arguments), indent=2))
        elif args.command == "help":
            management_arguments("help", args.arguments)
            parser.print_help()

        else:
            command = args.command
            arguments = args.arguments
            source = source_from(args.catalog, command)
            help_call = not arguments or any(a in ("--help", "-h") for a in arguments)
            if not help_call and (
                args.background or source.get("execution") == "background"
            ):
                from .runtime.jobs import launch, directory_for

                print(
                    json.dumps(
                        launch(args.catalog, [command, *arguments], directory_for())
                    )
                )
            elif source["kind"] == "python":
                from .importers.python import cached_help
                from .runtime.python import invoke

                if cached_help(source, arguments, f"netmed {command}"):
                    return 0
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
