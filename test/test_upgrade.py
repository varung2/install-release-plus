from types import SimpleNamespace

from typer.testing import CliRunner

from InstallRelease import cli, cli_interact
from InstallRelease.providers.git.schemas import Release


def test_upgrade_accepts_and_filters_by_name(monkeypatch):
    captured = []
    monkeypatch.setattr(
        cli_interact.cache,
        "state",
        {
            f"{name}-repo#{name}": Release(
                f"{name}-repo", name, "v1", False, "2026-01-01T00:00:00Z", []
            )
            for name in ("zen", "other")
        },
    )
    monkeypatch.setattr(cli_interact, "state_info", lambda: None)
    monkeypatch.setattr(
        cli_interact,
        "get_repo_info",
        lambda url, **kw: (
            captured.append(url)
            or SimpleNamespace(repo_url=url, release=lambda **kw: [])
        ),
    )

    result = CliRunner().invoke(cli.app, ["upgrade", "zen", "--yes"])

    assert result.exit_code == 0
    assert captured == ["zen-repo"]


def test_me_upgrade_keeps_running_binary_name(monkeypatch):
    for argv0, expected in [
        (
            "/home/u/bin/irp",
            "irp get https://github.com/varung2/install-release-plus -n irp",
        ),
        (
            "InstallReleasePlus",
            "InstallReleasePlus get https://github.com/varung2/install-release-plus -n InstallReleasePlus",
        ),
        (
            "/src/InstallRelease/cli.py",
            "irp get https://github.com/varung2/install-release-plus -n irp",
        ),
    ]:
        ran = []
        monkeypatch.setattr(cli.sys, "argv", [argv0])
        monkeypatch.setattr(cli.os, "system", ran.append)

        result = CliRunner().invoke(cli.app, ["me", "-U"])

        assert result.exit_code == 0
        assert ran == [expected]
