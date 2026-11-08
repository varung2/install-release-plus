import json

from typer.testing import CliRunner

from InstallRelease import cli, cli_interact
from InstallRelease.config import cache
from InstallRelease.providers.git.schemas import Release


def release(url, **kwargs):
    return Release(
        url=url,
        name="tool",
        tag_name="v1",
        prerelease=False,
        published_at="2026-01-01T00:00:00Z",
        assets=[],
        **kwargs,
    )


def test_list_keeps_each_project_path_after_config_changes(monkeypatch, tmp_path):
    state = {}
    paths = {}
    for owner in ("alice", "bob"):
        url = f"https://github.com/{owner}/tool"
        paths[url] = str(tmp_path / owner / "tool")
        state[f"{url}#tool"] = release(url, install_path=paths[url])
    monkeypatch.setattr(cache, "state", state)
    monkeypatch.setattr(cli_interact, "dest", str(tmp_path / "new-default"))

    runner = CliRunner()
    result = runner.invoke(cli.app, ["ls", "--json"])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert len(rows) == 2
    assert {row["url"]: row["install_path"] for row in rows} == paths
    assert all(not row["path_inferred"] for row in rows)

    # The normal table must include the paths too, even when columns wrap.
    result = runner.invoke(cli.app, ["ls"], env={"COLUMNS": "240"})
    assert result.exit_code == 0, result.output
    assert "Install path" in result.output
    for path in paths.values():
        assert path in result.output


def test_list_paths_for_downloads_packages_and_legacy_records(monkeypatch, tmp_path):
    directory = str(tmp_path / "archives")
    records = {
        "legacy": release("legacy"),
        "archive": release(
            "archive", install_method="download", download_dir=directory
        ),
        "package": release("package", install_method="package", package_type="deb"),
        "legacy-appimage": release(
            "legacy-appimage", install_method="package", package_type="AppImage"
        ),
        "appimage": release(
            "appimage",
            install_method="package",
            package_type="AppImage",
            install_path="/apps/tool.appimage",
            hold_update=True,
        ),
    }
    monkeypatch.setattr(
        cache, "state", {f"{key}#{key}": r for key, r in records.items()}
    )
    monkeypatch.setattr(cli_interact, "dest", str(tmp_path / "bin"))
    runner = CliRunner()
    result = runner.invoke(cli.app, ["ls", "--json"])
    assert result.exit_code == 0, result.output
    rows = {row["name"]: row for row in json.loads(result.output)}
    assert rows["legacy"]["install_path"] == str(tmp_path / "bin/legacy")
    assert rows["legacy"]["path_inferred"] is True
    assert rows["archive"]["install_path"] == directory
    assert rows["package"]["install_path"] is None
    assert rows["legacy-appimage"]["install_path"].endswith(
        "/appimages/legacy-appimage.appimage"
    )
    assert rows["legacy-appimage"]["path_inferred"] is True
    assert rows["appimage"]["install_path"] == "/apps/tool.appimage"

    result = runner.invoke(cli.app, ["ls"], env={"COLUMNS": "240"})
    assert "(inferred)" in result.output
    assert "System package manager" in result.output
    result = runner.invoke(cli.app, ["ls", "--hold", "--json"])
    assert [row["name"] for row in json.loads(result.output)] == ["appimage"]


def test_remove_uses_recorded_binary_path(monkeypatch, tmp_path):
    original = tmp_path / "original/tool"
    original.parent.mkdir()
    original.write_bytes(b"original")
    other = tmp_path / "new-default/tool"
    other.parent.mkdir()
    other.write_bytes(b"unrelated")
    monkeypatch.setattr(
        cache, "state", {"repo#tool": release("repo", install_path=str(original))}
    )
    monkeypatch.setattr(cache, "state_file", str(tmp_path / "state.json"))
    monkeypatch.setattr(cli_interact, "dest", str(other.parent))
    result = CliRunner().invoke(cli.app, ["rm", "tool"])
    assert result.exit_code == 0, result.output
    assert not original.exists()
    assert other.read_bytes() == b"unrelated"
