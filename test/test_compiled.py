"""Opt-in smoke tests: build first, then run pytest --compiled."""

import os
import shutil
import subprocess
from importlib.metadata import distribution
from pathlib import Path

import pytest

pytestmark = pytest.mark.compiled


def test_standalone_identity_version_and_fork_url(tmp_path):
    root = Path(__file__).parents[1]
    built = Path(os.environ.get("IRP_TEST_BINARY", root / "dist/InstallReleasePlus"))
    assert built.is_file(), "Run ./build.sh before pytest --compiled"
    installed = tmp_path / "bin/irp"
    installed.parent.mkdir()
    shutil.copy2(built, installed)
    env = {**os.environ, "IRP_STATE_DIR": str(tmp_path / "state")}

    def run(*args):
        return subprocess.run(
            [str(installed), *args], env=env, capture_output=True, text=True, check=True
        ).stdout

    metadata = distribution("InstallReleasePlus")
    repo = next(
        url.split(", ", 1)[1]
        for url in metadata.metadata.get_all("Project-URL")
        if url.startswith("Repository, ")
    )
    assert "Usage: irp" in run("--help")
    assert "--output" in run("get", "--help")
    assert run("me", "--version").strip() == metadata.version
    assert repo in run("me")
    result = subprocess.run(
        [str(installed), "download"], env=env, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "No such command" in result.stderr
