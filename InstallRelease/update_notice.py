"""Cached shell notices. Refreshes are triggered by commands or shell startup."""

import hashlib
import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

CACHE_MAX_AGE = 6 * 60 * 60
CHECK_TIMEOUT = 5


def cache_path() -> Path:
    if directory := os.environ.get("IRP_STATE_DIR"):
        return Path(directory) / "update-notice.json"
    return (
        Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
        / "install-release-plus/update-notice.json"
    )


def state_digest() -> str:
    if directory := os.environ.get("IRP_STATE_DIR"):
        path = Path(directory) / "state.json"
    else:
        folder = "Library/.config" if sys.platform == "darwin" else ".config"
        path = Path.home() / folder / "install_release/state.json"
    try:
        config = path.with_name("config.json")
        return hashlib.sha256(
            path.read_bytes() + (config.read_bytes() if config.exists() else b"")
        ).hexdigest()
    except OSError:
        return ""


def save_snapshot(
    rows: list[dict], *, error: str | None = None, expected_state: str | None = None
) -> None:
    """Atomically replace this disposable cache; never modify installed state."""
    temporary = None
    try:
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("Invalid release status data")
        digest = state_digest()
        if expected_state is not None and digest != expected_state:
            return
        snapshot = {
            "state": digest,
            "checked_at": time.time(),
            "error": error,
            "rows": [
                {
                    k: row.get(k)
                    for k in ("url", "update_status", "update_error", "update_retry_at")
                }
                for row in rows
            ],
        }
        path = cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(snapshot, handle)
        os.replace(temporary, path)
    except (OSError, ValueError, TypeError):
        pass  # A failed cache write must not break ls or shell startup.
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def read_snapshot() -> dict | None:
    try:
        snapshot = json.loads(cache_path().read_text())
        if snapshot["state"] != state_digest():
            return None
        if not isinstance(snapshot["rows"], list) or not all(
            isinstance(row, dict) for row in snapshot["rows"]
        ):
            return None
        snapshot["checked_at"] = float(snapshot["checked_at"])
        if not math.isfinite(snapshot["checked_at"]):
            return None
        for row in snapshot["rows"]:
            if row.get("update_status") not in (
                "available",
                "current",
                "held",
                "unavailable",
            ):
                return None
            if row.get("url") is not None and not isinstance(row["url"], str):
                return None
            if row.get("update_retry_at") is not None:
                row["update_retry_at"] = float(row["update_retry_at"])
                if not math.isfinite(row["update_retry_at"]):
                    return None
        return snapshot
    except (OSError, ValueError, KeyError, TypeError):
        return None


def rate_limited_rows() -> list[dict]:
    snapshot = read_snapshot()
    return (
        [
            row
            for row in snapshot["rows"]
            if row.get("update_error") == "rate_limit"
            and (row.get("update_retry_at") or 0) > time.time()
        ]
        if snapshot
        else []
    )


def banner() -> str:
    try:
        snapshot = read_snapshot()
        if snapshot is None:
            return ""
        checked = (
            datetime.fromtimestamp(snapshot["checked_at"])
            .astimezone()
            .strftime("%Y-%m-%d %H:%M %Z")
        )
        rows = snapshot["rows"]
        available = sum(row["update_status"] == "available" for row in rows)
        unavailable = sum(row["update_status"] == "unavailable" for row in rows)
        lines = []
        if available:
            lines += [
                f"{available} IRP update{' is' if available == 1 else 's are'} available.",
                "To see available updates, run: irp ls",
                "To install them, run: irp upgrade",
            ]
        if unavailable or snapshot.get("error"):
            reason = ""
            if any(row.get("update_error") == "rate_limit" for row in rows):
                reason = " (API rate limit reached)"
            elif snapshot.get("error") == "timeout":
                reason = " (request timed out)"
            lines += [
                f"IRP could not complete its update check{reason}.",
                "Run irp ls for details.",
            ]
        return (
            "\n" + "\n".join([*lines, f"Last checked: {checked}"]) + "\n\n"
            if lines
            else ""
        )
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return ""


def _release_rows(binary: str) -> list[dict]:
    """Wait for one foreground check and kill its whole process group on timeout."""
    process = subprocess.Popen(
        [binary, "ls", "--json"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(timeout=CHECK_TIMEOUT)
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, process.args)
    return json.loads(output)


def refresh(binary: str) -> None:
    import fcntl

    try:
        path = cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_suffix(".lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return  # Another newly opened shell is already refreshing.
            digest = state_digest()
            snapshot = read_snapshot()
            if snapshot is not None:
                if 0 <= time.time() - snapshot["checked_at"] < CACHE_MAX_AGE:
                    return
                active = [
                    row for row in snapshot["rows"] if row["update_status"] != "held"
                ]
                if (
                    snapshot["state"] == digest
                    and active
                    and all(
                        row.get("update_error") == "rate_limit"
                        and (row.get("update_retry_at") or 0) > time.time()
                        for row in active
                    )
                ):
                    return
            try:
                save_snapshot(_release_rows(binary), expected_state=digest)
            except subprocess.TimeoutExpired:
                save_snapshot([], error="timeout", expected_state=digest)
            except (OSError, ValueError, subprocess.CalledProcessError):
                save_snapshot([], error="request_failed", expected_state=digest)
    except OSError:
        pass


def notify(binary: str) -> None:
    refresh(binary)
    print(banner(), end="", flush=True)


if __name__ == "__main__":
    action, binary = sys.argv[1:]
    if action == "--notify":
        notify(binary)
