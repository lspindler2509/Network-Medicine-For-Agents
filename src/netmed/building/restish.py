"""Download verified Restish artifacts at build time, never at user runtime."""

import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import zipfile
import requests
from ..runtime.environments import installation_lock
from ..runtime.restish_binary import VERSION, CHECKSUMS, target, verify
from ..errors import UserError


def download(destination):
    system, architecture = target()
    root = Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=True)
    executable = root / ("restish.exe" if system == "windows" else "restish")
    if executable.is_file():
        return str(executable)
    with installation_lock(root / "install.lock"):
        if executable.is_file():
            return str(executable)
        suffix = "zip" if system == "windows" else "tar.gz"
        asset = f"restish-{VERSION}-{system}-{architecture}.{suffix}"
        url = f"https://github.com/rest-sh/restish/releases/download/v{VERSION}/{asset}"
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        if (
            hashlib.sha256(response.content).hexdigest()
            != CHECKSUMS[(system, architecture)]
        ):
            raise UserError("Restish archive checksum mismatch; installation refused")
        # Extract only the executable bytes, never archive paths or links.
        if suffix == "zip":
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                members = [
                    x
                    for x in archive.infolist()
                    if Path(x.filename).name == executable.name and not x.is_dir()
                ]
                if len(members) != 1:
                    raise UserError("Restish archive does not contain one executable")
                data = archive.read(members[0])
        else:
            with tarfile.open(fileobj=io.BytesIO(response.content)) as archive:
                members = [
                    x
                    for x in archive.getmembers()
                    if Path(x.name).name == executable.name and x.isfile()
                ]
                if len(members) != 1:
                    raise UserError("Restish archive does not contain one executable")
                data = archive.extractfile(members[0]).read()
        with tempfile.TemporaryDirectory(dir=root) as directory:
            temporary = Path(directory) / executable.name
            temporary.write_bytes(data)
            temporary.chmod(0o755)
            verify(temporary)
            temporary.replace(executable)
    return str(executable)
