"""Platform-specific worker startup, verification and termination."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import psutil
from ..errors import UserError
from .layout import data_directory

_workers = []


def prepare_external_process():
    """Release the frozen Windows DLL search path before starting external tools."""
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        import ctypes

        ctypes.windll.kernel32.SetDllDirectoryW(None)


def process_environment():
    # Do not inherit arbitrary credentials, PYTHONPATH, active venvs or uv settings.
    names = {
        "PATH",
        "HOME",
        "USERPROFILE",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "NETMED_DATA_DIR",
    }
    result = {k: v for k, v in os.environ.items() if k in names}
    result["PYTHONNOUSERSITE"] = "1"
    result["UV_PYTHON_INSTALL_DIR"] = str(data_directory() / "runtimes")
    return result


def job_command(root):
    prefix = (
        [sys.executable]
        if getattr(sys, "frozen", False)
        else [sys.executable, "-m", "netmed"]
    )
    return [*prefix, "_job-worker", str(root)]


def _windows():
    return sys.platform == "win32"


def detached_options():
    if _windows():
        # Win32 DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP.
        return {"creationflags": 0x00000008 | 0x00000200}
    return {"start_new_session": True}


def start_worker(root, log):
    environment = process_environment()
    for name in ("NETMED_UV", "NETMED_RESTISH"):
        if name in os.environ:
            environment[name] = os.environ[name]
    if getattr(sys, "frozen", False):
        environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    process = subprocess.Popen(
        job_command(root),
        env=environment,
        stdout=log,
        stderr=log,
        stdin=subprocess.DEVNULL,
        **detached_options(),
    )
    # Retain handles while children run; reap finished workers on subsequent starts.
    _workers[:] = [worker for worker in _workers if worker.poll() is None]
    _workers.append(process)
    return process.pid


def _worker(pid, root):
    if type(pid) is not int or pid <= 0:
        raise UserError("Worker PID not available; retry after the job has started")
    process = psutil.Process(pid)
    arguments = process.cmdline()
    prefix = arguments[:-1]
    expected = (len(prefix) == 2 and prefix[-1:] == ["_job-worker"]) or (
        len(prefix) == 4 and prefix[-3:] == ["-m", "netmed", "_job-worker"]
    )
    if not expected or os.path.normcase(
        os.path.abspath(arguments[-1])
    ) != os.path.normcase(str(Path(root).resolve())):
        raise UserError("No matching job worker found")
    if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
        raise UserError("Worker is no longer running")
    return process


def worker_is_active(pid, root):
    try:
        _worker(pid, root)
        return True
    except (psutil.Error, ValueError, OSError):
        return False


def stop_worker(pid, root):
    try:
        process = _worker(pid, root)
        children = process.children(recursive=True)
        if _windows():
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode:
                raise UserError("Windows could not stop the job process tree")
        else:
            if os.getpgid(pid) != pid:
                raise UserError(
                    "Worker is not the expected detached process group leader"
                )
            os.killpg(pid, signal.SIGKILL)
        _, alive = psutil.wait_procs([process, *children], timeout=5)
        # POSIX zombies have stopped executing but may await reaping by their parent.
        if any(p.is_running() and p.status() != psutil.STATUS_ZOMBIE for p in alive):
            raise UserError(
                "Some job processes are still running; cancellation was not confirmed"
            )
    except psutil.Error as error:
        raise UserError(
            "Could not inspect or stop the job worker; check its status and process permissions"
        ) from error


def activity_process_identity():
    """Record process creation time as well as PID to detect PID reuse."""
    process = psutil.Process()
    return {"pid": process.pid, "created_at": process.create_time()}


def activity_process_alive(record):
    try:
        process = psutil.Process(record["pid"])
        return process.create_time() == record["created_at"] and process.is_running()
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied as error:
        raise UserError("Cannot verify active process; cleanup refused") from error
