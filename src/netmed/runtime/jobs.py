"""Detached execution of the same CLI; no source-specific polling logic."""
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

_workers = []


def launch(catalog, arguments, directory):
    job = uuid.uuid4().hex
    root = Path(directory).resolve() / job
    root.mkdir(parents=True, mode=0o700)
    status = {'id': job, 'state': 'queued', 'arguments': arguments}
    (root / 'status.json').write_text(json.dumps(status))
    with (root / 'worker.log').open('w') as log:
        process = subprocess.Popen([sys.executable, '-m', 'netmed.runtime.jobs', str(root), str(Path(catalog).resolve()), json.dumps(arguments)],
                                   stdout=log, stderr=log, start_new_session=True)
    status['pid'] = process.pid
    _workers[:] = [worker for worker in _workers if worker.poll() is None]
    _workers.append(process)
    return {'id': job, 'directory': str(root), 'pid': process.pid}


def worker(root, catalog, arguments):
    root = Path(root)
    def state(name, **extra):
        target = root / 'status.json'
        temp = root / 'status.tmp'
        temp.write_text(json.dumps({'id': root.name, 'state': name, **extra}))
        temp.replace(target)
    state('running', pid=os.getpid())
    try:
        with (root / 'result.txt').open('w') as output, (root / 'stderr.txt').open('w') as errors:
            code = subprocess.call([sys.executable, '-m', 'netmed', '--catalog', catalog, '_run', *arguments], stdout=output, stderr=errors)
        state('completed' if code == 0 else 'failed', exit_code=code)
    except Exception:
        state('failed', error='Worker could not execute command')


if __name__ == '__main__':
    worker(sys.argv[1], sys.argv[2], json.loads(sys.argv[3]))
