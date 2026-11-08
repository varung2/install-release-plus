# InstallReleasePlus

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
| `irp get <repo-url> --pkg` | Install a supported OS package. |
| `irp ls` | List tracked installations and downloads; add `--json` for JSON. |
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

Kept archives remain intact and are tracked as `<repo>-download` by default.
Use the same `ls`, `info`, `upgrade`, and `rm` commands to manage them. Upgrades
look for the same asset filename in the newer release. `get -y` skips prompts
and uses the executable installation flow; choose archive tracking interactively.

## Differences from upstream

- The command is `irp`, and the project name is InstallReleasePlus.
- `get` can keep an archive as a tracked download without extracting or installing
  an executable. There is no separate `download` command.
- Local `build.sh` and `install.sh` compile and install this checkout.
- Additional regression tests cover archive tracking, failed updates, state
  persistence, and local build/install behavior.

This fork does not add separate storage and executable directories or symlink
management. Executable installation remains focused on standalone binaries;
application bundles requiring sibling libraries are unsupported. The internal
`InstallRelease` package and existing state/config paths are retained to make
upstream merges easier.

## Tests

```bash
uv sync --locked --dev
uv run --no-sync pytest -q test
```

The default suite runs without external network access once dependencies are
installed; it uses local fixtures and loopback connections. Compiled-binary and
live integration tests are opt-in. See [extended documentation](README-ORIGINAL.md)
for those commands, offline CI setup, providers, and configuration details.

## License

GNU General Public License v3. See [LICENSE](LICENSE). Upstream attribution and
the license are preserved in this fork.
