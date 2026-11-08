from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from InstallRelease import cli, cli_interact
from InstallRelease import download as downloads
from InstallRelease import state as state_module
from InstallRelease.config import cache
from InstallRelease.providers.git import main as git_main
from InstallRelease.providers.git.schemas import Release, ReleaseAssets, RepositoryInfo
from InstallRelease.state import State

URL = "https://github.com/owner/skills"
KEY = f"{URL}#skills-download"


def release(
    tag="v1", names=("skills.zip", "notes.md"), published="2026-01-01T00:00:00Z"
):
    return Release(
        url=URL,
        name="skills",
        tag_name=tag,
        prerelease=False,
        published_at=published,
        assets=[
            ReleaseAssets(name=name, browser_download_url=f"https://example.com/{name}")
            for name in names
        ],
    )


@pytest.fixture
def environment(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "state", {})
    monkeypatch.setattr(cache, "state_file", str(tmp_path / "state.json"))
    monkeypatch.setattr(downloads, "dest", str(tmp_path / "default"))
    remote = SimpleNamespace(value=release(), calls=[])

    def fetch(**kwargs):
        remote.calls.append(kwargs)
        return [remote.value]

    repo = SimpleNamespace(
        repo_url=URL,
        repo_name="skills",
        info=RepositoryInfo(full_name="owner/skills"),
        release=fetch,
    )
    monkeypatch.setattr(git_main, "get_repo_info", lambda url: repo)
    monkeypatch.setattr(git_main, "dest", str(tmp_path / "default"))
    monkeypatch.setattr(cli_interact, "get_repo_info", lambda url: repo)

    def transfer(url, at):
        path = Path(at) / url.rsplit("/", 1)[-1]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"asset from {remote.value.tag_name}")
        return str(path)

    monkeypatch.setattr(downloads, "download", transfer)
    return remote


def test_download_command_is_not_exposed():
    runner = CliRunner()
    result = runner.invoke(cli.app, ["download", URL])
    assert result.exit_code == 2
    assert "No such command" in result.output


@pytest.mark.parametrize(
    "names,selected",
    [
        ((), ""),
        (("skills.zip",), "missing.zip"),
        (("../escape",), ""),
        (("..",), ""),
        (("skills.zip", "skills.zip"), ""),
    ],
)
def test_invalid_asset_selection_leaves_no_state(environment, names, selected):
    environment.value = release(names=names)
    with pytest.raises(ValueError):
        downloads.download_release(
            URL, asset_file=selected, prompt=False, all_assets=True
        )
    assert KEY not in cache.state


def test_rejects_unrelated_files_and_symlinks(environment, tmp_path):
    output = tmp_path / "default"
    output.mkdir()
    target = output / "skills.zip"
    target.write_text("unrelated")
    with pytest.raises(ValueError, match="unrelated"):
        downloads.download_release(URL, prompt=False, all_assets=True)
    assert target.read_text() == "unrelated"
    target.unlink()
    target.symlink_to(tmp_path / "missing")
    with pytest.raises(ValueError, match="unrelated"):
        downloads.download_release(URL, prompt=False, all_assets=True)
    assert target.is_symlink()


def test_failed_transfer_preserves_old_files_and_state(
    environment, monkeypatch, tmp_path
):
    downloads.download_release(URL, prompt=False, all_assets=True)
    old_state = (tmp_path / "state.json").read_text()
    environment.value = release("v2")

    def fail(url, at):
        raise OSError("transfer failed")

    monkeypatch.setattr(downloads, "download", fail)
    with pytest.raises(OSError):
        downloads.download_release(URL, prompt=False, all_assets=True)
    assert (tmp_path / "default/skills.zip").read_text() == "asset from v1"
    assert (tmp_path / "state.json").read_text() == old_state
    assert not list((tmp_path / "default").glob(".irp-download-*"))


