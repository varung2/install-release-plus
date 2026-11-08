"""Exercise real HTTP transfers and archive installation without external services."""

import io
import json
import shutil
import subprocess
import tarfile
import threading
import zipfile
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from typer.testing import CliRunner

from InstallRelease import cli, cli_interact
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
            elif self.path in (
                "/repos/offline/tool/releases/latest",
                f"/repos/offline/tool/releases/tags/{payload.get('tag', 'v1')}",
            ):
                data = json.dumps(
                    {
                        "name": "tool",
                        "tag_name": payload.get("tag", "v1"),
                        "prerelease": False,
                        "published_at": payload.get(
                            "published", "2026-01-01T00:00:00Z"
                        ),
                        **{
                            field: f"{base}/{field}/{payload.get('tag', 'v1')}"
                            for field in payload.get("source_urls", [])
                        },
                        "assets": []
                        if payload.get("source_only")
                        else [
                            {
                                "id": 1,
                                "name": payload.get("asset_name", "tool.tar.gz"),
                                "size": len(payload["archive"]),
                                "browser_download_url": f"{base}/tool.tar.gz",
                            }
                        ],
                    }
                ).encode()
            elif self.path == "/tool.tar.gz":
                data = payload["archive"]
            elif self.path == f"/tarball_url/{payload.get('tag', 'v1')}":
                data = payload["archive"]
            elif self.path == f"/zipball_url/{payload.get('tag', 'v1')}":
                data = payload["zip"]
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


@pytest.mark.parametrize(
    ("filename", "asset_id", "field"),
    [("source.tar.gz", "1", "tarball_url"), ("source.zip", "2", "zipball_url")],
)
@pytest.mark.parametrize("explicit_file", [False, True])
def test_generated_sources_download_upgrade_and_remove(
    local_release, tmp_path, filename, asset_id, field, explicit_file
):
    payload, default, _, _ = local_release

    def source_bytes(text):
        buffer = io.BytesIO()
        if field == "zipball_url":
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr("owner-tool-commit/skills/SKILL.md", text)
        else:
            with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
                member = tarfile.TarInfo("owner-tool-commit/skills/SKILL.md")
                member.size = len(text)
                archive.addfile(member, io.BytesIO(text))
        return buffer.getvalue()

    expected = source_bytes(b"skill instructions")
    payload.update(
        source_only=True,
        source_urls=["tarball_url", "zipball_url"],
        zip=expected,
        archive=expected,
    )
    custom = tmp_path / "kept sources"
    args = ["get", REPOSITORY, "-o", str(custom)]
    if explicit_file:
        args += ["--file", filename]
    runner = CliRunner()
    result = runner.invoke(
        cli.app, args, input=f"{'y' if explicit_file else asset_id}\n2\ny\n"
    )
    assert result.exit_code == 0, result.output
    assert "source.tar.gz" in result.output and "source.zip" in result.output
    assert "Unknown" in result.output
    assert (custom / filename).read_bytes() == expected
    assert list(custom.iterdir()) == [custom / filename]
    assert not default.exists()
    key = f"{REPOSITORY}#tool-download"
    assert cache.state[key].download_file == filename
    assert cache.state[key].tag_name == "v1"
    assert payload["requests"].count(f"/{field}/v1") == 1

    expected = source_bytes(b"updated skill instructions")
    payload.update(
        tag="v2", published="2026-02-01T00:00:00Z", zip=expected, archive=expected
    )
    result = runner.invoke(cli.app, ["upgrade", "tool-download", "--yes"])
    assert result.exit_code == 0, result.output
    assert cache.state[key].tag_name == "v2"
    assert payload["requests"].count(f"/{field}/v2") == 1
    assert (custom / filename).read_bytes() == expected
    result = runner.invoke(cli.app, ["rm", "tool-download"])
    assert result.exit_code == 0, result.output
    assert not (custom / filename).exists()
    assert key not in cache.state


def test_generated_sources_do_not_change_uploaded_binary_default(local_release):
    payload, destination, _, binary = local_release
    payload["source_urls"] = ["tarball_url", "zipball_url"]
    result = CliRunner().invoke(cli.app, ["get", REPOSITORY], input="y\n1\ny\n")
    assert result.exit_code == 0, result.output
    assert "source.tar.gz" in result.output and "source.zip" in result.output
    assert (destination / "tool").read_bytes() == binary
    assert "/tool.tar.gz" in payload["requests"]
    assert not any("ball_url/" in path for path in payload["requests"])


def test_generated_tarball_can_install_an_executable(local_release):
    payload, destination, _, binary = local_release
    payload.update(source_only=True, source_urls=["tarball_url"])
    result = CliRunner().invoke(cli.app, ["get", REPOSITORY], input="y\n1\ny\n")
    assert result.exit_code == 0, result.output
    installed = destination / "tool"
    assert installed.read_bytes() == binary
    subprocess.run([str(installed)], check=True)
    assert cache.state[f"{REPOSITORY}#tool"].install_method == "binary"


def test_generated_sources_preserve_native_package_selection(
    local_release, monkeypatch
):
    payload, _, _, _ = local_release
    payload.update(asset_name="tool.deb", source_urls=["tarball_url", "zipball_url"])
    monkeypatch.setattr(git_main, "os_package_type", "deb")
    provider = git_main.GitInteractProvider(github.GitHubInfo(REPOSITORY))
    selected = provider.select(provider.resolve())
    assert selected.name == "tool.deb"
    assert not selected.source_archive


