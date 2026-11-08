# Install Release Plus

Install and update CLI tools from project releases, or keep release archives as
tracked downloads, using `irp`.

This is a fork of **[install-release](https://github.com/Rishang/install-release)**,
created by **[Rishang](https://github.com/Rishang)**. Credit for the original tool
and its core functionality belongs to Rishang and the upstream contributors.
This fork is maintained at [varung2/install-release-plus](https://github.com/varung2/install-release-plus).

## Quickstart

Build requirements: Python 3.10+, [uv](https://docs.astral.sh/uv/), a C compiler,
and the `libmagic` runtime library. Linux also requires `patchelf`; `ccache` is
optional. See the [extended setup instructions](README-ORIGINAL.md#getting-started)
for more detail.

```bash
git clone https://github.com/varung2/install-release-plus.git
cd install-release-plus
./install.sh

export PATH="$HOME/bin:$PATH"
irp --help
irp get https://github.com/ekzhang/bore
```

`install.sh` installs the local build at `~/bin/irp`, building first if the
executable is missing or stale. It does not download an upstream executable.
Installing build dependencies may require internet access. Add `~/bin` to your
shell's persistent `PATH` if needed.

```bash
./build.sh          # Compile only: dist/InstallReleasePlus
./build.sh --check  # Exit successfully if the local build is current
./install.sh        # Build when needed, then install
```

## Command reference

| Command | Purpose |
| --- | --- |
| `irp get <repo-url>` | Select and install a release asset, or keep an archive. |
| `irp get <repo-url> --tag <tag> --file <filename>` | Choose a release and asset explicitly; both options are optional. |
| `irp get <repo-url> --name <name>` | Choose a custom installation name. |
| `irp get <repo-url> --output <directory>` | Use a destination for this invocation only (`-o`); the configured default is unchanged. |
| `irp get <repo-url> --pkg` | Install a supported OS package. |
| `irp ls` | List tracked installations and downloads with their install paths; add `--json` for JSON. |
| `irp info <name>` | Show a tracked item's details. |
| `irp upgrade [name]` | Upgrade one item, or all eligible items. |
| `irp rm <name>` | Remove an item and its tracking record. |
| `irp hold <name>` | Pause updates; use `irp hold --unset <name>` to resume. |
| `irp config --path <directory>` | Set the default destination for installations and downloads. |
| `irp <command> --help` | Show all options for a command. |

Without `--tag`, `get` uses the latest release. You can choose another asset by
its ID before confirming. Selecting an archive offers **Install its executable**
or **Keep archive as a tracked download**, followed by final confirmation.
An explicit `--tag` also places the item on hold to preserve that version.

GitHub releases also list their generated source archives as `source.tar.gz` and
`source.zip`, including releases with no uploaded assets. Uploaded assets remain
preferred for automatic selection. To keep a source archive, use
`irp get <repo-url> --file source.zip -o ~/downloads/sources`, choose **2**, then
confirm. Source archives remain compressed; this does not extract or install skills.

Kept archives remain intact and are tracked as `<repo>-download` by default.
Use the same `ls`, `info`, `upgrade`, and `rm` commands to manage them. Upgrades
look for the same asset filename in the newer release. `get -y` skips prompts
and uses the executable installation flow; choose archive tracking interactively.

To keep an archive in a different directory:

```bash
irp get https://github.com/owner/project --output ~/downloads/releases
# Select an archive, then choose "Keep archive as a tracked download".
```

`--output` also works for binary installs, mise tools, and Docker wrappers.
Paths may be relative or use `~`; the saved location is reused for upgrades and
removal. Native packages (including AppImages) do not support this option.
Remove an existing tracked item before relocating it to a different directory.

## Differences from upstream

- The command is `irp`, and the project name is Install Release Plus.
- `get` can keep an archive as a tracked download without extracting or installing
  an executable. There is no separate `download` command.
- Local `build.sh` and `install.sh` compile and install this checkout.
- Additional regression tests cover archive tracking, failed updates, state
  persistence, and local build/install behavior.

This fork does not add separate storage and executable directories or symlink
management. Executable installation remains focused on standalone binaries;
application bundles requiring sibling libraries are unsupported. The internal
`InstallRelease` package and existing state/config paths are retained to make
upstream merges easier. These compatibility names are intentional; user-facing
names use Install Release Plus and `irp`. Set `IRP_DEBUG=true` for debug logging
(the upstream `IR_DEBUG` variable remains a fallback).

New executable installations record their full path. For older records, `ls`
marks paths derived from the current configuration as **inferred**. Downloads
show their saved directory; OS packages show **System package manager** because
their files may span several directories. JSON output adds `install_path` and
`path_inferred`.

**Name collisions:** before downloading a binary or pulling a Docker image, `irp`
compares existing and proposed names, paths, repositories, tags, assets, and
settings. Overwriting requires confirmation, defaulting to **No**. `get -y`
explicitly approves overwrites after showing the comparison. Matching tracked
releases at an existing destination are skipped, even with `-y`; Docker images
also require matching digests. `upgrade --force` can request a reinstall.

Successful replacement removes previous binary tracking records for that
destination. Untracked files show unknown release details. Symlinks and
directories are rejected. Use `--name` to choose a distinct executable name.
Tracked downloads retain their separate file-ownership checks; native package
conflicts are handled by the system package manager.

## Tests

```bash
uv sync --locked --dev
uv run --no-sync pytest -q test
```

The default suite runs without external network access once dependencies are
installed; it uses local fixtures and loopback connections. Compiled-binary and
live integration tests are opt-in. See [extended documentation](README-ORIGINAL.md)
for those commands, offline CI setup, providers, and configuration details.

CI reuses a compiler cache, logs C compiler commands, and limits standalone
compilation to 45 minutes. See [upstream sync setup](README-ORIGINAL.md#automatic-upstream-synchronization)
for the scheduled App-authenticated PR and merge workflow.

## License

GNU General Public License v3. See [LICENSE](LICENSE). Upstream attribution and
the license are preserved in this fork.
