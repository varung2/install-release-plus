"""Exercise real HTTP transfers and archive installation without external services."""

import io
import json
import shutil
import subprocess
import tarfile
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from typer.testing import CliRunner

from InstallRelease import cli
from InstallRelease import download as downloads
from InstallRelease.config import cache
from InstallRelease.providers.git import github
from InstallRelease.providers.git import main as git_main

REPOSITORY = "https://github.com/offline/tool"


@pytest.fixture
def local_release(monkeypatch, tmp_path):
    executable = shutil.which("true")
    assert executable, "Offline archive fixtures require the standard 'true' executable"

    def make_archive(bundle=False):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            data = Path(executable).read_bytes()
            member = tarfile.TarInfo("app/tool")
            member.size, member.mode = len(data), 0o755
            tar.addfile(member, io.BytesIO(data))
            if bundle:
                member = tarfile.TarInfo("app/libpython3.fixture.so.1.0")
                member.size = 7
                tar.addfile(member, io.BytesIO(b"library"))
        return buffer.getvalue()

    payload = {"archive": make_archive(), "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            payload["requests"].append(self.path)
            if self.path == "/repos/offline/tool":
                data = json.dumps(
                    {"name": "tool", "full_name": "offline/tool"}
                ).encode()
            elif self.path == "/repos/offline/tool/releases/latest":
                data = json.dumps(
                    {
                        "name": "tool",
                        "tag_name": "v1",
                        "prerelease": False,
                        "published_at": "2026-01-01T00:00:00Z",
                        "assets": [
                            {
                                "id": 1,
                                "name": "tool.tar.gz",
                                "size": len(payload["archive"]),
                                "browser_download_url": f"{base}/tool.tar.gz",
                            }
                        ],
                    }
                ).encode()
            elif self.path == "/tool.tar.gz":
                data = payload["archive"]
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    base = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_get = github.requests.get

    def routed_get(url, **kwargs):
        # Only redirect the provider's API transport; keep real JSON parsing,
        # release selection, streaming downloads, extraction and installation.
        if url.startswith("https://api.github.com/"):
            url = base + urlsplit(url).path
        return original_get(url, **kwargs)

    monkeypatch.setattr(github.requests, "get", routed_get)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    destination = tmp_path / "destination with spaces"
    monkeypatch.setattr(git_main, "dest", str(destination))
    monkeypatch.setattr(downloads, "dest", str(destination))
    monkeypatch.setattr(cache, "state", {})
    monkeypatch.setattr(cache, "state_file", str(tmp_path / "state.json"))
    try:
        yield payload, destination, make_archive, Path(executable).read_bytes()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_real_http_archive_can_be_kept_byte_for_byte(local_release):
    payload, destination, _, _ = local_release
    result = CliRunner().invoke(
        cli.app, ["get", REPOSITORY, "--file", "tool.tar.gz"], input="y\n2\ny\n"
    )
    assert result.exit_code == 0, result.output
    archive = destination / "tool.tar.gz"
    assert archive.read_bytes() == payload["archive"]
    assert not (destination / "app").exists()
    assert not (destination / "tool").exists()
    assert cache.state[f"{REPOSITORY}#tool-download"].install_method == "download"
    assert payload["requests"].count("/tool.tar.gz") == 1


def test_real_http_archive_installs_and_runs_executable(local_release):
    payload, destination, _, binary = local_release
    result = CliRunner().invoke(
        cli.app, ["get", REPOSITORY, "--file", "tool.tar.gz"], input="y\n1\ny\n"
    )
    assert result.exit_code == 0, result.output
    installed = destination / "tool"
    assert installed.read_bytes() == binary
    subprocess.run([str(installed)], check=True)
    assert not (destination / "tool.tar.gz").exists()
    assert cache.state[f"{REPOSITORY}#tool"].install_method == "binary"
    assert cache.state[f"{REPOSITORY}#tool"].install_path == str(installed)
    saved = json.loads(Path(cache.state_file).read_text())
    assert saved[f"{REPOSITORY}#tool"]["install_path"] == str(installed)
    assert payload["requests"].count("/tool.tar.gz") == 1


def test_binary_install_confirms_before_overwriting_existing_destination(local_release):
    _, destination, _, binary = local_release
    destination.mkdir(exist_ok=True)
    installed = destination / "tool"
    installed.write_bytes(b"existing unrelated executable")
    result = CliRunner().invoke(
        cli.app, ["get", REPOSITORY, "--file", "tool.tar.gz"], input="y\n1\ny\ny\n"
    )
    assert result.exit_code == 0, result.output
    assert installed.read_bytes() == binary
    assert "Installation collision" in result.output
    assert "Unknown" in result.output


@pytest.mark.parametrize("answer", ["n\n", "\n"])
def test_binary_collision_decline_never_downloads_or_changes_state(
    local_release, answer
):
    payload, destination, _, _ = local_release
    destination.mkdir(exist_ok=True)
    installed = destination / "tool"
    installed.write_bytes(b"existing executable")
    result = CliRunner().invoke(
        cli.app,
        ["get", REPOSITORY, "--file", "tool.tar.gz"],
        input="y\n1\ny\n" + answer,
    )
    assert result.exit_code == 0, result.output
    assert "Installation cancelled" in result.output
    assert installed.read_bytes() == b"existing executable"
    assert "/tool.tar.gz" not in payload["requests"]
    assert not cache.state


def test_exact_reinstall_skips_transfer_even_with_yes(local_release):
    payload, destination, _, _ = local_release
    runner = CliRunner()
    args = ["get", REPOSITORY, "--file", "tool.tar.gz", "-y"]
    assert runner.invoke(cli.app, args).exit_code == 0
    before = Path(cache.state_file).read_bytes()
    payload["requests"].clear()
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    assert "already exists" in result.output
    assert "/tool.tar.gz" not in payload["requests"]
    assert Path(cache.state_file).read_bytes() == before
    assert (destination / "tool").is_file()


@pytest.mark.parametrize("succeeds", [True, False])
def test_replacement_changes_owner_only_after_success(local_release, succeeds):
    payload, destination, make_archive, _ = local_release
    runner = CliRunner()
    args = ["get", REPOSITORY, "--file", "tool.tar.gz", "-y"]
    assert runner.invoke(cli.app, args).exit_code == 0
    key = f"{REPOSITORY}#tool"
    old = cache.state.pop(key)
    old_key = "https://github.com/previous/tool#tool"
    cache.state[old_key] = replace(
        old, url="https://github.com/previous/tool", tag_name="v0"
    )
    cache.save()
    before_state = Path(cache.state_file).read_bytes()
    before_binary = (destination / "tool").read_bytes()
    if not succeeds:
        payload["archive"] = make_archive(bundle=True)
    result = runner.invoke(cli.app, args)
    if succeeds:
        assert result.exit_code == 0, result.output
        assert set(cache.state) == {key}
        assert set(json.loads(Path(cache.state_file).read_text())) == {key}
    else:
        assert result.exit_code == 1, result.output
        assert set(cache.state) == {old_key}
        assert Path(cache.state_file).read_bytes() == before_state
        assert (destination / "tool").read_bytes() == before_binary


def test_shared_library_bundle_is_rejected_without_state(local_release, caplog):
    payload, destination, make_archive, _ = local_release
    payload["archive"] = make_archive(bundle=True)
    result = CliRunner().invoke(
        cli.app, ["get", REPOSITORY, "--file", "tool.tar.gz", "-y"]
    )
    assert result.exit_code == 1, result.output
    assert "Shared-library bundles are unsupported" in caplog.text
    assert not (destination / "tool").exists()
    assert cache.state == {}


def test_cancelling_final_confirmation_never_fetches_archive(local_release):
    payload, destination, _, _ = local_release
    result = CliRunner().invoke(
        cli.app, ["get", REPOSITORY, "--file", "tool.tar.gz"], input="y\n2\nn\n"
    )
    assert result.exit_code == 0, result.output
    assert "/tool.tar.gz" not in payload["requests"]
    assert not destination.exists()


def test_offline_guard_rejects_external_dns():
    import socket

    with pytest.raises(AssertionError, match="External DNS is disabled"):
        socket.getaddrinfo("example.invalid", 443)
