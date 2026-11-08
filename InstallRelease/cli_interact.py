import json
import os
import threading

from rich.console import Console
from rich.markup import escape

from InstallRelease.config import (  # noqa: F401
    cache,
    cache_config,
    config,
    dest,
    pre_release_enabled,
)
from InstallRelease.download import download_release
from InstallRelease.pkgs.app_images import AppImage
from InstallRelease.pkgs.main import PackageInstaller
from InstallRelease.providers.base import (
    PROVIDER_STATE_KEY_PREFIXES,
    InteractProvider,
    output_directory,
)
from InstallRelease.providers.docker.main import (
    DockerInteractProvider,
)
from InstallRelease.providers.docker.main import (
    needs_update as docker_needs_update,
)
from InstallRelease.providers.git.main import GitInteractProvider, get_repo_info
from InstallRelease.providers.git.schemas import Release, TypeState
from InstallRelease.providers.mise.main import MiseInteractProvider
from InstallRelease.schemas import irKey
from InstallRelease.utils import (
    PackageVersion,
    is_none,
    logger,
    pprint,
    requests_session,
    sh,
    show_table,
    threads,
)

console = Console(width=40)
install_release_version = PackageVersion("InstallReleasePlus")


def is_package(state, k):
    """Check if a tool was installed as an OS package (deb/rpm/appimage)."""
    return state[k].is_package


# ------- cli ----------


def state_info() -> None:
    """Log current cache and install paths for debugging."""
    logger.debug(cache.state_file)
    logger.debug(cache_config.state_file)
    logger.debug(dest)


def get(
    url: str,
    version: str = "",
    asset_file: str = "",
    local: bool = True,
    prompt: bool = False,
    name: str | None = None,
    pkg: bool = False,
    hold: bool = False,
    docker_opts: str | None = None,
    force: bool = False,
    output: str = "",
) -> None:
    """Resolve URL to provider and install the tool."""
    state_info()
    if output and pkg:
        raise ValueError(
            "--output is not supported for native packages; their package manager controls installation paths."
        )
    if output:
        output = output_directory(output, dest)

    # User-facing prefixes (typed by the user)
    # State-key prefixes (used internally by upgrade/pull_state)
    _mise_user, _mise = "mise@", PROVIDER_STATE_KEY_PREFIXES["mise"]
    _docker_user, _docker = "docker@", PROVIDER_STATE_KEY_PREFIXES["docker"]
    if docker_opts and not (url.startswith(_docker_user) or url.startswith(_docker)):
        logger.warning(
            "--docker-opts is only supported for docker images and will be ignored."
        )

    if url.startswith(_mise_user):
        provider: InteractProvider = MiseInteractProvider(url[len(_mise_user) :])
    elif url.startswith(_mise):
        provider = MiseInteractProvider(url[len(_mise) :])
    elif url.startswith(_docker_user):
        provider = DockerInteractProvider(url[len(_docker_user) :])
    elif url.startswith(_docker):
        provider = DockerInteractProvider(url[len(_docker) :])
    elif url.startswith(("gitlab@", "forgejo@")):
        # Self-hosted: keep the full path, GitLab subgroups need the depth
        provider = GitInteractProvider(get_repo_info(url), package_mode=pkg)
    else:
        url = "/".join(url.split("/")[:5])
        provider = GitInteractProvider(get_repo_info(url), package_mode=pkg)
    provider.get(
        version=version,
        asset_file=asset_file,
        local=local,
        prompt=prompt,
        name=name,
        hold=hold,
        docker_opts=docker_opts,
        force=force,
        output=output,
    )


def _matching_keys(state: TypeState, name: str | None) -> list[str]:
    if name is None:
        return list(state)
    if name in state:
        return [name]
    matches = [key for key in state if irKey.parse(key).name == name]
    if len(matches) > 1:
        raise ValueError(
            f"Ambiguous tool name '{name}'; use a full state key: " + ", ".join(matches)
        )
    return matches


