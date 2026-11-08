from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from InstallRelease import cli
from InstallRelease.config import cache
from InstallRelease.providers.docker import main as docker
from InstallRelease.providers.mise import main as mise
from InstallRelease.providers.mise.schemas import AquaAsset


@pytest.mark.parametrize("provider", ["mise", "docker"])
def test_provider_writes_only_to_custom_directory(monkeypatch, tmp_path, provider):
    default = tmp_path / "default"
    output = tmp_path / "custom tools"
    monkeypatch.setattr(cache, "state", {})
    monkeypatch.setattr(cache, "state_file", str(tmp_path / "state.json"))
    module = mise if provider == "mise" else docker
    monkeypatch.setattr(module, "dest", str(default))
    if provider == "mise":
        asset = AquaAsset(
            url="https://example.invalid/tool.tar.gz",
            name="tool.tar.gz",
            version="v1",
            fmt="tar.gz",
            owner="owner",
            repo="tool",
        )
        monkeypatch.setattr(
            mise.MiseInteractProvider, "resolve", lambda *a, **kw: [asset]
        )
        monkeypatch.setattr(mise.MiseInteractProvider, "select", lambda *a, **kw: asset)

        # Exercise the real install orchestration with a local executable fixture.
        def extract(url, directory):
            import shutil

            shutil.copy2(shutil.which("true"), Path(directory) / "tool")

        monkeypatch.setattr(mise, "extract_url", extract)
        url = "mise@tool"
    else:
        monkeypatch.setattr(
            docker.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0)
        )
        monkeypatch.setattr(docker, "_get_entrypoint", lambda *a: ["/entrypoint"])
        url = "docker@owner/tool:v1"
    result = CliRunner().invoke(cli.app, ["get", url, "-o", str(output), "-y"])
    assert result.exit_code == 0, result.output
    target = output / "tool"
    assert target.is_file()
    assert not default.exists()
    saved = next(iter(cache.state.values()))
    assert saved.install_path == str(target)
    rows = CliRunner().invoke(cli.app, ["ls", "--json"])
    assert str(target) in rows.output
    result = CliRunner().invoke(cli.app, ["rm", "tool"])
    assert result.exit_code == 0, result.output
    assert not target.exists()


def test_existing_binary_cannot_silently_relocate(monkeypatch, tmp_path):
    from InstallRelease.helper.collision import confirm_binary_install
    from InstallRelease.providers.git.schemas import Release

    original = tmp_path / "old/tool"
    original.parent.mkdir()
    original.write_bytes(b"existing")
    saved = Release(
        url="repo",
        name="tool",
        tag_name="v1",
        prerelease=False,
        published_at="2026-01-01T00:00:00Z",
        assets=[],
        install_path=str(original),
    )
    monkeypatch.setattr(cache, "state", {"repo#tool": saved})
    from dataclasses import replace

    proposed = replace(saved, install_path=str(tmp_path / "new/tool"))
    with pytest.raises(ValueError, match="remove it before relocating"):
        confirm_binary_install("repo#tool", proposed, prompt=False)
    assert original.read_bytes() == b"existing"
    assert cache.state["repo#tool"] is saved


def test_output_directory_alias_keeps_one_destination_owner(monkeypatch, tmp_path):
    from dataclasses import replace

    from InstallRelease.helper.collision import confirm_binary_install
    from InstallRelease.helper.state import save_state
    from InstallRelease.providers.git.schemas import Release

    directory = tmp_path / "real"
    directory.mkdir()
    (directory / "tool").write_bytes(b"old")
    alias = tmp_path / "alias"
    alias.symlink_to(directory, target_is_directory=True)
    saved = Release(
        url="old",
        name="tool",
        tag_name="v1",
        prerelease=False,
        published_at="2026-01-01T00:00:00Z",
        assets=[],
        install_path=str(alias / "tool"),
    )
    monkeypatch.setattr(cache, "state", {"old#tool": saved})
    monkeypatch.setattr(cache, "state_file", str(tmp_path / "state.json"))
    proposed = replace(saved, url="new", install_path=str(directory / "tool"))
    assert confirm_binary_install("new#tool", proposed, prompt=False)
    save_state("new#tool", proposed)
    assert set(cache.state) == {"new#tool"}
