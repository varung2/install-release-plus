"""Check build reuse/invalidation without invoking the C compiler in unit tests."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def local_build(tmp_path):
    root = tmp_path / "checkout with spaces"
    root.mkdir()
    shutil.copy2(Path(__file__).parents[1] / "build.sh", root / "build.sh")
    for name in (
        "pyproject.toml",
        "uv.lock",
        "InstallRelease/module.py",
        "cli/__main__.py",
    ):
        path = root / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("# Initial input\n")

    commands = tmp_path / "commands"
    commands.mkdir()
    # Replace only external tooling; exercise the real script's state checks.
    uv = commands / "uv"
    uv.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "from pathlib import Path\n"
        "if 'nuitka' in sys.argv:\n"
        "    root = Path(os.environ['IR_TEST_PROJECT'])\n"
        "    (root / 'dist').mkdir(exist_ok=True)\n"
        "    binary = root / 'dist/InstallReleasePlus'\n"
        "    binary.write_text('#!/bin/sh\\nexit 0\\n')\n"
        "    binary.chmod(0o755)\n"
    )
    uv.chmod(0o755)
    for name in ("cc", "patchelf"):
        command = commands / name
        command.write_text("#!/bin/sh\nexit 0\n")
        command.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{commands}:{os.environ['PATH']}",
        "IR_TEST_PROJECT": str(root),
    }

    def run(*args):
        return subprocess.run(
            ["bash", str(root / "build.sh"), *args],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    return root, run


def test_build_records_freshness_from_another_directory(local_build):
    root, run = local_build
    assert run("--check").returncode == 1
    result = run()
    assert result.returncode == 0, result.stderr
    assert (root / "dist/.irp-build.json").is_file()
    assert run("--check").returncode == 0


@pytest.mark.parametrize(
    "change",
    ["edit", "add", "delete", "lock", "script", "binary", "permissions", "stamp"],
)
def test_changed_inputs_or_artifact_invalidate_build(local_build, change):
    root, run = local_build
    assert run().returncode == 0
    source = root / "InstallRelease/module.py"
    if change == "edit":
        original = source.stat()
        source.write_text("# Changed source\n")
        os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns))
    elif change == "add":
        (root / "InstallRelease/new_module.py").write_text("# New source\n")
    elif change == "delete":
        source.unlink()
    elif change == "lock":
        (root / "uv.lock").write_text("# Changed dependencies\n")
    elif change == "script":
        with (root / "build.sh").open("a") as handle:
            handle.write("\n# Changed build settings\n")
    elif change == "binary":
        (root / "dist/InstallReleasePlus").write_text("#!/bin/sh\nexit 1\n")
    elif change == "permissions":
        (root / "dist/InstallReleasePlus").chmod(0o644)
    else:
        (root / "dist/.irp-build.json").write_text("invalid JSON")
    assert run("--check").returncode == 1
    result = run()
    assert result.returncode == 0, result.stderr
    assert run("--check").returncode == 0
