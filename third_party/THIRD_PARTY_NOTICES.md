# Third-party notices

The netmed release bundle redistributes the components below. Their license
texts are in the folder of the same name. Python packages that netmed installs
on demand are downloaded by the user from their package index and are not part
of the bundle.

| Component | Version | License | Folder |
| --- | --- | --- | --- |
| Python (CPython runtime) | 3.11 / 3.13 | PSF-2.0 | `python/` |
| PyInstaller bootloader | 6.22.3 | GPL-2.0-or-later with bootloader exception | `pyinstaller/` |
| Restish | 2.3.0 | MIT | `restish/` |
| uv | 0.12.23 | MIT OR Apache-2.0 | `uv/` |
| requests | 2.34.2 | Apache-2.0 | `requests/` |
| urllib3 | 2.8.0 | MIT | `urllib3/` |
| certifi | 2026.7.22 | MPL-2.0 | `certifi/` |
| idna | 3.20 | BSD-3-Clause | `idna/` |
| charset-normalizer | 3.5.2 | MIT | `charset-normalizer/` |
| PyYAML | 6.0.3 | MIT | `pyyaml/` |
| psutil | 7.2.2 | BSD-3-Clause | `psutil/` |
| graphql-core | 3.2.13 | MIT | `graphql-core/` |
| setuptools (incl. vendored packages) | 84.0.0 | MIT; vendored packages as in their files | `setuptools/` |
| annotated-types | 0.8.0 | MIT | `annotated-types/` |
| anyio | 4.16.0 | MIT | `anyio/` |
| attrs | 26.1.0 | MIT | `attrs/` |
| cffi | 2.1.1 | MIT-0 | `cffi/` |
| click | 8.5.0 | BSD-3-Clause | `click/` |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | `cryptography/` |
| h11 | 0.16.0 | MIT | `h11/` |
| httpcore | 1.0.9 | BSD-3-Clause | `httpcore/` |
| httpx | 0.28.1 | BSD-3-Clause | `httpx/` |
| httpx-sse | 0.4.3 | MIT | `httpx-sse/` |
| jsonschema | 4.26.0 | MIT | `jsonschema/` |
| jsonschema-specifications | 2025.9.1 | MIT | `jsonschema-specifications/` |
| mcp | 1.30.0 | MIT | `mcp/` |
| pycparser | 3.12 | BSD-3-Clause | `pycparser/` |
| pydantic | 2.14.3 | MIT | `pydantic/` |
| pydantic-core | 2.50.4 | MIT | `pydantic-core/` |
| pydantic-settings | 2.16.2 | MIT | `pydantic-settings/` |
| pyjwt | 2.15.1 | MIT | `pyjwt/` |
| python-dotenv | 1.2.4 | BSD-3-Clause | `python-dotenv/` |
| python-multipart | 0.0.33 | Apache-2.0 | `python-multipart/` |
| referencing | 0.37.0 | MIT | `referencing/` |
| rpds-py | 2026.9.1 | MIT | `rpds-py/` |
| sse-starlette | 3.6.0 | BSD-3-Clause | `sse-starlette/` |
| starlette | 1.10.0 | BSD-3-Clause | `starlette/` |
| typing-extensions | 4.16.0 | PSF-2.0 | `typing-extensions/` |
| typing-inspection | 0.4.5 | MIT | `typing-inspection/` |
| uvicorn | 0.54.0 | BSD-3-Clause | `uvicorn/` |

Update these files when `uv.lock`, the pinned uv or Restish version, or the
PyInstaller version in the build dependency group changes.
