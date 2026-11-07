<p align="center">
  <img src="./.github/images/banner.png" alt="InstallReleasePlus — easily install any release" width="100%" />
</p>
<p align="center">
  <em>CLI to install any CLI</em>
  <br><br>
  <a href="https://shields.io/">
    <img src="https://img.shields.io/badge/Python-3.10_to_3.14-xx.svg" alt="Python Version" />
  </a>
<p>

<br>




**InstallReleasePlus** is a fork of [install-release](https://github.com/Rishang/install-release). The internal `InstallRelease` package and existing state/config paths are preserved to simplify upstream merges.

**InstallReleasePlus** gives you the `irp` command to install and keep single-binary CLI tools updated on Linux, macOS, and WSL. It works with GitHub, GitLab, and Forgejo-powered Codeberg releases, and supports mise/aqua registry entries and Docker images.

This can be any tool you want to install, which is pre-compiled for your device and present on a supported provider.


<a href="#getting-started"><img src=".github/images/demo.gif" alt="irp CLI demo: install gron from GitHub, glab from GitLab and terraform from the mise registry, list and remove tools" width="100%" /></a>

> INFO: It's mainly for installing tools that are not directly available officially by package managers like `apt, yum, pacman, brew` etc.

<p align="center">
  <img src=".github/images/flow.png" alt="How it works" width="800">
</p>

## Highlights

#### [GitHub, GitLab, and Codeberg releases](#install-tool-from-github-gitlab-and-codeberg-releases-)

`irp` is mainly built for installing CLI tools straight from GitHub, GitLab, or Codeberg releases. Codeberg support uses its Forgejo-compatible API. Give `irp` a repository URL, and it finds the right release asset for your system.

```bash
# Install from GitHub
irp get https://github.com/denoland/deno

# Install from GitLab
irp get https://gitlab.com/gitlab-org/cli -n glab

# Install from Codeberg (Forgejo)
irp get https://codeberg.org/forgejo/forgejo

# Install from a self-hosted GitLab or Forgejo instance
irp get gitlab@gitlab.example.com/group/subgroup/mytool
irp get forgejo@git.example.com/owner/mytool
```

#### [Package mode (`--pkg`)](#install-as-system-package-debrpmappimage-)

Some tools ship better as `.deb`, `.rpm`, or `AppImage` packages. Use `--pkg` when you want `irp` to install that package instead of picking a standalone binary.

```bash
# Install any package from GitHub releases
irp get https://github.com/redis/RedisInsight --pkg
```

#### Extra providers

- [mise/aqua](#install-tool-via-mise-registry-): Install tools from registry metadata.

```bash
# Install from mise/aqua registry
irp get mise@terraform
```

- [Docker](#install-docker-image-as-a-cli-tool-): Run container images like local CLIs.

```bash
# Install from Docker image (with custom name)
irp get docker@mcr.microsoft.com/azure-cli -n az
```
<!-- Table of content -->

## Table of Contents 📚

- [Table of Contents 📚](#table-of-contents-)
- [Highlights](#highlights)
- [Getting started ⚡](#getting-started)
  - [Installation](#installation)
  - [Manage your tools](#manage-your-tools)
- [Example usage `irp --help` 💡](#example-usage-irp---help-)
  - [Install completion for cli 🎠](#install-completion-for-cli-)
  - [Install tool from GitHub, GitLab, and Codeberg releases 🌈](#install-tool-from-github-gitlab-and-codeberg-releases-)
    - [Self-hosted GitLab and Forgejo instances 🏠](#self-hosted-gitlab-and-forgejo-instances-)
    - [Install as system package (deb/rpm/appimage) 📦](#install-as-system-package-debrpmappimage-)
  - [Install tool via mise registry 🧩](#install-tool-via-mise-registry-)
  - [Install Docker image as a CLI tool 🐳](#install-docker-image-as-a-cli-tool-)
  - [Download and track release assets](#download-and-track-release-assets)
  - [Install specific release asset from GitHub, GitLab, or Codeberg releases 🔦](#install-specific-release-asset-from-github-gitlab-or-codeberg-releases-)
    - [Method 1: Interactive Selection (Recommended)](#method-1-interactive-selection-recommended)
    - [Method 2: Command-line Flag](#method-2-command-line-flag)
  - [List installed tools 📋](#list-installed-tools-)
  - [Show info about an installed tool ℹ️](#show-info-about-an-installed-tool-️)
  - [Remove installed release ❌](#remove-installed-release-)
  - [Update all previously installed tools to the latest version 🕶](#update-all-previously-installed-tools-to-the-latest-version-)
    - [Update installed system packages 📦](#update-installed-system-packages-)
  - [Pull state templates for installing tools 📄](#pull-state-templates-for-installing-tools-)
  - [Hold Update to specific installed tool ✋](#hold-update-to-specific-installed-tool-)
  - [Configure tool installation path 🗂️](#configure-tool-installation-path)
  - [Configure updates for pre-release versions 🔌](#configure-updates-for-pre-release-versions-)
  - [Configure provider tokens for higher rate limits 🔑](#configure-provider-tokens-for-higher-rate-limits-)


## Getting started



### Installation

#### Option 1: Build and install this checkout

`build.sh` compiles the local source into `dist/InstallReleasePlus`. `install.sh`
checks that build and installs it at `~/bin/irp`, calling `build.sh` only when
needed. It replaces an existing executable at that path after a successful build
and smoke check. It does not download a published binary or register this local
build with a release updater.

Prerequisites on Linux/macOS/WSL:

- `uv` and a Python version supported by the project (Python 3.10 or newer).
- A C compiler (`cc`, GCC, or Clang); on macOS, install the Xcode command line tools.
- `patchelf` on Linux.
- The `libmagic` runtime library (`file-libs` on Fedora/RHEL, `libmagic` with Homebrew).
- Optional: `ccache` to speed up subsequent builds.

From your local checkout, run:

```bash
./build.sh    # Build only; always compiles
./install.sh  # Install, building first only if missing or stale
```

Both scripts work when invoked by full path from another working directory.
The build script synchronizes the locked development dependencies with `uv`,
compiles using Nuitka, and checks `dist/InstallReleasePlus --help`. It records a fingerprint in
`dist/.irp-build.json`; installation reuses the executable only when the Python
sources, build script, dependency files, platform, and binary content still match.
Added or deleted source files also trigger rebuilding. An existing executable
without a fingerprint is rebuilt once. Use `./build.sh --check` to check freshness
without compiling (exit status 0 means current; 1 means missing or stale).
Dependency setup and compiler tooling may require network access; InstallReleasePlus
itself is always built from this checkout, including your uncommitted changes.
Run `./install.sh` again after source changes; it rebuilds automatically when needed.

After installation, refresh command lookup in your existing Bash/Zsh terminal:

```bash
export PATH="$HOME/bin:$PATH"
hash -r
command -v irp
irp --help
```

`command -v irp` should resolve to `~/bin/irp`. The compiled artifact is also kept
at `dist/InstallReleasePlus`. A failed build or smoke check leaves the installed
binary intact. `irp me -U` installs a published release from this fork; use
`./install.sh` to update from your local checkout instead.

To test the checkout, force a fresh build, and install it:

```bash
uv sync --locked --dev
uv run --no-sync pytest -q test --ignore=test/test_install.py
uv run --no-sync ruff check .
./build.sh
./install.sh
```

The Docker installation integration tests are separate. They require a running
Docker daemon, permission to access it, and network access to download test tools:

```bash
cd test
../.venv/bin/pytest -q test_install.py
cd ..
```

The existing AWS CLI integration case currently fails at runtime because its
launcher needs a sibling Python shared library from the release bundle. Keeping
an archive as a tracked download is supported; installing that multi-file bundle
is outside the supported single-executable scope. The failure remains visible
in the test suite.

After confirming `irp --help` works, remove the old tracked installation if
`irp ls` still lists `ir`. This also removes its state entry so a later upgrade
does not reinstall the upstream executable:

```bash
irp rm ir
```

Then remove any remaining legacy `ir` executables:

```bash
rm -f "$HOME/bin/ir" "$HOME/.local/bin/ir"
hash -r
type -a irp
```

The command should resolve to `~/bin/irp`. Build scripts never create an `ir`
alias or install another copy into `~/.local/bin`.


#### Option 2: Install this checkout with pip

**Prerequisites:**

- Python 3.10 or higher
- pip
- [libmagic](https://github.com/ahupp/python-magic#installation)

```bash
pip install .
```

---

**Set up the PATH for shell (e.g. ~/.bashrc or ~/.zshrc):**

Tools installed via `irp` will be installed to `~/bin` by default.

```bash
export PATH="$HOME/bin:$PATH" 
```

If you want to change the installation path, you can use the `irp config --path <path>` flag.

---

### Manage your tools

Example: Installing [deno (Rust-based JavaScript runtime)](https://github.com/denoland/deno) directly from its GitHub releases:

```bash
# Usage: irp get [GITHUB-URL or GITLAB-URL or CODEBERG-URL or gitlab@<HOST>/<OWNER>/<REPO>
#                or forgejo@<HOST>/<OWNER>/<REPO> or mise@<TOOL> or docker@<IMAGE-URI>]

# GitHub URL
❯ irp get https://github.com/denoland/deno

# mise registry
❯ irp get mise@terraform

# Docker image with latest tag
❯ irp get docker@hashicorp/terraform:latest
```

Verify the installation:

```bash
❯ which deno
~/bin/deno

❯ deno --version
deno 1.46.3 ...
```

Example: Installing [GitLab CLI](https://gitlab.com/gitlab-org/cli) with a custom binary name `glab`:

```bash
❯ irp get https://gitlab.com/gitlab-org/cli -n glab
```

Verify the installation:

```bash
❯ which glab
~/bin/glab

❯ glab --version
glab 1.80.0 ...
```

Codeberg repositories use the same install and update workflow. For example, install [Forgejo](https://codeberg.org/forgejo/forgejo) from its Codeberg releases:

```bash
❯ irp get https://codeberg.org/forgejo/forgejo
```

Once installed, you can manage your tools with these simple commands:

- **List**: `irp ls` — See all installed tools and versions.
- **Update**: `irp upgrade` — Upgrade all installed tools to their latest releases, or use `irp upgrade <name>` for a specific tool.
- **Remove**: `irp rm deno` — Remove a tool from your system.

For more details, check the [Table of Contents](#table-of-contents-).


## Example usage `irp --help` 💡

```
# Help page

❯ irp --help
Usage: irp [OPTIONS] COMMAND [ARGS]...

  GitHub / GitLab / Codeberg / Mise release installer based on your system (Linux/MacOS)

  Options:
    --install-completion   Install completion for the current shell.
    --show-completion      Show completion for the current shell, to copy it or customize the installation.
    --help                Show this message and exit.

  Commands:
    get      | Install a CLI tool or keep a release archive as a tracked download
    upgrade  | Upgrade all installed CLI tools from their repositories
    ls       | List all installed CLI tools
    info     | Show info about an installed CLI tool
    rm       | Remove any installed CLI tool
    config   | Set configs for Install-Release
    state    | Show the current stored state of Install-Release
    pull     | Install tools from the remote InstallReleasePlus state URL
    hold     | Keep an installed CLI tool's updates on hold.
    me       | Update the Install-Release tool.
```

For sub-command help use: `irp <sub-command> --help`

Example: `irp get --help`

#### Install completion for cli 🎠

```bash
# irp --install-completion [SHELL: bash|zsh|fish|powershell]
# Example for zsh:
irp --install-completion zsh
```

#### Install tool from GitHub, GitLab, and Codeberg releases 🌈

Use a repository URL in one of these forms:

```text
https://github.com/<owner>/<repo>
https://gitlab.com/<owner>/<repo>
https://codeberg.org/<owner>/<repo>
```

Codeberg is powered by Forgejo, so `irp` accesses Codeberg releases through the Forgejo-compatible API. Codeberg tools are recorded in `irp`'s state and can be managed with `irp ls`, `irp info`, `irp upgrade`, and `irp rm` like tools from GitHub and GitLab.

```bash
# Install Forgejo from Codeberg
❯ irp get https://codeberg.org/forgejo/forgejo
```

##### Self-hosted GitLab and Forgejo instances 🏠

Self-hosted instances are addressed with a provider prefix, which tells `irp` which API the domain speaks (https is assumed):

```text
gitlab@<host>/<owner>/<repo>
forgejo@<host>/<owner>/<repo>
```

```bash
# Self-hosted GitLab (GitLab subgroups are supported)
❯ irp get gitlab@gitlab.example.com/group/subgroup/mytool

# Self-hosted Forgejo / Gitea
❯ irp get forgejo@git.example.com/owner/mytool
```

Self-hosted tools are recorded in state under their prefixed form, so `irp ls`, `irp info`, `irp upgrade`, and `irp rm` work on them like any other tool. See [provider tokens](#configure-provider-tokens-for-higher-rate-limits-) for authenticating against a private instance.

GitHub example:

```bash
❯ irp get "https://github.com/ahmetb/kubectx"

📑 Repo     : ahmetb/kubectx
🌟 Stars    : 13295
✨ Language : Go
🔥 Title    : Faster way to switch between clusters and namespaces in kubectl

                    📦 Available Assets for kubectx
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ Asset ID ┃ Filename                           ┃ Size (MB) ┃ Downloads ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━┩
│ 1        │ kubectx_v0.9.4_linux_x86_64.tar.gz │ 1.0       │ 43811     │
└──────────┴────────────────────────────────────┴───────────┴───────────┘

                              🚀 Install: kubectx
┏━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┓
┃ Name    ┃ Selected Item                      ┃ Version ┃ Size Mb ┃ Downloads ┃
┡━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━┩
│ kubectx │ kubectx_v0.9.4_linux_x86_64.tar.gz │ v0.9.4  │ 1.0     │ 43811     │
└─────────┴────────────────────────────────────┴─────────┴─────────┴───────────┘
Install selected tool? [Y/n/ Asset ID]: y
 INFO     Downloaded: 'kubectx_v0.9.4_linux_x86_64.tar.gz' at /tmp/dn_kubectx_ph6i7dmk                                                               utils.py:159
 INFO     install /tmp/dn_kubectx_ph6i7dmk/kubectx /home/noobi/bin/kubectx                                                                  core.py:132
 INFO     Installed: kubectx
```

```
# checking if kubectx is installed
❯ which kubectx
/home/noobi/bin/kubectx

❯ kubectx --version
0.9.4
```

##### Install as system package (deb/rpm/appimage) 📦

If the release asset files provide a package file for your system, you can install tools as a system package (deb/rpm/appimage) instead of a standalone binary by using the `--pkg` flag.

This is useful for tools that provide `.deb`, `.rpm` or `appimage` releases that might need other system package dependencies to work.

```bash
# Example installation of RedisInsight, a dashboard to manage Redis
❯ irp get https://github.com/redis/RedisInsight --pkg
```

#### Install tool via mise registry 🧩

Some tools (like Terraform, Packer, etc.) don't publish platform-specific binaries on GitHub releases — they host their own download URLs instead. For these tools, `irp` can resolve the correct download URL via the [mise](https://mise.jdx.dev/) / [aqua](https://aquaproj.github.io/) registry using the `mise@` prefix.

```bash
# Usage: irp get mise@<tool-name>
❯ irp get mise@terraform

# Install a specific version (inline or via --tag)
❯ irp get mise@terraform:v1.12.0
❯ irp get mise@terraform -t v1.12.0
```

```
                     Install terraform (via mise/aqua)
┏━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Tool      ┃ Version  ┃ File                     ┃ URL                              ┃
┡━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ terraform │ v1.12.0  │ terraform_1.12.0_linu... │ https://releases.hashicorp.c...  │
└───────────┴──────────┴──────────────────────────┴──────────────────────────────────┘
Install selected tool? [Y/n]: y
```

Tools installed via `mise@` are also tracked by `irp ls` and upgraded with `irp upgrade` just like GitHub/GitLab tools.

> **Note:** The mise provider currently only supports tools with **HTTP-based** download URLs in the aqua registry. Tools that use `github_release` type assets should be installed directly via their GitHub URL (`irp get <github-url>`) instead.

#### Install Docker image as a CLI tool 🐳

`irp` can wrap any Docker image as a local CLI tool using the `docker@` prefix. It pulls the image, detects its entrypoint, and writes an executable wrapper script to `~/bin/<toolname>` that proxies all invocations through `docker run`.

```bash
# Usage: irp get docker@<image>[:<tag>]
❯ irp get docker@hashicorp/terraform

# Install a specific tag (inline or via --tag)
❯ irp get docker@hashicorp/terraform:1.7.0
❯ irp get docker@hashicorp/terraform -t 1.7.0

# Custom tool name
❯ irp get docker@mcr.microsoft.com/azure-cli -n az

# Pass extra docker run options (e.g. volume mounts, env vars)
❯ irp get docker@alpine:latest -n alpine --docker-opts "-v $HOME/data:/data"
```

```
         Install terraform (via Docker)
┏━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ Tool      ┃ Image                 ┃ Tag    ┃
┡━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ terraform │ hashicorp/terraform   │ latest │
└───────────┴───────────────────────┴────────┘
Install selected tool? [Y/n]: y
```

- **Latest tags** (`latest`) are checked for updates via digest comparison during `irp upgrade` — only re-pulled when the remote image has changed.
- **Pinned tags** (e.g. `1.7.0`) are held from auto-upgrade; use `irp upgrade --force` to re-pull.
- The wrapper mounts the current directory into the container at `/tmp/cmd`, so the tool sees your local files.
- **Extra Docker options (`--docker-opts`)**: You can pass additional flags to `docker run` (e.g. `-v` volume mounts or `-e` environment variables) via `--docker-opts`.
  - The value is inserted into the `/bin/sh` wrapper as-is, so it's raw shell (paths with spaces must be quoted).
  - The options are persisted in state and reused on `irp upgrade`.
  - Re-running `irp get` without `--docker-opts` preserves the previously saved options. To clear them, pass an explicit empty string (`--docker-opts ""`).

### Download and track release assets

When `irp get` selects an archive (such as `.tar.gz`, `.zip`, or `.tar.xz`),
choose how to use it before downloading:

```text
Selected asset is an archive:
  1. Install its executable
  2. Keep archive as a tracked download
Archive action (1/2/n) [1]:
```

Both choices show the resolved tag, selected file, and destination for final
confirmation. Choosing 2 preserves the archive without extracting or installing
it, and tracks it as `<repository-name>-download`. The choice applies to the
final selected Asset ID, including when you override IR's suggested asset.
Standalone executables and native packages retain their existing flow.
`irp get -y` keeps the existing executable installation behavior without asking
for an archive action. Keeping an archive requires the interactive choice above.
Upgrades reuse the recorded installation/download method.

For example, keep an archive containing skills, documentation, or data by running:

```sh
irp get https://github.com/owner/project
# Or select an archive explicitly:
irp get https://github.com/owner/project --file skills.zip
# Optionally select a specific release:
irp get https://github.com/owner/project --tag v1.2.0 --file skills.zip
```

Choose an archive Asset ID (or accept IR's suggestion), choose **2**, then review
and confirm the download. Omitting `--tag` resolves the latest release, honoring
prerelease configuration. An explicit tag holds updates, as with executable
installations. GitHub's automatically generated source archives are not included.

Kept archives use the directory set by `irp config --path` (or `~/bin` if unset).
Upgrades reuse their recorded directory even if the configuration changes.
To relocate an existing tracked download, remove it and download it again.
Enter `n` at asset selection, the archive choice, or final confirmation to cancel
before writing files.

Downloads are recorded in the existing `state.json` under the management name
`<repository-name>-download`, separately from an executable installation:

```sh
irp ls
irp info project-download
irp upgrade project-download
irp rm project-download
# Allow upgrades after downloading with an explicit --tag:
irp hold --unset project-download
```

Upgrades reuse the saved directory and selected filename after the usual upgrade
confirmation; they do not prompt for the file again. If that filename disappears
in a later release, the update fails without advancing the recorded version. Download
failures leave the previous files and recorded version intact. Files are staged
before being moved into place; unrelated existing files are never overwritten.
When filenames change across versions, previous files are retained and tracked.
`irp rm` removes tracked files, preserving the directory and unrelated contents.
Use `irp ls --json` to inspect download paths and file lists.

When kept as downloads, archives remain untouched: IR does not extract them,
set up symlinks, or install skills into an application. Installing application
bundles, sibling libraries/assets, or multiple entry points remains unsupported.
The archive choice works with GitHub, GitLab, Codeberg, and the supported
self-hosted Git repository providers; it does not apply to mise or Docker.

### Install specific release asset from GitHub, GitLab, or Codeberg releases 🔦

In rare cases where InstallReleasePlus does not automatically find the correct release file for your system, you can manually specify the release file name. There are two ways to do this:

##### Method 1: Interactive Selection (Recommended)

During the installation prompt, review the available release assets and type the asset ID you want to install:

```bash
❯ irp get https://github.com/ekzhang/bore

📑 Repo     : ekzhang/bore
🌟 Stars    : 8234
✨ Language : Rust
🔥 Title    : A simple CLI tool for making tunnels to localhost

                    📦 Available Assets for bore
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ Asset ID ┃ Filename                                        ┃ Size (MB) ┃ Downloads ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━┩
│ 1        │ bore-v0.4.0-x86_64-unknown-linux-musl.tar.gz    │ 1.2       │ 1523      │
│ 2        │ bore-v0.4.0-x86_64-unknown-linux-gnu.rpm        │ 1.3       │ 845       │
│ 3        │ bore-v0.4.0-aarch64-unknown-linux-musl.deb      │ 1.1       │ 234       │
│ 4        │ bore-v0.4.0-x86_64-apple-darwin.dmg             │ 1.2       │ 456       │
│ 5        │ bore-v0.4.0-x86_64-apple-darwin.tar.gz          │ 1.2       │ 1523      │
└──────────┴─────────────────────────────────────────────────┴───────────┴───────────┘

                              🚀 Install: bore
┏━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┓
┃ Name ┃ Selected Item                            ┃ Version ┃ Size Mb ┃ Downloads ┃
┡━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━┩
│ bore │ bore-v0.4.0-x86_64-unknown-linux-musl... │ v0.4.0  │ 1.2     │ 1523      │
└──────┴──────────────────────────────────────────┴─────────┴─────────┴───────────┘

Path: /home/noobi/bin
Install selected tool? [Y/n/ Asset ID]: 3
```

The tool will automatically parse the selected filename into keywords and store them for future upgrades.

##### Method 2: Command-line Flag

You can also specify the release file name directly using the `-f` / `--file` flag:

```bash
❯ irp get [GITHUB-URL or GITLAB-URL or CODEBERG-URL] -f [release asset filename]
```

Example: Installing the bore tool from GitHub with the release file name `bore-v0.4.0-arm-unknown-linux-musleabi.tar.gz`. Here, the keywords generated are: `bore, v0.4.0, arm, linux, musleabi`

```bash
❯ irp get https://github.com/ekzhang/bore -f bore-v0.4.0-arm-unknown-linux-musleabi.tar.gz
```

**How it works:**
- The tool parses the release file name into keywords (removing version numbers and file extensions)
- These keywords are stored in the state file to match the correct release file during future tool upgrades
- This ensures consistent upgrades to the same release variant

> Note: If `InstallReleasePlus` fails to identify the correct release package for your system, please raise a GitHub issue to help improve the tool.

#### List installed tools 📋

```bash
❯ irp ls

                       Installed tools
┏━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Name      ┃ Version ┃ Url                                  ┃
┡━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ terrascan │ v1.15.2 │ https://github.com/tenable/terrascan │
│ gron      │ v0.7.1  │ https://github.com/tomnomnom/gron    │
│ kubectx   │ v0.9.4  │ https://github.com/ahmetb/kubectx    │
└───────────┴─────────┴──────────────────────────────────────┘
```

#### Show info about an installed tool ℹ️

```bash
❯ irp info kubectx

                Info: kubectx
┏━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Name    ┃ Description                            ┃ Url                              ┃
┡━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ kubectx │ Faster way to switch between clusters  │ https://github.com/ahmetb/kubectx │
│         │ and namespaces in kubectl              │                                  │
└─────────┴────────────────────────────────────────┴──────────────────────────────────┘
```

#### Remove installed release ❌

```bash
# Remove installed release

❯ irp rm gron

INFO     Removed: gron
```

#### Update all previously installed tools to the latest version 🕶

```bash
❯ irp upgrade

Fetching: https://github.com/tenable/terrascan#terrascan
Fetching: https://github.com/ahmetb/kubectx#kubectx

Following tools will be upgraded:

terrascan

Upgrade these tools (Y/n): y

Updating: terrascan, v1.15.0 => v1.15.2
 INFO     Downloaded: 'terrascan_1.15.2_Linux_x86_64.tar.gz' at /tmp/dn_terrascan_0as71a6v
 INFO     install /tmp/dn_terrascan_0as71a6v/terrascan ~/bin/terrascan
 INFO     Installed: terrascan

Progress... ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:00
```

##### Update a specific installed tool

To upgrade only one installed tool, provide its name:

```bash
❯ irp upgrade zen
```

##### Update installed system packages 📦

If you have tools installed as packages (deb/rpm/appimage), `irp upgrade` will inform you if updates are available but will **not** install them. To upgrade packages, run:

```bash
❯ irp upgrade --pkg
```

This will prompt for sudo permissions to upgrade the system packages.

#### Pull state templates for installing tools 📄

You can push your state to somewhere like GitHub and use it on any other device to sync the tools installed via irp.

```bash
❯ irp pull --url https://raw.githubusercontent.com/Rishang/dotFiles/main/templates/install-release/state.json
```

#### Hold Update to specific installed tool ✋

In case you want to hold an update for a specific tool, you can use the `hold {tool-name}` command which will pause updates for that tool.

Example: Keep tool named [k9s](https://github.com/derailed/k9s) update on hold:

```bash
❯ irp hold k9s
 INFO     Update on hold for, k9s to True
```

You can list tools on hold updates by using the `ls --hold` command:

```bash
❯ irp ls --hold
             Installed tools kept on hold
┏━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Name ┃ Version ┃ Url                               ┃
┡━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ k9s  │ v0.26.7 │ https://github.com/derailed/k9s   │
└──────┴─────────┴───────────────────────────────────┘
```

In case you want to remove the update hold for a specific tool, you can use the `hold --unset {tool-name}` command:

```
❯ irp hold --unset k9s
 INFO     Update on hold for, k9s to False
```

#### Configure tool installation path

```bash
❯ irp config --path ~/.local/bin

INFO   Updated path to:  ~/.local/bin
INFO   Done
```

#### Configure updates for pre-release versions 🔌

This is useful when you want to install pre-release versions of tools like beta or alpha releases. By default, it is set to `False`, in which case it will only check for the latest stable release.

```bash
❯ irp config --pre-release
```

#### Configure provider tokens for higher rate limits 🔑

> For GitHub:

```bash
❯ irp config --github-token [your github token]

INFO: Updated GitHub token
INFO: Done.
```

> For GitLab:

```bash
❯ irp config --gitlab-token [your gitlab token]

INFO: Updated GitLab token for gitlab.com
INFO: Done.
```

> For Codeberg/Forgejo:

Use a Codeberg access token when authenticated API access or a higher rate limit is needed.

```bash
❯ irp config --codeberg-token [your codeberg token]

INFO: Updated Codeberg/Forgejo token for codeberg.org
INFO: Done.
```

> For self-hosted instances:

GitLab and Forgejo tokens are stored per host, so a private instance's token is never sent to the public one. Add `--host` to write the token for a specific instance; without it, `--gitlab-token` targets `gitlab.com` and `--codeberg-token` targets `codeberg.org`.

```bash
❯ irp config --gitlab-token [your token] --host gitlab.example.com

INFO: Updated GitLab token for gitlab.example.com
INFO: Done.
```

Hosts are registered automatically the first time you install from them, so `irp config --host` only needs a token when the instance requires authentication.

> Upgrading from an earlier version:

Older versions stored a single token string per provider. On first run, `irp` converts it to the per-host form and keeps your existing token under `gitlab.com` / `codeberg.org` — no action needed, you will just see a one-time warning:

```text
WARNING  Config format changed: 'gitlab_token' is now a per-host map; migrated your token to host 'gitlab.com'.
```

## Merging upstream changes

Keep the internal `InstallRelease` package and existing config/state format when
possible so upstream changes can be merged without renaming imports. After
renaming your GitHub repository, update `origin` and add the upstream remote once:

```bash
git remote set-url origin git@github.com:varung2/InstallReleasePlus.git
git remote add upstream https://github.com/Rishang/install-release.git
```

After committing your local changes, bring in upstream commits with:

```bash
git fetch upstream
git merge upstream/main
./install.sh
```

The installer rebuilds automatically when merged changes affect the build inputs.
