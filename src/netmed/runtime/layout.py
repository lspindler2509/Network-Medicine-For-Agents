"""Installed resource paths and the central mutable data directory."""

from pathlib import Path
import os
import sys


def data_directory():
    if os.environ.get("NETMED_DATA_DIR"):
        return Path(os.environ["NETMED_DATA_DIR"]).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "netmed"
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "netmed"
    return (
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "netmed"
    )


def asset_directory():
    return Path(__file__).resolve().parents[1] / "assets"


def default_catalog():
    if getattr(sys, "frozen", False):
        return asset_directory() / "catalog.json"
    return data_directory() / "catalog.json"


def bundled_uv():
    path = asset_directory() / "bin" / ("uv.exe" if os.name == "nt" else "uv")
    return str(path) if path.is_file() else None