def test_generated_source_can_override_uploaded_asset_and_cancel(local_release):
    payload, destination, _, _ = local_release
    payload["source_urls"] = ["tarball_url", "zipball_url"]
    result = CliRunner().invoke(cli.app, ["get", REPOSITORY], input="2\n2\nn\n")
    assert result.exit_code == 0, result.output
    assert not destination.exists()
    assert not cache.state
    assert not any("ball_url/" in path for path in payload["requests"])
    assert "/tool.tar.gz" not in payload["requests"]


def test_generated_source_filename_collision_keeps_uploaded_asset(local_release):
    payload, destination, _, _ = local_release
    payload.update(asset_name="source.tar.gz", source_urls=["tarball_url"])
    result = CliRunner().invoke(
        cli.app, ["get", REPOSITORY, "--file", "source.tar.gz"], input="y\n2\ny\n"
    )
    assert result.exit_code == 0, result.output
    assert (destination / "source.tar.gz").read_bytes() == payload["archive"]
    assert "/tool.tar.gz" in payload["requests"]
    assert "/tarball_url/v1" not in payload["requests"]


@pytest.mark.parametrize("field", ["tarball_url", "zipball_url"])
def test_generated_source_is_available_when_only_one_url_exists(local_release, field):
    payload, _, _, _ = local_release
    payload.update(source_only=True, source_urls=[field])
    releases = github.GitHubInfo(REPOSITORY).release(tag_name="v1")
    assert len(releases[0].assets) == 1
    assert releases[0].assets[0].source_archive
    assert releases[0].assets[0].browser_download_url.endswith(f"/{field}/v1")
    assert "/repos/offline/tool/releases/tags/v1" in payload["requests"]


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


@pytest.mark.parametrize("mode,option", [("download", "--output"), ("binary", "-o")])
def test_custom_output_survives_upgrade_listing_and_removal(
    local_release, monkeypatch, tmp_path, mode, option
):
    payload, default, _, _ = local_release
    monkeypatch.chdir(tmp_path)
    custom = tmp_path / "custom releases"
    config_before = dict(vars(cli_interact.config))
    default.mkdir()
    sentinel = default / "tool"
    sentinel.write_bytes(b"unrelated default installation")
    runner = CliRunner()
    answers = "y\n2\ny\n" if mode == "download" else "y\n1\ny\n"
    result = runner.invoke(
        cli.app,
        ["get", REPOSITORY, "--file", "tool.tar.gz", option, "custom releases"],
        input=answers,
    )
    assert result.exit_code == 0, result.output
    name = "tool-download" if mode == "download" else "tool"
    target = custom / ("tool.tar.gz" if mode == "download" else "tool")
    assert target.is_file()
    assert str(custom) in result.output
    assert sentinel.read_bytes() == b"unrelated default installation"
    assert vars(cli_interact.config) == config_before
    row = json.loads(runner.invoke(cli.app, ["ls", "--json"]).output)[0]
    assert row["install_path"] == str(custom if mode == "download" else target)

    # An upgrade must use the saved per-project path, not a changed default.
    changed_default = str(tmp_path / "changed-default")
    for module in (cli_interact, git_main, downloads):
        monkeypatch.setattr(module, "dest", changed_default)
    payload.update(tag="v2", published="2026-02-01T00:00:00Z")
    result = runner.invoke(cli.app, ["upgrade", name, "--yes"])
    assert result.exit_code == 0, result.output
    assert cache.state[f"{REPOSITORY}#{name}"].tag_name == "v2"
    assert target.is_file()
    assert not Path(changed_default).exists()
    result = runner.invoke(cli.app, ["rm", name])
    assert result.exit_code == 0, result.output
    assert not target.exists()
    assert sentinel.read_bytes() == b"unrelated default installation"


def test_custom_output_collision_decline_preserves_both_directories(
    local_release, tmp_path
):
    payload, default, _, _ = local_release
    custom = tmp_path / "custom"
    custom.mkdir()
    target = custom / "tool"
    target.write_bytes(b"existing custom binary")
    result = CliRunner().invoke(
        cli.app, ["get", REPOSITORY, "--output", str(custom)], input="y\n1\ny\nn\n"
    )
    assert result.exit_code == 0, result.output
    assert target.read_bytes() == b"existing custom binary"
    assert "/tool.tar.gz" not in payload["requests"]
    assert not default.exists()
    assert not cache.state


def test_cancelled_custom_download_creates_no_output_directory(local_release, tmp_path):
    payload, _, _, _ = local_release
    custom = tmp_path / "cancelled"
    result = CliRunner().invoke(
        cli.app, ["get", REPOSITORY, "--output", str(custom)], input="y\n2\nn\n"
    )
    assert result.exit_code == 0, result.output
    assert not custom.exists()
    assert "/tool.tar.gz" not in payload["requests"]
    assert not cache.state


def test_output_file_rejected_before_fetching_release(local_release, tmp_path):
    payload, _, _, _ = local_release
    target = tmp_path / "file"
    target.write_bytes(b"preserve")
    result = CliRunner().invoke(
        cli.app, ["get", REPOSITORY, "--output", str(target), "-y"]
    )
    assert result.exit_code == 1, result.output
    assert target.read_bytes() == b"preserve"
    assert not payload["requests"]


def test_native_package_output_rejected_before_fetching(local_release, tmp_path):
    payload, _, _, _ = local_release
    target = tmp_path / "native"
    result = CliRunner().invoke(
        cli.app, ["get", REPOSITORY, "--pkg", "-o", str(target), "-y"]
    )
    assert result.exit_code == 1, result.output
    assert not payload["requests"]
    assert not target.exists()
