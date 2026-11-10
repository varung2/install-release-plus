"""Install a managed, startup-only notification hook for Bash or Zsh."""

import os
import shlex
import sys
from pathlib import Path

START = "# >>> IRP shell updates >>>"
END = "# <<< IRP shell updates <<<"


def startup_files(shell: str) -> list[Path]:
    home = Path.home()
    if Path(shell).name == "zsh":
        return [Path(os.environ.get("ZDOTDIR") or home) / ".zshrc"]
    if Path(shell).name == "bash":
        # Bash reads only the first existing login profile. Cover SSH logins
        # without assuming that this profile already sources .bashrc.
        profiles = [
            home / name for name in (".bash_profile", ".bash_login", ".profile")
        ]
        return [
            home / ".bashrc",
            next((p for p in profiles if p.exists()), profiles[-1]),
        ]
    raise ValueError(
        "Shell update notifications support Bash and Zsh; set SHELL accordingly."
    )


def install_hook(binary: str, shell: str) -> None:
    files = startup_files(shell)
    runtime = (
        Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
        / "install-release-plus/update_notice.py"
    )
    runtime = runtime.absolute()
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_bytes(
        (
            Path(__file__).resolve().parents[1] / "InstallRelease/update_notice.py"
        ).read_bytes()
    )
    block = f"""{START}
case $- in
  *i*)
    if [ -z "${{_IRP_SHELL_UPDATES_STARTED-}}" ] && command -v python3 >/dev/null 2>&1; then
      _IRP_SHELL_UPDATES_STARTED=1
      python3 {shlex.quote(str(runtime))} --notify {shlex.quote(str(Path(binary).absolute()))} 2>/dev/null || true
    fi
    ;;
esac
{END}
"""
    for path in files:
        old = path.read_text() if path.exists() else ""
        if START in old:
            start = old.index(START)
            end = old.find(END, start)
            if end == -1:
                raise ValueError(
                    f"Incomplete IRP hook in {path}; repair it before retrying."
                )
            new = old[:start] + block.rstrip("\n") + old[end + len(END) :]
        else:
            new = old + ("\n" if old and not old.endswith("\n") else "") + "\n" + block
        if new != old:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new)
        print(f"Shell update notifications enabled: {path}")


if __name__ == "__main__":
    try:
        install_hook(*sys.argv[1:])
    except (OSError, ValueError) as exc:
        sys.exit(f"IRP installed, but shell hook setup failed: {exc}")
