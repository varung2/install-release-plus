from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from InstallRelease import cli, cli_interact
from InstallRelease.config import cache
from InstallRelease.providers.git.schemas import Release


def tracked(url, **kwargs):
    return Release(
        url=url,
        name="tool-download",
        tag_name="v1",
        prerelease=False,
        published_at="2026-01-01T00:00:00Z",
        assets=[],
        install_method="download",
        download_file="tool.zip",
        **kwargs,
    )


@pytest.fixture
def two_projects(monkeypatch, tmp_path):
    state = {}
    for owner in ("alice", "bob"):
        url = f"https://github.com/{owner}/tool"
        directory = tmp_path / owner
        directory.mkdir()
        archive = directory / "tool.zip"
        archive.write_bytes(owner.encode())
        state[f"{url}#tool-download"] = tracked(
            url, download_dir=str(directory), download_files=[str(archive)]
        )
    monkeypatch.setattr(cache, "state", state)
    monkeypatch.setattr(cache, "state_file", str(tmp_path / "state.json"))
    cache.save()

    def latest(**kw):
        return [
            Release(
                url="",
                name="tool",
                tag_name="v2",
                prerelease=False,
                published_at="2026-02-01T00:00:00Z",
                assets=[],
            )
        ]

    monkeypatch.setattr(
        cli_interact,
        "get_repo_info",
        lambda url, **kwargs: SimpleNamespace(repo_url=url, release=latest),
    )
    calls = []
    monkeypatch.setattr(
        cli_interact, "download_release", lambda *args, **kw: calls.append((args, kw))
    )
    return state, calls


def test_upgrade_keeps_same_named_projects_distinct(two_projects):
    state, calls = two_projects
    cli_interact.upgrade(skip_prompt=True)
    assert {args[0] for args, kw in calls} == {r.url for r in state.values()}
    assert len(calls) == 2
    for args, kw in calls:
        saved = state[f"{args[0]}#tool-download"]
        assert kw["output"] == saved.download_dir
        assert kw["asset_file"] == "tool.zip"


@pytest.mark.parametrize("command", ["upgrade", "rm"])
def test_ambiguous_name_rejected_without_changes(two_projects, command):
    state, calls = two_projects
    before = {key: Path(r.download_files[0]).read_bytes() for key, r in state.items()}
    result = CliRunner().invoke(cli.app, [command, "tool-download"])
    assert result.exit_code == 1
    assert not calls
    assert set(state) == set(before)
    for key, data in before.items():
        with open(state[key].download_files[0], "rb") as f:
            assert f.read() == data


def test_full_key_selects_one_project_for_upgrade_and_removal(two_projects):
    state, calls = two_projects
    key = next(iter(state))
    cli_interact.upgrade(skip_prompt=True, name=key)
    assert len(calls) == 1 and calls[0][0][0] == state[key].url
    cli_interact.remove(key)
    assert key not in state
    assert len(state) == 1


@pytest.mark.parametrize("force", [False, True])
def test_held_downloads_do_not_fetch_even_when_forced(two_projects, monkeypatch, force):
    state, calls = two_projects
    for saved in state.values():
        saved.hold_update = True
    monkeypatch.setattr(
        cli_interact,
        "get_repo_info",
        lambda url, **kwargs: pytest.fail("Fetched a held download"),
    )
    cli_interact.upgrade(skip_prompt=True, force=force)
    assert not calls


def test_current_downloads_leave_files_and_state_unchanged(two_projects, monkeypatch):
    state, calls = two_projects
    before = Path(cache.state_file).read_bytes()
    monkeypatch.setattr(
        cli_interact,
        "get_repo_info",
        lambda url, **kwargs: SimpleNamespace(repo_url=url, release=lambda **kw: [tracked(url)]),
    )
    cli_interact.upgrade(skip_prompt=True)
    assert not calls
    assert Path(cache.state_file).read_bytes() == before
    assert all(r.tag_name == "v1" for r in state.values())


def test_package_only_upgrade_skips_downloads(two_projects, monkeypatch):
    _, calls = two_projects
    monkeypatch.setattr(
        cli_interact, "get_repo_info", lambda url, **kwargs: pytest.fail("Fetched non-package")
    )
    cli_interact.upgrade(skip_prompt=True, packages_only=True)
    assert not calls