def test_upgrade_reuses_output_and_selection(environment, monkeypatch, tmp_path):
    output = tmp_path / "custom"
    downloads.download_release(
        URL, asset_file="notes.md", output=str(output), prompt=False
    )
    environment.value = release("v2", published="2026-02-01T00:00:00Z")
    monkeypatch.setattr(downloads, "dest", str(tmp_path / "changed-default"))
    monkeypatch.setattr(
        cli_interact,
        "get",
        lambda *a, **kw: pytest.fail("Attempted executable installation"),
    )
    cli_interact.upgrade(skip_prompt=True, name="skills-download")
    assert cache.state[KEY].tag_name == "v2"
    assert (output / "notes.md").read_text() == "asset from v2"
    assert not (output / "skills.zip").exists()
    assert not (tmp_path / "changed-default").exists()


def test_remove_tracks_versioned_filenames_and_preserves_other_files(
    environment, tmp_path
):
    downloads.download_release(URL, prompt=False, all_assets=True)
    environment.value = release("v2", names=("skills-v2.zip",))
    downloads.download_release(URL, prompt=False, all_assets=True)
    unrelated = tmp_path / "default/unrelated"
    unrelated.write_text("keep")
    cli_interact.remove("skills-download")
    assert KEY not in cache.state
    assert sorted(p.name for p in unrelated.parent.iterdir()) == ["unrelated"]


def test_remove_failure_keeps_state(environment, monkeypatch):
    downloads.download_release(URL, prompt=False, all_assets=True)

    def fail(path):
        raise PermissionError("denied")

    monkeypatch.setattr(cli_interact.os, "remove", fail)
    cli_interact.remove("skills-download")
    assert KEY in cache.state


def test_state_roundtrip_and_legacy_defaults(environment, tmp_path):
    downloads.download_release(URL, prompt=False, all_assets=True)
    loaded = State(str(tmp_path / "state.json"), Release).state[KEY]
    assert loaded.install_method == "download"
    assert loaded.download_files == cache.state[KEY].download_files
    legacy = asdict(release())
    for field in ("download_dir", "download_files", "download_file"):
        legacy.pop(field)
    (tmp_path / "state.json").write_text(json.dumps({KEY: legacy}))
    old = State(str(tmp_path / "state.json"), Release).state[KEY]
    assert old.download_dir is None
    assert old.download_files == []
    assert old.install_method == "binary"


def test_missing_selected_file_on_upgrade_keeps_previous_version(environment, tmp_path):
    downloads.download_release(URL, asset_file="skills.zip", prompt=False)
    environment.value = release(
        "v2", names=("renamed-skills.zip",), published="2026-02-01T00:00:00Z"
    )
    with pytest.raises(ValueError, match="No uploaded release assets match"):
        cli_interact.upgrade(skip_prompt=True, name="skills-download")
    assert cache.state[KEY].tag_name == "v1"
    assert (tmp_path / "default/skills.zip").read_text() == "asset from v1"


def test_json_and_info_show_download_location(environment):
    downloads.download_release(URL, prompt=False, all_assets=True)
    runner = CliRunner()
    result = runner.invoke(cli.app, ["ls", "--json"])
    row = json.loads(result.output)[0]
    assert row["type"] == "download"
    assert row["download_dir"] == cache.state[KEY].download_dir
    result = runner.invoke(cli.app, ["info", "skills-download"])
    assert result.exit_code == 0
    assert "Download directory" in result.output


def test_rejects_non_git_providers(environment):
    with pytest.raises(ValueError, match="repository"):
        downloads.download_release("docker@alpine")


def test_import_uses_local_destination(environment, monkeypatch, tmp_path):
    imported = release()
    imported.install_method = "download"
    imported.download_dir = "/some/other/computer"
    monkeypatch.setattr(
        cli_interact.requests_session,
        "get",
        lambda **kw: SimpleNamespace(json=lambda: {KEY: vars(imported)}),
    )
    monkeypatch.setattr("builtins.input", lambda: "y")
    cli_interact.pull_state("https://example.com/state.json")
    assert cache.state[KEY].download_dir == str(tmp_path / "default")


