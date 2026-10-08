"""Detached execution of the same CLI; no source-specific polling logic."""

import json
import os
import re
import shutil
import shlex
import subprocess
import uuid
from pathlib import Path
from datetime import datetime, timezone
from ..catalog import load
from .processes import start_worker, worker_is_active, stop_worker
from .layout import data_directory
from ..errors import UserError

from .job_state import TERMINAL_STATES, transition


def directory_for():
    return data_directory() / "jobs"


def job_path(directory, job):
    root = Path(directory)
    path = root / validate_job_id(job)
    if root.is_symlink() or path.is_symlink() or (path / "status.json").is_symlink():
        raise UserError("Symlink job metadata is not supported")
    return path


def read_status(path):
    if path.is_symlink() or (path / "status.json").is_symlink():
        raise UserError("Symlink job metadata is not supported")
    status = load(path / "status.json")
    if not isinstance(status, dict):
        raise UserError("Invalid job status object")
    return status


def write_status(path, status):
    temporary = path / ("status-" + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(status))
    temporary.replace(path / "status.json")


def change_state(path, target, **details):
    """Persist a valid transition from the latest status, preserving terminal states."""
    current = read_status(path)
    if current.get("state") in TERMINAL_STATES:
        return current
    updated = transition(current, target, **details)
    write_status(path, updated)
    return updated


def list_jobs(directory):
    entries = []
    for path in sorted(Path(directory).glob("*/status.json")):
        status = read_status(job_path(directory, path.parent.name))
        entries.append({**job_label(path.parent, status), "state": status["state"]})
    return entries


def inspect_job(directory, job):
    path = job_path(directory, job)
    return describe_job(path, read_status(path))


def validate_job_id(job):
    if not re.fullmatch(r"[0-9a-f]{32}", job):
        raise UserError("Invalid job ID")
    return job


def describe_job(path, status):
    """Describe metadata stored by the job worker."""
    arguments = status["arguments"]
    result = path / "result.txt"
    return {
        "id": path.name,
        "state": status.get("state", "unknown"),
        "command": shlex.join(["netmed", *arguments]),
        "arguments": arguments,
        "tool": status["tool"],
        "created_at": status["created_at"],
        "updated_at": datetime.fromtimestamp(
            (path / "status.json").stat().st_mtime, timezone.utc
        ).isoformat(),
        "exit_code": status.get("exit_code"),
        "objects": status.get("objects", []),
        "directory": str(path.resolve()),
        "result_bytes": result.stat().st_size
        if result.is_file() and not result.is_symlink()
        else None,
    }


def job_label(path, status):
    return {"id": path.name, "tool": status["tool"]}


