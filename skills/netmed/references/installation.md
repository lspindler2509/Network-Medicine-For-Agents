# Install or locate netmed

Project: <https://github.com/lspindler2509/Network-Medicine-For-Agents>

First try `netmed --help`. If PATH lookup fails, check an existing installation:

- macOS/Linux: `~/.local/bin/netmed`; installed bundles normally live in
  `~/.local/share/netmed-cli/<version>/`.
- Windows: `%LOCALAPPDATA%\Programs\netmed\<version>\netmed.exe`.
- An extracted download contains `netmed/netmed` or `netmed/netmed.exe` plus its
  supporting files. Keep the entire directory together.

Use the existing executable by absolute path, or refresh the current shell's
PATH, before installing a duplicate. Inspect `--help`; a binary built before a
feature was added does not gain it from changes to a repository checkout.

## Published bundles

Supported published targets are macOS Apple Silicon, Linux x64 and Windows x64.
For other architectures, check release assets and current project instructions
rather than selecting an incompatible binary.

For an installation requested by the user, the project provides these commands.
They download and execute the installer and may update the user's shell PATH.
Follow the host's execution permissions. The installer scripts can be inspected
at the same URLs before execution.

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/lspindler2509/Network-Medicine-For-Agents/main/installers/install.sh | sh
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/lspindler2509/Network-Medicine-For-Agents/main/installers/install.ps1 | iex
```

The installer selects the newest published release, including pre-releases but
excluding drafts, and verifies the archive checksum. Honor an explicitly requested
version using the installer options documented in the project README. Updating
does not require deleting old environments or results; stop relevant jobs first.

Alternatively download a matching binary asset from
<https://github.com/lspindler2509/Network-Medicine-For-Agents/releases>, extract it,
and invoke the executable from the complete directory. GitHub's automatic
"Source code" archives are not the application bundles. If no matching published
asset exists, report that and consult the project's build instructions rather
than promising that installation succeeded.

## Alternative installation directories

The installers support `NETMED_INSTALL_DIR` for versioned bundles and
`NETMED_MODIFY_PATH=0` to suppress persistent PATH edits. The macOS/Linux installer
also supports `NETMED_BIN_DIR` for the executable link. Changing only the install
directory still leaves that link in its default location.

For an optional isolated macOS/Linux trial:

```sh
netmed_trial_dir=$(mktemp -d)
curl -fsSL https://raw.githubusercontent.com/lspindler2509/Network-Medicine-For-Agents/main/installers/install.sh \
  -o "$netmed_trial_dir/install.sh"
NETMED_INSTALL_DIR="$netmed_trial_dir/install" \
NETMED_BIN_DIR="$netmed_trial_dir/bin" NETMED_MODIFY_PATH=0 \
  sh "$netmed_trial_dir/install.sh"
NETMED_DATA_DIR="$netmed_trial_dir/data" "$netmed_trial_dir/bin/netmed" --help
```

Keep using that executable and the same `NETMED_DATA_DIR` for subsequent calls.
Changing the data directory changes lookup of prepared environments and saved
objects; it does not reuse or move them automatically. uv may still access its
normal shared cache outside that directory. This is installation/data isolation,
not a fully isolated filesystem sandbox.

## Distinguish startup and runtime failures

- **Command not found:** check PATH or invoke the existing executable directly.
- **Silent exit or termination before `--help`:** capture exit status and stderr,
  verify the archive checksum, OS/architecture and complete extracted directory.
  Exit 137 indicates a killed process, not proof of a missing Python package or
  a specific cause. OS security controls or resource limits may require further
  diagnosis; do not bypass security controls based only on this exit code.
- **Missing catalog/index:** distinguish a source checkout from a published
  bundle. Prefer a matching published bundle rather than a full source rebuild.
- **Provisioning/network/cache errors after CLI startup:** preserve the actual
  diagnostic and follow host network/filesystem permissions. Reinstalling the
  CLI does not fix blocked API access or a denied shared uv cache.

Do not repeatedly launch a silent process without a bounded wait. If the cause
remains unknown, report it rather than claiming that a different download or a
security attribute proves the diagnosis.

## Verify

```sh
netmed --help
netmed find --help
netmed find "shortest path" --limit 3
netmed networkx path_graph 4 - number_of_nodes
```

The final command should print `4`. The bundle contains the core runtime, uv and
Restish. Scientific packages and their Python interpreters install automatically
on first use, which needs internet. The API sources also need network access.
There is no need to install all source packages into the agent's own Python.

Mutable data defaults to `~/Library/Application Support/netmed` on macOS,
`${XDG_DATA_HOME:-~/.local/share}/netmed` on Linux and `%LOCALAPPDATA%\netmed`
on Windows. `NETMED_DATA_DIR` overrides it. Report the executable location and any
verification that could not run. Installing this skill alone does not install netmed.