@pytest.fixture
def archive_installer(environment, monkeypatch):
    installed = []

    def install(self, asset, **kwargs):
        installed.append(asset.name)
        self._selected_release.assets = [asset]
        return True

    monkeypatch.setattr(git_main.GitInteractProvider, "install", install)
    return installed


@pytest.mark.parametrize(
    "filename",
    [
        "skills.zip",
        "skills.tar.gz",
        "skills.tgz",
        "skills.tar.xz",
        "skills.tar.bz2",
        "skills.tar.zst",
    ],
)
def test_get_archive_keep_download_confirms_and_skips_install(
    environment, archive_installer, tmp_path, filename
):
    environment.value = release(names=(filename, "notes.md"))
    result = CliRunner().invoke(
        cli.app, ["get", URL, "--file", filename], input="y\n2\ny\n"
    )
    assert result.exit_code == 0, result.output
    assert not archive_installer
    assert cache.state[KEY].download_file == filename
    assert cache.state[KEY].install_method == "download"
    assert (tmp_path / "default" / filename).is_file()
    assert (
        len(environment.calls) == 1
    )  # Reuse the selected release without fetching again.
    assert result.output.index("Archive action") < result.output.index(
        "Download selected release asset?"
    )


def test_get_archive_install_confirms_and_saves_binary(environment, archive_installer):
    result = CliRunner().invoke(
        cli.app, ["get", URL, "--file", "skills.zip"], input="y\n1\ny\n"
    )
    assert result.exit_code == 0, result.output
    assert archive_installer == ["skills.zip"]
    assert cache.state[f"{URL}#skills"].install_method == "binary"
    assert KEY not in cache.state
    assert "Install its executable?" in result.output


@pytest.mark.parametrize("answers", ["y\nn\n", "y\n1\nn\n", "y\n2\nn\n"])
def test_get_archive_cancel_before_transfer(
    environment, archive_installer, tmp_path, answers
):
    result = CliRunner().invoke(
        cli.app, ["get", URL, "--file", "skills.zip"], input=answers
    )
    assert result.exit_code == 0, result.output
    assert not archive_installer
    assert not cache.state
    assert not (tmp_path / "default").exists()


def test_get_checks_archive_after_changing_asset_id(environment, archive_installer):
    environment.value = release(names=("skills-linux", "skills.zip"))
    result = CliRunner().invoke(
        cli.app, ["get", URL, "--file", "skills-linux"], input="2\n2\ny\n"
    )
    assert result.exit_code == 0, result.output
    assert not archive_installer
    assert cache.state[KEY].download_file == "skills.zip"


@pytest.mark.parametrize(
    "name", ["skills-linux", "skills.deb", "skills.rpm", "skills.AppImage"]
)
def test_get_non_archive_preserves_existing_flow(environment, archive_installer, name):
    environment.value = release(names=(name,))
    result = CliRunner().invoke(cli.app, ["get", URL, "--file", name], input="y\n")
    assert result.exit_code == 0, result.output
    assert archive_installer == [name]
    assert "Archive action" not in result.output


def test_get_archive_yes_keeps_existing_install_behavior(
    environment, archive_installer
):
    result = CliRunner().invoke(cli.app, ["get", URL, "--file", "skills.zip", "-y"])
    assert result.exit_code == 0, result.output
    assert archive_installer == ["skills.zip"]
    assert "Archive action" not in result.output


@pytest.mark.parametrize("asset", ["skills.deb", "skills.rpm", "skills.AppImage"])
def test_native_asset_rejects_custom_output_before_install(
    environment, archive_installer, tmp_path, asset
):
    environment.value = release(names=(asset,))
    output = tmp_path / "native-output"
    result = CliRunner().invoke(
        cli.app, ["get", URL, "--file", asset, "--output", str(output), "-y"]
    )
    assert result.exit_code == 1, result.output
    assert not archive_installer
    assert not output.exists()


