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

Update these files when `uv.lock`, the pinned uv or Restish version, or the
PyInstaller version in the build dependency group changes.
