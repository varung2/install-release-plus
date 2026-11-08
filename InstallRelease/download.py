"""Tracked release-asset downloads, without extraction or installation.

Reuse Git provider release metadata and the shared state, but deliberately bypass
platform scoring and executable/package installers: assets may contain anything.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import typer

from InstallRelease.config import dest, pre_release_enabled
from InstallRelease.helper.state import load_state, save_state
from InstallRelease.providers.base import Provider
from InstallRelease.providers.git.base import RepoInfo
from InstallRelease.providers.git.schemas import Release, ReleaseAssets
from InstallRelease.utils import download, logger, show_table


def download_release(
    url: str,
    version: str = "",
    asset_file: str = "",
    output: str = "",
    hold: bool = False,
    prompt: bool = False,
    all_assets: bool = False,
) -> Release | None:
    """Refresh or restore tracked downloads from provider release metadata.

    Download records use ``<repo>-download`` as their management name. Only files
    already owned by this record may be replaced. Old version files are retained
    and tracked until removal, even when filenames change between releases.
    """
    if Provider.resolve_provider(url) not in (
        "github",
        "gitlab",
        "codeberg",
        "gitlab_self",
        "forgejo_self",
    ):
        raise ValueError("Downloads require a GitHub, GitLab, or Forgejo repository.")
    # Import the factory lazily: Git installation also uses store_release_assets.
    from InstallRelease.providers.git.main import get_repo_info

    repo = get_repo_info(url)
    releases = repo.release(tag_name=version, pre_release=pre_release_enabled())
    if not releases:
        raise ValueError(f"No releases found: {url}")
    release = releases[0]
    assets = [a for a in release.assets if not asset_file or a.name == asset_file]
    if not assets:
        raise ValueError(
            f"No uploaded release assets match {asset_file or 'this release'}"
        )

    if not asset_file and not all_assets and len(assets) > 1:
        raise ValueError(
            "Multiple release assets available; a saved filename is required"
        )

    if not all_assets:
        asset_file = assets[0].name

    return store_release_assets(
        repo,
        release,
        assets,
        output=output,
        hold=hold,
        prompt=prompt,
        asset_file=asset_file or None,
    )


def store_release_assets(
    repo: RepoInfo,
    release: Release,
    assets: list[ReleaseAssets],
    output: str = "",
    hold: bool = False,
    prompt: bool = True,
    asset_file: str | None = None,
) -> Release | None:
    """Confirm, stage, and track already resolved assets without fetching again.

    Used by the archive decision in ``irp get`` and tracked download refreshes.
    """
    release = replace(release)
    name = f"{repo.repo_name.lower()}-download"
    key = f"{repo.repo_url}#{name}"
    cached = load_state(key)
    if cached and cached.install_method != "download":
        raise ValueError(
            f"The management name {name} is already used by an installation"
        )
    directory = Path(output or dest).expanduser().resolve()
    previous_files = cached.download_files if cached else []
    if cached and Path(cached.download_dir or "") != directory:
        raise ValueError(
            f"This download is tracked in {cached.download_dir}; "
            "use --output with that directory, or remove the download before relocating it"
        )
    targets = []
    for asset in assets:
        if (
            not asset.name
            or Path(asset.name).name != asset.name
            or asset.name in (".", "..")
        ):
            raise ValueError(f"Unsafe release asset filename: {asset.name}")
        target = directory / asset.name
        if target in targets:
            raise ValueError(f"Duplicate release asset filename: {asset.name}")
        if os.path.lexists(target) and (
            str(target) not in previous_files
            or target.is_symlink()
            or not target.is_file()
        ):
            raise ValueError(f"Refusing to overwrite an unrelated file: {target}")
        targets.append(target)

    if prompt:
        show_table(
            [
                {
                    "Repository": repo.repo_url,
                    "Version": release.tag_name,
                    "Selected file": asset.name,
                    "Size (MB)": "Unknown" if asset.source_archive else asset.size_mb(),
                }
                for asset in assets
            ],
            title=f"Download: {repo.repo_name}",
        )
        typer.echo(f"Path: {directory}")
        if not typer.confirm("Download selected release asset?", default=True):
            return None

    directory.mkdir(parents=True, exist_ok=True)
    # Stage on the destination filesystem. Failed transfers leave previous files
    # and release state intact; nothing in the archive is executed or extracted.
    with TemporaryDirectory(prefix=".irp-download-", dir=directory) as temp:
        ready = Path(temp) / "ready"
        ready.mkdir()
        for asset in assets:
            with TemporaryDirectory(dir=temp) as staging_dir:
                downloaded = download(asset.browser_download_url, staging_dir)
                shutil.move(downloaded, ready / asset.name)
        backup = Path(temp) / "backup"
        backup.mkdir()
        for target in targets:
            if target.exists():
                shutil.copy2(target, backup / target.name)
        replaced = []
        try:
            for target in targets:
                os.replace(ready / target.name, target)
                replaced.append(target)
            release.name = name
            release.assets = assets
            release.install_method = "download"
            release.download_dir = str(directory)
            release.download_file = asset_file or None
            release.download_files = list(
                dict.fromkeys([*previous_files, *map(str, targets)])
            )
            release.hold_update = hold
            if repo.info:
                release.description = repo.info.description
            save_state(key, release)
        except Exception:
            for target in reversed(replaced):
                saved = backup / target.name
                if saved.exists():
                    os.replace(saved, target)
                else:
                    target.unlink(missing_ok=True)
            raise
    logger.info(f"Tracked download: {name} {release.tag_name} at {directory}")
    return release
