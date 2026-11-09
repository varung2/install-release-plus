import json
import os
import pty
import shlex
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
    shutil.copytree(Path(__file__).parents[1] / "scripts", root / "scripts")
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

    def run(mode, *options, shell="/bin/bash"):
        commands = tmp_path / "commands"
        commands.mkdir(exist_ok=True)
        if mode in ("install-failure", "rename-failure"):
            command = commands / ("install" if mode == "install-failure" else "mv")
            command.write_text("#!/bin/sh\nexit 23\n")
            command.chmod(0o755)
        return subprocess.run(
            ["bash", str(root / "install.sh"), *options],
            cwd=tmp_path,
            env={
                **os.environ,
                "IRP_BIN_DIR": str(destination),
                "IRP_TEST_MODE": mode,
                "HOME": str(tmp_path),
                "SHELL": shell,
                "ZDOTDIR": str(tmp_path / "zsh config"),
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


def test_shell_hook_is_opt_in_and_idempotent(installer):
    root, _destination, _, run = installer
    home = root.parent
    rc = home / ".bashrc"
    rc.write_text("# My existing config\n")
    assert run("fresh").returncode == 0
    assert rc.read_text() == "# My existing config\n"
    assert run("reuse", "--shell-updates").returncode == 0
    first = rc.read_text()
    assert "IRP shell updates" in first
    assert first.startswith("# My existing config\n")
    assert (home / ".profile").exists()
    assert run("reuse", "--shell-updates").returncode == 0
    assert rc.read_text() == first
    assert run("reuse", "--no-shell-updates").returncode == 0
    assert rc.read_text() == first


def test_zsh_hook_respects_zdotdir(installer):
    root, _destination, _, run = installer
    result = run("fresh", "--shell-updates", shell="/usr/bin/zsh")
    assert result.returncode == 0, result.stderr
    assert "IRP shell updates" in (root.parent / "zsh config/.zshrc").read_text()
    assert not (root.parent / ".bashrc").exists()


def test_failed_install_never_changes_shell_config(installer):
    root, _destination, _, run = installer
    result = run("compile-failure", "--shell-updates")
    assert result.returncode != 0
    assert not (root.parent / ".bashrc").exists()


@pytest.mark.parametrize("updates", [0, 2])
def test_shell_hook_runs_once_and_only_for_interactive_shells(installer, updates):
    root, destination, _, run = installer
    home = root.parent
    profile = home / ".bash_profile"
    profile.write_text('. "$HOME/.bashrc"\n')
    result = run("fresh", "--shell-updates")
    assert result.returncode == 0, result.stderr
    calls = home / "calls"
    binary = destination / "irp"
    rows = [{"update_status": "available"}] * updates + [{"update_status": "current"}]
    binary.write_text(
        "#!/bin/sh\n"
        f"echo checked >> {shlex.quote(str(calls))}\n"
        f"printf '%s\\n' {shlex.quote(json.dumps(rows))}\n"
    )
    rc = home / ".bashrc"
    env = {**os.environ, "HOME": str(home)}
    noninteractive = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", f"source {shlex.quote(str(rc))}"],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert noninteractive.returncode == 0
    assert not calls.exists()
    result = subprocess.run(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-ic",
            f"source {shlex.quote(str(rc))}; source {shlex.quote(str(profile))}",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert "[1]" not in result.stderr
    assert calls.read_text().splitlines() == ["checked"]
    assert ("IRP: 2 updates available" in result.stdout) == bool(updates)
    if not updates:
        assert result.stdout == ""


def test_shell_check_does_not_block_the_prompt(installer):
    root, destination, _, run = installer
    assert run("fresh", "--shell-updates").returncode == 0
    home = root.parent
    ready = home / "prompt-ready"
    done = home / "checked"
    # A blocking hook would deadlock: the shell must advance to release this check.
    (destination / "irp").write_text(
        "#!/bin/sh\n"
        f"while [ ! -f {shlex.quote(str(ready))} ]; do sleep 0.01; done\n"
        f"touch {shlex.quote(str(done))}\n"
        "echo '[]'\n"
    )
    result = subprocess.run(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-ic",
            f"source {shlex.quote(str(home / '.bashrc'))}; touch {shlex.quote(str(ready))}",
        ],
        env={**os.environ, "HOME": str(home)},
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert done.exists()


def test_invalid_installer_option_does_not_build(installer):
    root, _destination, _, run = installer
    assert run("fresh", "--invalid").returncode != 0
    assert not (root / "build-called").exists()


def test_unsupported_shell_leaves_config_alone(installer):
    root, destination, _, run = installer
    result = run("fresh", "--shell-updates", shell="/usr/bin/fish")
    assert result.returncode != 0
    assert "IRP installed, but shell hook setup failed" in result.stderr
    assert not (root.parent / ".bashrc").exists()
    assert (destination / "irp").exists()


@pytest.mark.parametrize("answer", ["y", ""])
def test_interactive_installer_offers_hook_only_after_install(installer, answer):
    root, destination, _, _run = installer
    master, slave = pty.openpty()
    try:
        os.write(master, (answer + "\n").encode())
        result = subprocess.run(
            ["bash", str(root / "install.sh")],
            env={
                **os.environ,
                "HOME": str(root.parent),
                "SHELL": "/bin/bash",
                "IRP_BIN_DIR": str(destination),
                "IRP_TEST_MODE": "fresh",
            },
            stdin=slave,
            stdout=slave,
            stderr=slave,
            timeout=5,
        )
        os.close(slave)
        slave = None
        output = b""
        while True:
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            if not chunk:
                break
            output += chunk
        assert result.returncode == 0, output
        assert output.index(b"Installed local build") < output.index(
            b"Check for IRP updates"
        )
        assert (root.parent / ".bashrc").exists() == bool(answer)
    finally:
        os.close(master)
        if slave is not None:
            os.close(slave)