def test_get_archive_invalid_action_reprompts(environment, archive_installer):
    result = CliRunner().invoke(
        cli.app, ["get", URL, "--file", "skills.zip"], input="y\ninvalid\n2\ny\n"
    )
    assert result.exit_code == 0, result.output
    assert "Choose 1, 2, or n" in result.output
    assert cache.state[KEY].install_method == "download"


def test_get_tracked_archive_upgrade_does_not_ask_for_action(
    environment, archive_installer, monkeypatch
):
    runner = CliRunner()
    result = runner.invoke(
        cli.app, ["get", URL, "--file", "skills.zip"], input="y\n2\ny\n"
    )
    assert result.exit_code == 0, result.output
    environment.value = release("v2", published="2026-02-01T00:00:00Z")
    monkeypatch.setattr(
        "builtins.input",
        lambda: pytest.fail("Unexpected per-file prompt during upgrade"),
    )
    cli_interact.upgrade(name="skills-download", skip_prompt=True)
    assert cache.state[KEY].tag_name == "v2"
    assert not archive_installer


@pytest.mark.parametrize(
    "failure", ["later_transfer", "replacement", "state_write", "state_replace"]
)
def test_late_failure_restores_files_memory_and_json(
    environment, monkeypatch, tmp_path, failure
):
    downloads.download_release(URL, prompt=False, all_assets=True)
    previous = cache.state[KEY]
    previous_json = (tmp_path / "state.json").read_bytes()
    old_files = {Path(p): Path(p).read_bytes() for p in previous.download_files}
    environment.value = release("v2", names=("skills.zip", "new.txt", "notes.md"))
    original_replace = downloads.os.replace
    original_download = downloads.download

    def replace(source, target):
        if (
            failure == "replacement"
            and Path(source).parent.name == "ready"
            and Path(target).name == "notes.md"
        ):
            raise OSError("injected replacement failure")
        if failure == "state_replace" and Path(source).name.startswith(".irp-state-"):
            raise OSError("injected state replacement failure")
        return original_replace(source, target)

    def transfer(url, at):
        if failure == "later_transfer" and url.endswith("new.txt"):
            raise OSError("injected second transfer failure")
        return original_download(url, at)

    def write(*args, **kwargs):
        raise OSError("injected state write failure")

    monkeypatch.setattr(downloads.os, "replace", replace)
    monkeypatch.setattr(downloads, "download", transfer)
    if failure == "state_write":
        monkeypatch.setattr(state_module.json, "dump", write)
    with pytest.raises(OSError, match="injected"):
        downloads.download_release(URL, prompt=False, all_assets=True)
    assert cache.state[KEY] is previous
    assert (tmp_path / "state.json").read_bytes() == previous_json
    assert all(path.read_bytes() == data for path, data in old_files.items())
    assert not (tmp_path / "default/new.txt").exists()
    assert not list((tmp_path / "default").glob(".irp-download-*"))
    assert not list(tmp_path.glob(".irp-state-*"))


def test_initial_state_save_failure_leaves_no_download(
    environment, monkeypatch, tmp_path
):
    def fail():
        raise OSError("state unavailable")

    monkeypatch.setattr(cache, "save", fail)
    with pytest.raises(OSError):
        downloads.download_release(URL, prompt=False, all_assets=True)
    assert KEY not in cache.state
    assert list((tmp_path / "default").iterdir()) == []
    assert not (tmp_path / "state.json").exists()


def test_atomic_state_save_preserves_valid_json_on_serialization_error(
    environment, tmp_path
):
    downloads.download_release(URL, prompt=False, all_assets=True)
    old = (tmp_path / "state.json").read_bytes()
    cache.state["unserializable"] = object()
    with pytest.raises(TypeError):
        cache.save()
    assert (tmp_path / "state.json").read_bytes() == old
    assert not list(tmp_path.glob(".irp-state-*"))
