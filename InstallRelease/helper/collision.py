"""Compare binary destinations before providers download or replace anything."""

from __future__ import annotations

import os
from collections.abc import Callable

import typer
from rich.markup import escape

from InstallRelease.config import cache
from InstallRelease.providers.git.schemas import Release
from InstallRelease.schemas import irKey
from InstallRelease.utils import show_table


def binary_path(key: str, release: Release, directory: str) -> str | None:
    if release.install_method != "binary":
        return None
    return os.path.realpath(
        release.install_path or os.path.join(directory, irKey.parse(key).name)
    )


def _details(key: str, release: Release, path: str) -> dict[str, str]:
    assets = release.assets
    return {
        "Name": irKey.parse(key).name,
        "Install path": path,
        "Source repo": irKey.parse(key).url,
        "Release source": release.url,
        "Tag": release.tag_name,
        "Install method": release.install_method or "binary",
        "Asset": "\n".join(a.name for a in assets) or "—",
        "Asset URL": "\n".join(a.browser_download_url for a in assets) or "—",
        "Asset size (bytes)": ", ".join(str(a.size) for a in assets) or "—",
        "Asset ID": ", ".join(str(a.id) for a in assets) or "—",
        "Asset updated": ", ".join(a.updated_at or "Unknown" for a in assets) or "—",
        "Prerelease": str(bool(release.prerelease)),
        "Updates held": str(bool(release.hold_update)),
        "Docker options": release.docker_opts or "—",
    }


def confirm_binary_install(
    key: str,
    release: Release,
    *,
    prompt: bool,
    force: bool = False,
    same_content: Callable[[], bool] | None = None,
) -> bool:
    """Return False for a declined collision or an already installed release.

    Explicit noninteractive approval is honoured for replacements. Identical
    releases still stop, unless an upgrade explicitly requests a forced refresh.
    """
    path = release.install_path
    if not path:
        raise ValueError("A binary installation must specify its destination")
    path = os.path.abspath(path)
    name = irKey.parse(key).name
    directory = os.path.dirname(path)
    cached = cache.state.get(key)
    if cached and cached.install_method == "binary" and cached.install_path:
        previous_path = os.path.realpath(cached.install_path)
        if previous_path != os.path.realpath(path):
            raise ValueError(
                f"This binary is tracked at {cached.install_path}; use --output "
                f"with {os.path.dirname(cached.install_path)}, or remove it before relocating it"
            )
    if os.path.islink(path) or (os.path.lexists(path) and not os.path.isfile(path)):
        raise ValueError(f"Refusing to overwrite a symlink or non-regular file: {path}")

    conflicts = []
    for old_key, old in cache.state.items():
        old_path = binary_path(old_key, old, directory)
        if old_path and (old_path == path or irKey.parse(old_key).name == name):
            conflicts.append((old_key, old, old_path))
        elif old.install_method == "download" and path in old.download_files:
            raise ValueError(
                f"Destination belongs to a tracked download; remove it first: {path}"
            )

    proposed = _details(key, release, path)
    existing = [_details(k, r, p) for k, r, p in conflicts]
    # A same-name record in another directory does not own an existing target.
    if os.path.lexists(path) and not any(p == path for _, _, p in conflicts):
        unknown = dict.fromkeys(proposed, "Unknown (untracked file)")
        unknown.update({"Name": name, "Install path": path})
        existing.append(unknown)
    if not existing:
        return True

    if (
        not force
        and len(existing) == 1
        and existing[0] == proposed
        and os.path.isfile(path)
        and (same_content is None or same_content())
    ):
        typer.echo(
            f"{name} {release.tag_name} already exists at {path}; nothing installed."
        )
        return False

    for index, old in enumerate(existing, 1):
        show_table(
            [
                {
                    "Field": field,
                    "Existing": escape(old[field]),
                    "Proposed": escape(value),
                    "Changed": "yes" if old[field] != value else "",
                }
                for field, value in proposed.items()
            ],
            title=f"Installation collision ({index}/{len(existing)})",
            no_wrap=False,
            column_opts={
                "Existing": {"overflow": "fold"},
                "Proposed": {"overflow": "fold"},
            },
        )
    if prompt and not typer.confirm(
        "Continue installation and overwrite the existing package?", default=False
    ):
        typer.echo("Installation cancelled; existing files and tracking are unchanged.")
        return False
    if not prompt:
        typer.echo("Overwrite approved by noninteractive confirmation.")
    return True
