#!/usr/bin/env bash
# Install dist/InstallReleasePlus as ~/bin/irp, building this checkout only when needed.
# Usage: /path/to/install-release-plus/install.sh
set -euo pipefail

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

[[ -n "${BASH_SOURCE[0]:-}" ]] || die "Run install.sh from a local checkout, not through a pipe."
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
install_dir="${IRP_BIN_DIR:-$HOME/bin}"
[[ -f "$project_dir/pyproject.toml" && -f "$project_dir/cli/__main__.py" ]] ||
  die "The local checkout must contain pyproject.toml and cli/__main__.py."

[[ -x "$project_dir/build.sh" ]] || die "The local checkout must contain executable build.sh."
if "$project_dir/build.sh" --check; then
  bold "Using current local build: $project_dir/dist/InstallReleasePlus"
else
  bold "Local build is missing or stale; compiling ..."
  "$project_dir/build.sh"
fi
built_binary="$project_dir/dist/InstallReleasePlus"
# Check again on reuse, since system runtime dependencies may have changed.
"$built_binary" --help >/dev/null

# Replace the installed binary only after a successful build and smoke check.
# Stage in the destination directory so the final rename stays on one filesystem.
mkdir -p "$install_dir"
install_tmp="$(mktemp "$install_dir/.irp-install.XXXXXX")"
trap 'rm -f -- "$install_tmp"' EXIT
install -m755 "$built_binary" "$install_tmp"
mv -f -- "$install_tmp" "$install_dir/irp"

printf '\nInstalled local build: %s/irp\n' "$install_dir"
printf 'Build artifact: %s\n' "$built_binary"
printf '\nTo use it in your current Bash/Zsh terminal, run:\n'
printf '  export PATH=%q:"$PATH"\n' "$install_dir"
printf '  hash -r\n'
printf '  irp --help\n'
