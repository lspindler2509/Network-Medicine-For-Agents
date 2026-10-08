#!/bin/sh
# User-local bundle installation; no Python or administrator privileges required.
set -eu
version=latest
while [ "$#" -gt 0 ]; do
  case "$1" in
    --version)
      [ "$#" -ge 2 ] || { echo '--version requires a value' >&2; exit 1; }
      version=$2; shift 2 ;;
    --version=*) version=${1#*=}; shift ;;
    -h|--help) echo 'Usage: install.sh [--version latest|v0.0.1]'; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done
if [ "$version" = latest ]; then
  api=${NETMED_RELEASE_API_URL:-"https://api.github.com/repos/lspindler2509/Network-Medicine-For-Agents/releases?per_page=1"}
  # Anonymous release listing includes published pre-releases, but no drafts.
  metadata=$(curl --fail --location --silent --show-error --proto '=https,file' "$api")
  version=$(printf '%s\n' "$metadata" | sed -n 's/.*"tag_name":[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)
  [ -n "$version" ] || { echo 'No published release found; use --version to select a version.' >&2; exit 1; }
fi
case "$version" in v[0-9]* ) ;; *) echo '--version must be latest or start with v and a version number' >&2; exit 1;; esac
case "$version" in *[!a-zA-Z0-9._-]* ) echo 'Invalid release version' >&2; exit 1;; esac
case "$(uname -s):$(uname -m)" in
  Darwin:arm64) target=darwin-arm64 ;;
  Linux:x86_64|Linux:amd64) target=linux-amd64 ;;
  *) echo 'Supported: Apple Silicon macOS and x64 Linux. Use install.ps1 for x64 Windows.' >&2; exit 1 ;;
esac
for command in curl tar; do command -v "$command" >/dev/null || { echo "Missing $command" >&2; exit 1; }; done
root=${NETMED_INSTALL_DIR:-"$HOME/.local/share/netmed-cli"}
bin=${NETMED_BIN_DIR:-"$HOME/.local/bin"}
case "$root:$bin" in /*:/*) ;; *) echo 'Installation and command directories must be absolute paths' >&2; exit 1;; esac
mkdir -p "$root" "$bin"
if [ -e "$bin/netmed" ] && [ ! -L "$bin/netmed" ]; then
  echo "Refusing to overwrite unrelated command: $bin/netmed" >&2; exit 1
fi
# Refuse concurrent installation rather than replacing an in-use staging tree.
mkdir "$root/.install-lock" 2>/dev/null || { echo "Installation already active: $root/.install-lock" >&2; exit 1; }
tmp=$(mktemp -d "$root/.install-XXXXXX")
cleanup() { rm -rf "$tmp"; rmdir "$root/.install-lock"; }
trap cleanup EXIT HUP INT TERM
base=${NETMED_RELEASE_BASE_URL:-"https://github.com/lspindler2509/Network-Medicine-For-Agents/releases/download/$version"}
archive="netmed-$target.tar.gz"
curl --fail --location --silent --show-error --proto '=https,file' "$base/$archive" -o "$tmp/$archive"
curl --fail --location --silent --show-error --proto '=https,file' "$base/$archive.sha256" -o "$tmp/checksum"
expected=$(awk 'NR==1 {print $1}' "$tmp/checksum")
if command -v sha256sum >/dev/null; then
  actual=$(sha256sum "$tmp/$archive" | awk '{print $1}')
else
  actual=$(shasum -a 256 "$tmp/$archive" | awk '{print $1}')
fi
[ "$actual" = "$expected" ] || { echo 'Checksum mismatch; installation unchanged.' >&2; exit 1; }
tar -xzf "$tmp/$archive" -C "$tmp"
[ -x "$tmp/netmed/netmed" ] || { echo 'Archive does not contain netmed executable' >&2; exit 1; }
# Keep versions separate so running jobs retain their original application files.
destination="$root/$version"
[ ! -e "$destination" ] || { echo "Already installed: $destination. Remove it to reinstall after stopping its jobs." >&2; exit 1; }
mv "$tmp/netmed" "$destination"
ln -sfn "$destination/netmed" "$bin/netmed"
# Persist the default command directory, without rewriting existing shell settings.
if [ "$bin" = "$HOME/.local/bin" ] && [ "${NETMED_MODIFY_PATH:-1}" = 1 ]; then
  case "${SHELL:-}" in
    */zsh) profile="$HOME/.zshrc" ;;
    */bash) profile="$HOME/.bashrc" ;;
    *) profile="$HOME/.profile" ;;
  esac
  line='export PATH="$HOME/.local/bin:$PATH" # netmed installer'
  touch "$profile"
  grep -Fq '# netmed installer' "$profile" || printf '\n%s\n' "$line" >> "$profile"
fi
printf 'Installed %s at %s\nRestart your terminal, then run: netmed --help\nFor this terminal: export PATH="%s:$PATH"\n' "$version" "$destination" "$bin"
