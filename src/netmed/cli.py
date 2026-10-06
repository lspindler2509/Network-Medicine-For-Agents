import argparse
import json
import sys
import requests
from pathlib import Path
from .catalog import build, load


def main():
    parser = argparse.ArgumentParser(description='Generate CLI access from source-native interfaces.')
    parser.add_argument('--catalog', default='.netmed/catalog.json')
    parser.add_argument('--background', action='store_true', help='Run a source command as a persistent local job')
    parser.add_argument('command', nargs='?', default='help')
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        if args.command == 'build':
            config = args.arguments[0] if args.arguments else 'sources.toml'
            result = build(config, args.catalog)
            print(json.dumps({'catalog': args.catalog, 'sources': list(result['sources'])}))
        elif args.command == 'sources':
            print(json.dumps(load(args.catalog)['sources'], indent=2))
        elif args.command == 'jobs':
            root = Path(args.catalog).resolve().parent / 'jobs'
            if args.arguments:
                job = args.arguments[0]
                if len(job) != 32 or any(c not in '0123456789abcdef' for c in job):
                    raise ValueError('Invalid job ID')
                print((root / job / 'status.json').read_text())
            else:
                print(json.dumps([json.loads(p.read_text()) for p in root.glob('*/status.json')], indent=2))
        elif args.command == 'help':
            parser.print_help()
            print('\nCommands: build [sources.toml], sources, jobs [id], <source> [operation] [arguments]')
        else:
            force = args.command == '_run'
            command = args.arguments[0] if force else args.command
            arguments = args.arguments[1:] if force else args.arguments
            source = load(args.catalog)['sources'][command]
            help_call = any(a in ('--help', '-h') for a in arguments)
            if not force and not help_call and (args.background or source.get('execution') == 'background'):
                from .runtime.jobs import launch
                print(json.dumps(launch(args.catalog, [command, *arguments], Path(args.catalog).resolve().parent / 'jobs')))
            elif source['kind'] == 'python':
                from .importers.python import invoke
                invoke(source, arguments, name=f'netmed {command}')
            elif not arguments or arguments == ['--help']:
                print(json.dumps({k: v['summary'] for k, v in source['operations'].items()}, indent=2))
            else:
                from .runtime.http import invoke
                print(json.dumps(invoke(source, arguments[0], arguments[1:], name=f'netmed {command}'), indent=2))
    except (ValueError, KeyError, OSError, ImportError, requests.RequestException) as error:
        # Do not echo upstream exceptions, request URLs or credentials.
        print(f'Command failed ({type(error).__name__}). Check source configuration, arguments and installed packages.', file=sys.stderr)
        return 1
    return 0
