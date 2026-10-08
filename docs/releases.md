# Native CLI builds

The current build produces a PyInstaller directory bundle for the build machine's OS/architecture. The user-facing command is `netmed` (`netmed.exe` on Windows). Its supporting files must stay together. A directory bundle avoids unpacking a new executable tree on every invocation.

```bash
uv sync --locked --group build
uv run --group build python scripts/build_cli.py
./dist/netmed/netmed --help
```

On Windows, run `./dist/netmed/netmed.exe`. Rebuild after changes to CLI code or sources. Build prerequisites are Python and uv 0.12.23; users of the resulting bundle need neither. Build caches live in `.build/` and archives in `dist/`. The first build installs scientific dependencies for discovery and lock generation and can take minutes. `--source networkx` selects the source before provisioning/discovery as well as export. Repeat --source for multiple sources. Python discovery is reused at export when configuration and lock match. API specs are snapshotted before native discovery and exported from the same snapshot.

## Included resources

The bundle contains the core interpreter/dependencies, independent worker package, uv 0.12.23, Restish 2.3.0, catalog, target-specific Python dependency locks and self-contained OpenAPI specification snapshots. The build verifies the Restish archive checksum and records native executable hashes in the resource manifest. Scientific package environments and their exact Python interpreters are installed on demand using bundled uv and hash-enforced locks. Source-only execution can use explicit NETMED_UV/NETMED_RESTISH paths.

`release-bundle` exports the resources without compiling the CLI. Lock and specification references are relative, not build-machine paths. Editable local packages are not release inputs. External OpenAPI `$ref` files must be combined into a self-contained specification before export. Remote API data remains live. Locks and hashes record provenance; they do not guarantee scientific validity, human review or byte-identical rebuilds. Build dependencies of packages distributed as source need separate release scrutiny.

## Storage

Installed application files contain executable code and read-only resources. NETMED_DATA_DIR contains only mutable state: `runtimes/`, `environments/`, `restish/` configuration/cache, `jobs/`, `objects/` and `logs.txt`. Executables are not downloaded there, and worker copies are not created. Worker code updates do not change dependency identities. Background jobs start the installed executable through its internal worker entry point.

## CI and publishing

The build workflow runs native Linux, macOS and Windows jobs on pull requests, main pushes, version-tag pushes or manual dispatch, validates a built artifact and uploads archives/checksums as workflow artifacts. Version tags additionally create a GitHub Release draft after lint, formatting, unit tests and all three native builds/binary tests succeed. Branch/PR builds only upload workflow artifacts. Each OS/architecture needs its own build; this is not cross-compilation. Local verification currently covers macOS arm64. CI results must be checked before claiming Windows/Linux distribution support.

Before public release: review dependency/source licenses and include required notices, validate all enabled sources on each target, decide signing/notarization and installation/update UX, and separate approved dependency updates from ordinary CLI builds. Scientific locks are versioned under `release-locks/<target>/`. CI consumes them through `--lock-directory` and does not freely re-resolve dependencies. Update them explicitly with `scripts/update_locks.py --target <target>`, review the diff, and validate each native target in CI. Cross-target resolution alone is not a successful platform test. Build checks provide feedback for deciding whether to merge; they are not configured as mandatory merge gates. No hosting is needed for execution beyond upstream services and downloadable release assets.

References: [PyInstaller operating mode](https://pyinstaller.org/en/stable/operating-mode.html), [uv secure installation](https://docs.astral.sh/uv/pip/compile/).

## Create a release draft

Commit and push the implementation, workflows and locks first. The first project version is `0.0.1`.

**Through the GitHub interface:** open **Actions → Build CLI → Run workflow**, select `main`, enable **Create a release draft after successful checks**, and run it. After checks pass, the workflow creates tag `v0.0.1` on the tested commit and a draft with the archives. No local tag command is required. This option is restricted to `main`; leaving it off creates build artifacts only.

**Alternatively, through a version tag:** tag the intended committed state:

```bash
git tag -a v0.0.1 -m "First release"
git push origin v0.0.1
```

For subsequent releases, update `project.version` in `pyproject.toml` and `uv.lock` before committing and use its matching `v<version>` tag. A mismatched tag causes the quality job to fail.

Watch **Actions → Build CLI** for the tag run. After all required jobs succeed, the release job downloads the three archives, verifies their SHA-256 checksums and creates a draft with six attached files (three archives plus checksums). Only this release job receives `contents: write`; builds keep read-only permissions. No separate access token is configured. Manual release dispatch creates its tag using the exact tested commit; an existing tag pointing elsewhere is rejected.

Open **Releases**, review the draft/notes and choose **Publish release** (or mark it as a pre-release first). Publication remains manual. Manual dispatch without the release option creates build artifacts only. Neither path publishes the release automatically.

If builds fail, correct the code and create a new version/tag. If only draft creation failed, retry that failed job. An existing release for the tag is not overwritten; review it instead of retrying creation. Branch checks are informational, but a release draft always requires successful quality and all platform build jobs.

## Pull-request feedback

Pull-request workflows use the default `actions/checkout` behavior: they check out GitHub's temporary merge commit combining the PR with its target branch. This tests the proposed combined state, not just the branch in isolation. It represents the target branch at that run; later target-branch changes require another run to validate the updated combination. Push workflows test the pushed commit. Lint and tests run on all pushes and PRs; native builds run on PRs, pushes to main, and manual dispatch.

Checks are informational for reviewers. No mandatory merge restrictions or branch rules are requested or configured.

## Explicit lock updates

```bash
# Update all supported targets:
uv run python scripts/update_locks.py --all

# Or select one target:
uv run python scripts/update_locks.py --target darwin-arm64
uv run python scripts/update_locks.py --target linux-amd64
uv run python scripts/update_locks.py --target windows-amd64
```

Each directory contains eight scientific requirements locks and a manifest binding their hashes and exact Python runtime versions to the dependency inputs in `sources.toml`. The normal build selects its current target automatically. A change to package/version/Python/dependency configuration requires an explicit lock update; help descriptions and module discovery settings do not require resolving dependencies again. Review candidate lock diffs and obtain a successful native PR build before accepting them. The initially generated Windows/Linux sets have been resolved on macOS, not locally installed or tested on those platforms.

`--all` processes the targets sequentially. If a target fails, the command stops; earlier completed targets may already have updated locks. It resolves dependencies for those targets but does not run their native builds.

## Distribution security and notices

Only configure trusted packages and registries: installs, discovery imports, setup calls, Pickle loading and explicit lambdas execute code with the caller's permissions. Dependency environments are not filesystem or network sandboxes. Command history stores complete arguments; `netmed logs --clear` removes it but does not prevent sensitive arguments from being recorded.

Release locks and archive hashes check integrity against trusted inputs; they do not establish safe code or publisher authenticity. Before public distribution, maintain bundled third-party license notices, evaluate signing/provenance and minimum supported OS versions, and verify native binaries reused from build caches. Build/test CI uses read-only content permissions and does not retain checkout credentials; pinning actions to immutable commit SHAs remains a hardening task. Scientific discovery should not receive publishing secrets.