def upgrade(
    force: bool = False,
    skip_prompt: bool = False,
    packages_only: bool = False,
    name: str | None = None,
) -> None:
    """Check all installed tools for newer versions and upgrade them.

    Phase 1: Concurrently fetch latest versions for all tools (git + mise).
    Phase 2: Show pending upgrades, prompt user, then install sequentially.
    """
    state_info()

    state: TypeState = cache.state
    keys = _matching_keys(state, name)

    # Collect upgrade candidates: full state key -> (url, new_version, is_package)
    upgrades: dict[str, tuple[str, str, bool]] = {}
    pkg_upgrades: set[str] = set()  # names only, for notification
    _lock = threading.Lock()
    _mise = PROVIDER_STATE_KEY_PREFIXES["mise"]
    _docker = PROVIDER_STATE_KEY_PREFIXES["docker"]

    def task(k: str) -> None:
        """Fetch latest version for one tool and bucket it if newer."""
        i = irKey.parse(k)
        release = state[k]

        if packages_only and not release.is_package:
            return

        if release.hold_update:
            return

        # ── mise tools ──────────────────────────────────────────────────────
        if i.url.startswith(_mise):
            toolname = i.url[len(_mise) :]
            pprint(f"Fetching: [blue]mise@{toolname}[/blue]")
            versions = MiseInteractProvider(toolname).resolve()
            if versions and (force or versions[0] != state[k].tag_name):
                with _lock:
                    upgrades[k] = (i.url, versions[0], False)
            return

        # ── docker tools ─────────────────────────────────────────────────────
        if i.url.startswith(_docker):
            image_ref = i.url[len(_docker) :]
            tag = state[k].tag_name
            cli_image = (
                image_ref[len("library/") :]
                if image_ref.startswith("library/")
                else image_ref
            )
            pprint(f"Checking: [blue]docker@{cli_image}:{tag}[/blue]")
            if docker_needs_update(image_ref, tag, force=force):
                with _lock:
                    upgrades[k] = (i.url, tag, False)
            return

        # ── git tools ───────────────────────────────────────────────────────
        repo = get_repo_info(i.url)
        pprint(f"Fetching: {k}")
        releases = repo.release(pre_release=pre_release_enabled())

        if not releases:
            logger.warning(f"No releases found for: {k}")
            return

        if releases[0].published_dt() > state[k].published_dt() or force:
            with _lock:
                if is_package(state, k) and not packages_only and not name:
                    pkg_upgrades.add(i.name)
                else:
                    upgrades[k] = (
                        repo.repo_url,
                        releases[0].tag_name,
                        is_package(state, k),
                    )

    # Phase 1: concurrent version checks
    threads(task, data=keys, max_workers=20, return_result=False)

    # Notify about package upgrades when not in --pkg mode
    if not packages_only and pkg_upgrades:
        pprint("\n[bold cyan]Following package can be upgraded.[/]\n")
        pprint("[bold indian_red]" + " ".join(pkg_upgrades))
        pprint(
            "\n[bold white]To upgrade packages, run: [green]irp upgrade --pkg[/green][/]\n"
        )

    # Phase 2: prompt and install pending upgrades
    if upgrades:
        pprint("\n[bold magenta]Following tool will get upgraded.\n")
        console.print("[bold yellow]" + " ".join(upgrades))
        pprint("\n[bold blue]Upgrade these tools, (Y/n):", end=" ")

        if not skip_prompt:
            r = input()
            if r.lower() != "y":
                return

        if packages_only or (name and any(v[2] for v in upgrades.values())):
            pprint("\n\n[bold]Need sudo access for installing packages...[/]")
            result = sh("sudo -v", interactive=True)
            if result.returncode != 0:
                pprint("[bold red]Failed to acquire sudo. Aborting.[/]")
                return
            pprint()
    else:
        pprint("[bold green]All tools are onto latest version")
        return

    total = len(upgrades)
    for idx, k in enumerate(upgrades, 1):
        name = irKey.parse(k).name
        url, new_version, pkg_mode = upgrades[k]
        docker_opts = state[k].docker_opts
        pct = int(idx * 100 / total)
        pprint(
            f"[bold yellow]({pct}%) Updating: {name}, {state[k].tag_name} => {new_version}[/]"
        )
        if state[k].install_method == "download":
            download_release(
                url,
                version=new_version,
                asset_file=state[k].download_file or "",
                output=state[k].download_dir or "",
                hold=bool(state[k].hold_update),
                prompt=False,
                all_assets=state[k].download_file is None,
            )
            continue
        get(
            url,
            version=new_version,
            prompt=False,
            name=name,
            pkg=pkg_mode,
            docker_opts=docker_opts,
            force=force,
            output=os.path.dirname(state[k].install_path)
            if not pkg_mode and state[k].install_path
            else "",
        )


