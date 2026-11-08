from dataclasses import replace
from unittest.mock import Mock

import pytest

from InstallRelease.config import cache
from InstallRelease.helper import collision
from InstallRelease.helper.state import save_state
from InstallRelease.providers.docker import main as docker
from InstallRelease.providers.git.schemas import Release, ReleaseAssets
from InstallRelease.providers.mise import main as mise
from InstallRelease.providers.mise.schemas import AquaAsset


@pytest.fixture
def installed(monkeypatch, tmp_path):
    path = tmp_path / "bin/tool"
    path.parent.mkdir()
    path.write_bytes(b"old executable")
    record = Release(
        url="https://github.com/alice/tool",
        name="tool",
        tag_name="v1",
        prerelease=False,
        published_at="2026-01-01T00:00:00Z",
        assets=[
            ReleaseAssets(
                name="tool.tar.gz",
                browser_download_url="https://example.invalid/v1/tool.tar.gz",
                size=42,
            )
        ],
        install_path=str(path),
    )
    key = f"{record.url}#tool"
    monkeypatch.setattr(cache, "state", {key: record})
    monkeypatch.setattr(cache, "state_file", str(tmp_path / "state.json"))
    cache.save()
    return key, record, path


@pytest.mark.parametrize(
    "change", ["tag", "repo", "asset", "path", "name", "hold", "options", "asset_id"]
)
def test_relevant_differences_require_default_no_confirmation(
    installed, monkeypatch, change
):
    key, old, path = installed
    new = replace(old)
    new_key = key
    if change == "tag":
        new.tag_name = "v2"
    elif change == "repo":
        new.url = "https://github.com/bob/tool"
        new_key = f"{new.url}#tool"
    elif change == "asset":
        new.assets = [replace(old.assets[0], name="different.tar.gz")]
    elif change == "asset_id":
        new.assets = [replace(old.assets[0], id=123)]
    elif change == "path":
        new.install_path = str(path.parent / "new/tool")
    elif change == "name":
        new_key = f"{old.url}#renamed"
    elif change == "hold":
        new.hold_update = True
    elif change == "options":
        new.docker_opts = "--network none"

    table = Mock()
    confirm = Mock(return_value=False)
    monkeypatch.setattr(collision, "show_table", table)
    monkeypatch.setattr(collision.typer, "confirm", confirm)
    assert not collision.confirm_binary_install(new_key, new, prompt=True)
    confirm.assert_called_once()
    assert confirm.call_args.kwargs["default"] is False
    rows = table.call_args.args[0]
    assert {"Name", "Install path", "Source repo", "Tag", "Asset"} <= {
        r["Field"] for r in rows
    }
    assert any(r["Changed"] == "yes" for r in rows)
    assert path.read_bytes() == b"old executable"
    assert cache.state == {key: old}


def test_identical_release_bails_without_asking(installed, monkeypatch, capsys):
    key, old, _ = installed
    monkeypatch.setattr(
        collision.typer,
        "confirm",
        lambda *a, **kw: pytest.fail("Asked about identical install"),
    )
    assert not collision.confirm_binary_install(key, replace(old), prompt=True)
    assert "already exists" in capsys.readouterr().out


def test_missing_binary_can_be_reinstalled(installed, monkeypatch):
    key, old, path = installed
    path.unlink()
    monkeypatch.setattr(collision.typer, "confirm", lambda *a, **kw: True)
    assert collision.confirm_binary_install(key, replace(old), prompt=True)


def test_approved_replacement_removes_previous_owner_only_on_save(
    installed, monkeypatch
):
    key, old, path = installed
    new = replace(old, url="https://github.com/bob/tool", tag_name="v2")
    new_key = f"{new.url}#tool"
    monkeypatch.setattr(collision.typer, "confirm", lambda *a, **kw: True)
    assert collision.confirm_binary_install(new_key, new, prompt=True)
    assert cache.state == {key: old}  # Approval alone must never alter tracking.
    save_state(new_key, new)
    assert cache.state == {new_key: new}
    cache.load()
    assert set(cache.state) == {new_key}
    assert path.read_bytes() == b"old executable"  # Provider owns file replacement.


def test_failed_save_restores_displaced_tracking(installed, monkeypatch):
    key, old, _ = installed
    before = open(cache.state_file, "rb").read()
    new = replace(old, url="https://github.com/bob/tool")

    def fail():
        raise OSError("disk full")

    monkeypatch.setattr(cache, "save", fail)
    with pytest.raises(OSError, match="disk full"):
        save_state(f"{new.url}#tool", new)
    assert cache.state == {key: old}
    assert open(cache.state_file, "rb").read() == before


@pytest.mark.parametrize("kind", ["symlink", "directory"])
def test_unsafe_destinations_are_rejected(installed, kind):
    key, record, path = installed
    path.unlink()
    if kind == "symlink":
        target = path.parent / "external"
        target.write_bytes(b"external")
        path.symlink_to(target)
    else:
        path.mkdir()
    with pytest.raises(ValueError, match="symlink or non-regular"):
        collision.confirm_binary_install(key, record, prompt=False)
    if kind == "symlink":
        assert target.read_bytes() == b"external"


@pytest.mark.parametrize("provider_name", ["mise", "docker"])
def test_other_providers_decline_before_download_or_pull(
    installed, monkeypatch, provider_name
):
    _, _, path = installed
    module = mise if provider_name == "mise" else docker
    monkeypatch.setattr(module, "dest", str(path.parent))
    if provider_name == "mise":
        provider = mise.MiseInteractProvider("tool")
        asset = AquaAsset(
            url="https://example.invalid/new.tar.gz",
            name="new.tar.gz",
            version="v2",
            fmt="tar.gz",
            owner="bob",
            repo="tool",
        )
    else:
        provider = docker.DockerInteractProvider("bob/tool:latest")
        asset = provider._image
    monkeypatch.setattr(provider, "resolve", lambda **kw: [asset])
    monkeypatch.setattr(provider, "select", lambda *a, **kw: asset)
    monkeypatch.setattr(provider, "prompt", lambda *a: "y")
    monkeypatch.setattr(
        provider,
        "install",
        lambda *a, **kw: pytest.fail("Downloaded or pulled after declining"),
    )
    monkeypatch.setattr(collision.typer, "confirm", lambda *a, **kw: False)
    provider.get(name="tool", prompt=True)
    assert path.read_bytes() == b"old executable"


def test_force_can_refresh_identical_release(installed):
    key, record, _ = installed
    assert collision.confirm_binary_install(key, record, prompt=False, force=True)


def test_same_wrapper_metadata_requires_matching_content(installed):
    key, record, _ = installed
    assert collision.confirm_binary_install(
        key, record, prompt=False, same_content=lambda: False
    )
    assert not collision.confirm_binary_install(
        key, record, prompt=False, same_content=lambda: True
    )
