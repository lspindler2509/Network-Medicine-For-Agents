"""Append invocation records without capturing environment variables or results."""

from datetime import datetime
import os
import shlex
import subprocess
from .layout import data_directory


def record_command(arguments):
    path = data_directory() / "logs.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().isoformat(sep=" ", timespec="seconds")
    args = [
        "netmed",
        *(
            argument.replace("\r", r"\r").replace("\n", r"\n").replace("\t", r"\t")
            for argument in arguments
        ),
    ]
    command = subprocess.list2cmdline(args) if os.name == "nt" else shlex.join(args)
    line = f"[{timestamp}] {command}\n".encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "ab") as stream:
        stream.write(line)
    return path


def read_commands(tail=None):
    """Read history on demand; optionally retain only the last N records."""
    from collections import deque

    path = data_directory() / "logs.txt"
    try:
        with path.open(encoding="utf-8") as stream:
            return "".join(stream if tail is None else deque(stream, maxlen=tail))
    except FileNotFoundError:
        return ""


def clear_commands():
    """Remove the complete command history, including this invocation."""
    (data_directory() / "logs.txt").unlink(missing_ok=True)