def show_state():
    """Print the raw state file contents for debugging."""
    state_info()
    if os.path.isfile(cache.state_file):
        with open(cache.state_file) as f:
            print(f.read())


def list_install(
    state: TypeState | None = None,
    title: str = "Installed tools",
    hold_update: bool = False,
    as_json: bool = False,
) -> None:
    """Render a table of installed tools, optionally filtering to held ones only."""
    if state is None:
        state_info()
        state = cache.state

    rows = []
    for key in state:
        release = state[key]
        if hold_update and not release.hold_update:
            continue
        name = irKey.parse(key).name
        path_inferred = False
        if release.install_method == "download":
            install_path = release.download_dir
        elif release.install_path:
            install_path = release.install_path
        elif release.is_package and release.package_type == "AppImage":
            install_path = str(AppImage(release.package_name or name).appimage_path)
            path_inferred = True
        elif release.is_package:
            install_path = None
        else:
            # Older state did not record destinations. Do not present the
            # current configured directory as a known historical location.
            install_path = os.path.abspath(os.path.join(dest, name))
            path_inferred = True
        rows.append(
            {
                "name": name,
                "version": release.tag_name,
                "type": "download"
                if release.install_method == "download"
                else (release.package_type if release.is_package else "binary"),
                "hold": bool(release.hold_update),
                "url": release.url,
                "description": release.description or "",
                "download_dir": release.download_dir,
                "download_files": release.download_files,
                "install_path": install_path,
                "path_inferred": path_inferred,
            }
        )

    if as_json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return

    dim = "[dim]" if hold_update else ""
    table = [
        {
            "Name": r["name"],
            "Version": f"{dim}{r['version']}",
            "Type": f"[cyan]{r['type']}" if r["type"] != "binary" else r["type"],
            "Hold": "[yellow]yes" if r["hold"] else "",
            "Install path": escape(
                r["install_path"]
                or ("System package manager" if r["type"] != "download" else "Unknown")
            )
            + (" (inferred)" if r["path_inferred"] else ""),
            "Url": f"{dim}{r['url']}",
            "Description": f"[dim yellow]{r['description']}",
        }
        for r in rows
    ]
    name_width = max((len(r["name"]) for r in rows), default=4)
    show_table(
        table,
        title=f"{title} kept on hold" if hold_update else title,
        ignore_keys=["Hold"] if hold_update else None,
        expand=True,
        column_opts={
            # High-priority columns keep their natural width; Url and
            # Description absorb leftover space and truncate first.
            "Name": {"min_width": min(name_width, 30)},
            "Version": {"min_width": 7},
            "Install path": {"no_wrap": False, "overflow": "fold", "ratio": 3},
            "Url": {"overflow": "ellipsis", "ratio": 2},
            "Description": {"overflow": "ellipsis", "ratio": 3},
        },
    )


