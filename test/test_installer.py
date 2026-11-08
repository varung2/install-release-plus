import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def installer(tmp_path):
    root = tmp_path / "checkout with spaces"
    root.mkdir()
    shutil.copy2(Path(__file__).parents[1] / "install.sh", root / "install.sh")
    (root / "pyproject.toml").touch()
    (root / "cli").mkdir()
    (root / "cli/__main__.py").touch()
    (root / "build.sh").write_text(
        f"#!{sys.executable}\n"
        "import os, sys\nfrom pathlib import Path\n"
        "root = Path(__file__).parent\nmode = os.environ['IRP_TEST_MODE']\n"
        "if '--check' in sys.argv: sys.exit(0 if mode == 'reuse' else 1)\n"
        "(root / 'build-called').touch()\n"
        "if mode == 'compile-failure': sys.exit(9)\n"
        "(root / 'dist').mkdir(exist_ok=True)\n"
        "binary = root / 'dist/InstallReleasePlus'\n"
        "binary.write_text('#!/bin/sh\\nexit ' + ('1' if mode == 'smoke-failure' else '0') + '\\n')\n"
        "binary.chmod(0o755)\n"
    )
    (root / "build.sh").chmod(0o755)
    destination = tmp_path / "installed bin"
    destination.mkdir()
    previous = b"#!/bin/sh\necho previous\n"
    (destination / "irp").write_bytes(previous)
    (destination / "irp").chmod(0o755)

    def run(mode):
        commands = tmp_path / "commands"
        commands.mkdir(exist_ok=True)
        if mode in ("install-failure", "rename-failure"):
            command = commands / ("install" if mode == "install-failure" else "mv")
            command.write_text("#!/bin/sh\nexit 23\n")
            command.chmod(0o755)
        return subprocess.run(
            ["bash", str(root / "install.sh")],
            cwd=tmp_path,
            env={
                **os.environ,
                "IRP_BIN_DIR": str(destination),
                "IRP_TEST_MODE": mode,
                "PATH": f"{commands}:{os.environ['PATH']}",
            },
            capture_output=True,
            text=True,
            check=False,
        )

    return root, destination, previous, run


@pytest.mark.parametrize(
    "failure", ["compile-failure", "smoke-failure", "install-failure", "rename-failure"]
)
def test_failed_install_preserves_working_executable(installer, failure):
    _root, destination, previous, run = installer
    result = run(failure)
    assert result.returncode != 0
    assert (destination / "irp").read_bytes() == previous
    assert not list(destination.glob(".irp-install.*"))
    assert not (destination / "ir").exists()


def test_current_build_installs_without_invoking_compiler(installer):
    root, destination, _, run = installer
    (root / "dist").mkdir()
    binary = root / "dist/InstallReleasePlus"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    result = run("reuse")
    assert result.returncode == 0, result.stderr
    assert not (root / "build-called").exists()
    assert (destination / "irp").read_bytes() == binary.read_bytes()


def test_missing_build_is_built_then_installed(installer):
    root, destination, _, run = installer
    result = run("fresh")
    assert result.returncode == 0, result.stderr
    assert (root / "build-called").exists()
    assert (destination / "irp").read_bytes() == (
        root / "dist/InstallReleasePlus"
    ).read_bytes()
    assert os.access(destination / "irp", os.X_OK)
