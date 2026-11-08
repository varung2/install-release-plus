#!/usr/bin/env bash
# Compile this local checkout into dist/InstallReleasePlus without installing it.
# --check exits successfully only when the existing build matches its inputs.
set -euo pipefail

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

[[ -n "${BASH_SOURCE[0]:-}" ]] || die "Run build.sh from a local checkout."
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$project_dir/pyproject.toml" && -f "$project_dir/cli/__main__.py" ]] ||
  die "The local checkout must contain pyproject.toml and cli/__main__.py."
command -v python3 >/dev/null 2>&1 || die "Install Python 3 before running this script."

build_state() {
  python3 - "$project_dir" "$@" <<'PYTHON'
import hashlib
import json
import os
from pathlib import Path
import platform
import sys

root = Path(sys.argv[1])
mode = sys.argv[2]
binary = root / "dist/InstallReleasePlus"
stamp = root / "dist/.irp-build.json"
inputs = hashlib.sha256()
inputs.update(f"{platform.system()}:{platform.machine()}".encode())
files = [root / name for name in ("build.sh", "pyproject.toml", "uv.lock")]
files += list((root / "InstallRelease").rglob("*.py"))
files += list((root / "cli").rglob("*.py"))
if (root / ".python-version").exists():
    files.append(root / ".python-version")
for path in sorted(files):
    inputs.update(str(path.relative_to(root)).encode() + b"\0")
    inputs.update(hashlib.sha256(path.read_bytes()).digest())
fingerprint = inputs.hexdigest()
if mode == "fingerprint":
    print(fingerprint)
    sys.exit(0)
if mode == "record" and fingerprint != sys.argv[3]:
    sys.exit("Build inputs changed during compilation; run build.sh again.")
try:
    state = {"inputs": fingerprint, "binary": hashlib.sha256(binary.read_bytes()).hexdigest()}
    if mode == "record":
        stamp.write_text(json.dumps(state) + "\n")
    elif not os.access(binary, os.X_OK) or json.loads(stamp.read_text()) != state:
        sys.exit(1)
except (OSError, ValueError):
    if mode == "record":
        raise
    sys.exit(1)
PYTHON
}

case "${1:-}" in
  --check) [[ $# -eq 1 ]] || die "Usage: build.sh [--check]"; build_state check; exit $? ;;
  "") ;;
  *) die "Usage: build.sh [--check]" ;;
esac

case "$(uname -s)" in
  Linux)
    command -v patchelf >/dev/null 2>&1 || die "Install patchelf with your OS package manager first."
    ;;
  Darwin) ;;
  *) die "Local standalone builds support Linux, macOS, and WSL."
esac
command -v uv >/dev/null 2>&1 || die "Install uv before running this script."
if ! command -v cc >/dev/null 2>&1 && ! command -v gcc >/dev/null 2>&1 && ! command -v clang >/dev/null 2>&1; then
  die "Install a C compiler (cc, gcc, or clang) before building."
fi

cd -- "$project_dir"
compiler_options=(--show-scons)
if [[ -n "${IRP_BUILD_JOBS:-}" ]]; then
  [[ "$IRP_BUILD_JOBS" =~ ^[1-9][0-9]*$ ]] || die "IRP_BUILD_JOBS must be a positive integer."
  compiler_options+=("--jobs=$IRP_BUILD_JOBS")
fi
build_fingerprint="$(build_state fingerprint)"
bold "Preparing dependencies for the local checkout ..."
# Dependencies may be fetched, but the IRP source and executable always come from
# this checkout. The lockfile is left unchanged.
uv sync --locked --dev
uv run --no-sync python -c 'import magic; magic.from_buffer(b"install-release-plus")' ||
  die "Install the libmagic runtime library with your OS package manager first."

bold "Compiling $project_dir into dist/InstallReleasePlus ..."
uv run --no-sync python -m nuitka \
  --standalone \
  --onefile \
  --include-package=rich \
  --include-distribution-metadata=InstallReleasePlus \
  "${compiler_options[@]}" \
  --follow-imports \
  --output-dir="$project_dir/dist" \
  --output-filename=InstallReleasePlus \
  "$project_dir/cli"

built_binary="$project_dir/dist/InstallReleasePlus"
[[ -x "$built_binary" ]] || die "Build did not produce an executable at $built_binary."
bold "Checking the compiled executable ..."
"$built_binary" --help >/dev/null
build_state record "$build_fingerprint"
printf 'Build complete: %s\n' "$built_binary"