def get_info(name: str) -> None:
    """Print stored info (name, description, url) for an installed tool."""
    state_info()
    state: TypeState = cache.state

    for key in state:
        i = irKey.parse(key)
        if i.name == name:
            release = state[key]
            show_table(
                [
                    {
                        "Name": i.name,
                        "Description": release.description or "N/A",
                        "Url": release.url,
                    }
                ],
                title=f"Info: {name}",
                no_wrap=False,
            )
            if release.install_method == "download":
                console.print(
                    "Download directory:",
                    release.download_dir,
                    markup=False,
                    soft_wrap=True,
                )
                console.print("Downloaded files:", markup=False)
                for file in release.download_files:
                    console.print(file, markup=False, soft_wrap=True)
            return

    pprint(f"[red]Tool not found: {name}")
    exit(1)


def remove(name: str) -> None:
    """Uninstall a tool by name — removes the binary/package and clears state."""
    state_info()
    state: TypeState = cache.state
    pop_key = ""

    # Find the tool in state, uninstall its binary or package
    for key in _matching_keys(state, name):
        i = irKey.parse(key)
        pop_key = key
        name = i.name
        release = state[key]

        if release.install_method == "download":
            try:
                for file in release.download_files:
                    if os.path.lexists(file):
                        os.remove(file)
            except OSError as exc:
                logger.error(f"Failed to remove download: {exc}")
                return
        elif is_package(state, key):
            if not release.package_type or release.package_type == "binary":
                logger.warning(f"{name} was not installed as a package")
            else:
                pkg_name = release.package_name or name
                if pkg_name != name:
                    logger.debug(
                        f"Using actual package name '{pkg_name}' instead of '{name}'"
                    )
                PackageInstaller(
                    pkg_name, package_type=release.package_type
                ).uninstall()
        else:
            try:
                tool_path = release.install_path or f"{dest}/{name}"
                if os.path.exists(tool_path):
                    os.remove(tool_path)
                    logger.debug(f"Removed file: {tool_path}")
            except OSError as e:
                logger.error(f"Failed to remove file: {e}")
        break

    # Purge from state after successful uninstall
    if pop_key:
        try:
            del state[pop_key]
            cache.save()
            logger.info(f"Removed: {name}")
        except Exception as e:
            logger.error(f"Failed to update state: {e}")
    else:
        logger.warning(f"Tool not found: {name}")


def hold(name: str, hold_update: bool) -> None:
    """Toggle the hold_update flag for a tool, skipping it during upgrades."""
    state_info()
    state: TypeState = cache.state

    for _k in state:
        key = irKey.parse(_k)
        if key.name == name:
            state[_k].hold_update = hold_update
            logger.info(f"Update on hold for, {name} to {hold_update}")
            break
    cache.save()


def pull_state(url: str = "", override: bool = False) -> None:
    """Import tools from a remote state URL, installing any that are new or outdated."""
    logger.debug(url)
    if is_none(url):
        return None

    # Fetch remote state and parse into Release objects
    r: dict = requests_session.get(url=url).json()
    data: dict[str, Release] = {k: Release(**r[k]) for k in r}
    state: TypeState = cache.state

    # Filter to tools that need installing (new or version mismatch with override)
    temp: dict[str, Release] = {}
    for key in data:
        try:
            i = irKey.parse(key)
        except Exception:
            logger.warning(f"Invalid input: {key}")
            continue

        if key in state and (state[key].tag_name == data[key].tag_name or not override):
            logger.debug(f"Skipping: {key}")
            continue
        temp[key] = data[key]

    logger.debug(temp)

    if not temp:
        return None

    list_install(state=temp, title="Tools to be installed")
    pprint("\n[bold magenta]Following tool will get Installed.\n")
    pprint("[bold blue]Install these tools, (Y/n):", end=" ")

    _i = input()
    if _i.lower() != "y":
        return None

    for key in temp:
        i = irKey.parse(key)
        if temp[key].install_method == "download":
            # Imported absolute paths belong to another machine. Use local config.
            download_release(
                i.url,
                version=temp[key].tag_name,
                asset_file=temp[key].download_file or "",
                hold=bool(temp[key].hold_update),
                prompt=False,
                all_assets=temp[key].download_file is None,
            )
            continue
        get(i.url, version=temp[key].tag_name, prompt=False, name=i.name)