def active(directory):
    """Check recorded worker PIDs without changing persisted job state."""
    result = []
    now = datetime.now(timezone.utc)
    for path in sorted(Path(directory).glob("*/status.json")):
        try:
            status = read_status(job_path(directory, path.parent.name))
            if status["state"] not in ("queued", "running"):
                continue
            entry = job_label(path.parent, status)
            if not worker_is_active(status.get("pid"), path.parent):
                continue
            started = datetime.fromisoformat(status["created_at"])
            seconds = max(0, int((now - started).total_seconds()))
            hours, remainder = divmod(seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            result.append(
                {
                    **entry,
                    "started_at": started.astimezone().strftime("%Y-%m-%d %H:%M"),
                    "runtime": f"{hours:02d}:{minutes:02d}:{seconds:02d}",
                }
            )
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return result


def clean(directory, job=None, dry_run=False):
    """Remove terminal job directories only; unknown/active states are preserved."""
    root = Path(directory)
    if root.is_symlink():
        raise UserError("Jobs root must not be a symlink")
    selected = [job] if isinstance(job, str) else (job or [])
    # Validate every ID before deleting anything; duplicate IDs are harmless.
    ids = list(dict.fromkeys(validate_job_id(item) for item in selected))
    candidates = [root / item for item in ids] if ids else sorted(root.glob("*"))
    result = {"dry_run": dry_run, "removed": [], "would_remove": [], "skipped": []}
    for path in candidates:
        details = {"id": path.name, "tool": None}
        try:
            validate_job_id(path.name)
            if path.is_symlink() or not path.is_dir():
                raise UserError("Not a regular job directory")
            data = read_status(path)
            details = job_label(path, data)
            if data.get("state") not in TERMINAL_STATES:
                raise UserError("Job is active or its state is unknown")
        except (OSError, ValueError, KeyError) as error:
            details["reason"] = (
                str(error)
                if isinstance(error, ValueError)
                else "Job metadata could not be read"
            )
            result["skipped"].append(details)
            continue
        if dry_run:
            result["would_remove"].append(details)
        else:
            try:
                shutil.rmtree(path)
            except OSError:
                details["reason"] = (
                    "Job files could not be removed; retry after the worker exits or check file permissions"
                )
                result["skipped"].append(details)
            else:
                result["removed"].append(details)
    return result


def kill(directory, job):
    """Stop the worker and its tools, preserving output files."""
    root = job_path(directory, job).resolve()
    status = read_status(root)
    if status["state"] in TERMINAL_STATES:
        return {**job_label(root, status), "state": status["state"]}
    stop_worker(status.get("pid"), root)
    status = change_state(
        root, "cancelled", cancelled_at=datetime.now(timezone.utc).isoformat()
    )
    return {**job_label(root, status), "state": status["state"]}


def launch(catalog, arguments, directory):
    job = uuid.uuid4().hex
    root = Path(directory).resolve() / job
    # Keep only the runtime configuration needed by this command.
    source = load(catalog)["sources"][arguments[0]]
    environment = None
    if source["kind"] == "python":
        from .python import prepare

        environment = prepare(source)
        execution = {
            key: source[key]
            for key in ("kind", "module", "submodules", "setup")
            if key in source
        }
    else:
        from .restish_binary import ensure

        ensure()  # Prepare the binary before detaching, as with Python environments.
        from .restish import resolve

        execution = {key: source[key] for key in ("kind", "timeout") if key in source}
        execution["restish"] = resolve(source)
        if "restish" not in execution:
            raise UserError(
                "API catalog requires rebuilding: run netmed build sources.toml"
            )
    root.mkdir(parents=True, mode=0o700)
    # Minimal routing envelope for the shared CLI execution path.
    (root / "execution.json").write_text(
        json.dumps({"sources": {arguments[0]: execution}})
    )
    if environment:
        (root / "environment.json").write_text(json.dumps(environment))
    status = transition(
        {
            "id": job,
            "tool": arguments[0],
            "arguments": arguments,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        "queued",
    )
    write_status(root, status)
    try:
        with (root / "worker.log").open("w") as log:
            pid = start_worker(root, log)
    except (OSError, subprocess.SubprocessError) as error:
        change_state(root, "failed", error="Worker could not start")
        raise UserError(
            "Job worker could not start; the job was marked failed"
        ) from error
    return {"id": job, "directory": str(root), "pid": pid}


def worker(root):
    root = Path(root)
    initial = read_status(root)
    arguments = initial["arguments"]
    execution_file = root / "execution.json"
    if change_state(root, "running", pid=os.getpid())["state"] != "running":
        return
    try:
        with (
            (root / "result.txt").open("w") as output,
            (root / "stderr.txt").open("w") as errors,
        ):
            source = load(execution_file)["sources"][initial["tool"]]
            if source["kind"] == "python":
                from .python import invoke

                code = invoke(
                    source,
                    arguments[1:],
                    name="netmed " + initial["tool"],
                    environment=load(root / "environment.json"),
                    stdout=output,
                    stderr=errors,
                )
            else:
                from .restish import invoke

                code = invoke(
                    source,
                    arguments[1:],
                    name="netmed " + initial["tool"],
                    stdout=output,
                    stderr=errors,
                )
        extra = {}
        from .object_store import execution_options

        _, object_options = (
            execution_options(arguments[1:]) if source["kind"] == "python" else ([], {})
        )
        if code == 0 and object_options:
            try:
                result = json.loads((root / "result.txt").read_text())
                if isinstance(result, dict) and isinstance(
                    result.get("saved_objects"), list
                ):
                    extra["objects"] = [item["id"] for item in result["saved_objects"]]
            except (ValueError, KeyError, TypeError):
                pass
        change_state(
            root, "completed" if code == 0 else "failed", exit_code=code, **extra
        )
    except Exception:
        change_state(root, "failed", error="Worker could not execute command")
