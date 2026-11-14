import json

import pytest
from typer.testing import CliRunner

from InstallRelease import cli
from InstallRelease.schemas import ToolConfig


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("change_path", [False, True])
def test_config_preserves_pre_release_unless_requested(
    monkeypatch, tmp_path, enabled, change_path
):
    config = ToolConfig(pre_release=enabled)
    saved = tmp_path / "config.json"
    monkeypatch.setattr(cli, "config", config)
    monkeypatch.setattr(cli.cache_config, "state", {"config": config})
    monkeypatch.setattr(cli.cache_config, "state_file", str(saved))
    args = ["config"]
    if change_path:
        args += ["--path", str(tmp_path / "bin")]
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    assert json.loads(saved.read_text())["config"]["pre_release"] is enabled
    if change_path:
        assert json.loads(saved.read_text())["config"]["path"] == str(tmp_path / "bin")


@pytest.mark.parametrize("enabled", [False, True])
def test_config_can_explicitly_enable_or_disable_pre_release(
    monkeypatch, tmp_path, enabled
):
    config = ToolConfig(pre_release=not enabled)
    saved = tmp_path / "config.json"
    monkeypatch.setattr(cli, "config", config)
    monkeypatch.setattr(cli.cache_config, "state", {"config": config})
    monkeypatch.setattr(cli.cache_config, "state_file", str(saved))
    flag = "--pre-release" if enabled else "--no-pre-release"
    result = CliRunner().invoke(cli.app, ["config", flag])
    assert result.exit_code == 0, result.output
    assert json.loads(saved.read_text())["config"]["pre_release"] is enabled
