import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest
import requests
from typer.testing import CliRunner

from InstallRelease import cli, cli_interact
from InstallRelease.config import cache
from InstallRelease.providers.git.schemas import Release


def release(url, tag="v1", **kwargs):
    return Release(
        url=url,
        name="tool",
        tag_name=tag,
        prerelease=False,
        published_at="2026-01-01T00:00:00Z" if tag == "v1" else "2026-02-01T00:00:00Z",
        assets=[],
        **kwargs,
    )


@pytest.fixture
def projects(monkeypatch, tmp_path):
    state = {}
    for owner, options in {
        "alice": {},
        "bob": {"install_method": "download"},
        "current": {},
        "held": {"hold_update": True},
        "offline": {},
    }.items():
        url = f"https://github.com/{owner}/tool"
        state[f"{url}#tool"] = release(url, **options)
    monkeypatch.setattr(cache, "state", state)
    monkeypatch.setattr(cache, "state_file", str(tmp_path / "state.json"))
    cache.save()
    fetched = []

    def repo(url, **kwargs):
        fetched.append(url)
        assert "/held/" not in url, "Fetched a held item"
        if "/offline/" in url:
            # Real providers can log to stdout before raising. JSON must remain parseable.
            print("Repository request failed")
            raise OSError("offline")
        latest = release(url, "v1" if "/current/" in url else "v2")
        return SimpleNamespace(repo_url=url, release=lambda **kw: [latest])

    monkeypatch.setattr(cli_interact, "get_repo_info", repo)
    return state, fetched


def test_ls_json_checks_releases_without_changing_state_or_config(projects):
    state, fetched = projects
    before = {key: asdict(value) for key, value in state.items()}
    config_before = dict(vars(cli_interact.config))
    with open(cache.state_file, "rb") as handle:
        saved = handle.read()
    result = CliRunner().invoke(cli.app, ["ls", "--json"])
    assert result.exit_code == 0, result.output
    rows = {row["url"].split("/")[-2]: row for row in json.loads(result.output)}
    assert rows["alice"]["update_status"] == "available"
    assert rows["bob"]["latest_version"] == "v2"
    assert rows["current"]["update_status"] == "current"
    assert rows["held"]["update_status"] == "held"
    assert rows["held"]["latest_version"] is None
    assert rows["offline"]["update_status"] == "unavailable"
    assert rows["offline"]["latest_version"] is None
    assert len(fetched) == 4
    assert {key: asdict(value) for key, value in state.items()} == before
    assert vars(cli_interact.config) == config_before
    with open(cache.state_file, "rb") as handle:
        assert handle.read() == saved


def test_ls_table_shows_updates_but_uses_hold_column(projects):
    result = CliRunner().invoke(cli.app, ["ls"], env={"COLUMNS": "240"})
    assert result.exit_code == 0, result.output
    assert "Update available: v2" in result.output
    assert "Up to date" not in result.output
    assert "Update check unavailable" in result.output
    assert "Updates on hold" not in result.output
    assert "Hold" in result.output
    assert "2 updates available" in result.output


@pytest.mark.parametrize("answer", ["n\n", "\n", "y\n"])
def test_upgrade_shows_versions_and_sources_before_confirming(
    projects, monkeypatch, answer
):
    calls = []
    monkeypatch.setattr(cli_interact, "get", lambda *a, **kw: calls.append("binary"))
    monkeypatch.setattr(
        cli_interact, "download_release", lambda *a, **kw: calls.append("download")
    )
    result = CliRunner().invoke(
        cli.app, ["upgrade"], input=answer, env={"COLUMNS": "180"}
    )
    assert result.exit_code == 0, result.output
    assert "Installed" in result.output and "Available" in result.output
    assert "v1" in result.output and "v2" in result.output
    assert "alice/tool" in result.output and "bob/tool" in result.output
    assert "2 to upgrade, 1 held" in result.output
    assert result.output.index("Available") < result.output.index("Continue?")
    assert calls == (["binary", "download"] if answer == "y\n" else [])


def test_unavailable_checks_do_not_claim_everything_is_current(projects, monkeypatch):
    state, _ = projects
    key = next(key for key in state if "/offline/" in key)
    monkeypatch.setattr(cache, "state", {key: state[key]})
    result = CliRunner().invoke(cli.app, ["upgrade"])
    assert result.exit_code == 0, result.output
    assert "unavailable" in result.output.lower()
    assert "All tools are onto latest version" not in result.output


def test_ls_hold_skips_all_remote_checks(projects):
    _, fetched = projects
    result = CliRunner().invoke(cli.app, ["ls", "--hold", "--json"])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.output)) == 1
    assert not fetched


def test_ls_refreshes_banner_cache_but_hold_filter_preserves_it(projects):
    from InstallRelease.update_notice import cache_path

    runner = CliRunner()
    result = runner.invoke(cli.app, ["ls", "--json"])
    assert result.exit_code == 0, result.output
    snapshot = cache_path().read_bytes()
    assert (
        sum(row["update_status"] == "available" for row in json.loads(snapshot)["rows"])
        == 2
    )
    assert runner.invoke(cli.app, ["ls", "--hold", "--json"]).exit_code == 0
    assert cache_path().read_bytes() == snapshot


@pytest.mark.parametrize("limited_on", ["metadata", "release"])
def test_rate_limits_explain_unavailable_checks(monkeypatch, limited_on):
    url = "https://github.com/owner/tool"
    monkeypatch.setattr(cache, "state", {f"{url}#tool": release(url)})

    def request(api, **kwargs):
        response = requests.Response()
        response.url = api
        limited = limited_on == "metadata" or api.endswith("/releases/latest")
        response.status_code = 403 if limited else 200
        response._content = json.dumps(
            {"message": "API rate limit exceeded"}
            if limited
            else {
                "name": "tool",
                "full_name": "owner/tool",
                "description": "",
                "stargazers_count": 1,
                "language": "Python",
            }
        ).encode()
        if limited:
            response.headers["x-ratelimit-remaining"] = "0"
        return response

    monkeypatch.setattr(requests, "get", request)
    runner = CliRunner()
    result = runner.invoke(cli.app, ["ls", "--json"])
    assert result.exit_code == 0, result.output
    row = json.loads(result.output)[0]
    assert row["update_status"] == "unavailable"
    assert row["update_error"] == "rate_limit"
    result = runner.invoke(cli.app, ["ls"])
    assert "rate limit" in result.output.lower()
    assert "--github-token" in result.output


def test_self_hosted_listing_does_not_register_hosts(monkeypatch):
    from InstallRelease.providers.git import main

    url = "gitlab@new.example/owner/tool"
    monkeypatch.setattr(cache, "state", {f"{url}#tool": release(url)})
    monkeypatch.setattr(main.config, "gitlab_token", {})
    monkeypatch.setattr(
        main.cache_config, "save", lambda: pytest.fail("Listing saved config")
    )
    _cls, token = main._PROVIDER_CLASSES["gitlab_self"]

    def offline(*args):
        raise OSError("unreachable")

    monkeypatch.setitem(main._PROVIDER_CLASSES, "gitlab_self", (offline, token))
    result = CliRunner().invoke(cli.app, ["ls", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)[0]["update_status"] == "unavailable"
    assert main.config.gitlab_token == {}


@pytest.mark.parametrize("answer", ["n\n", "y\n"])
def test_native_packages_confirm_before_sudo_and_download(
    projects, monkeypatch, answer
):
    state, _ = projects
    key = next(key for key in state if "/alice/" in key)
    state[key].install_method = "package"
    state[key].package_type = "deb"
    monkeypatch.setattr(cache, "state", {key: state[key]})
    calls = []
    monkeypatch.setattr(cli_interact, "get", lambda *a, **kw: calls.append("download"))

    def sudo(*args, **kwargs):
        calls.append("sudo")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli_interact, "sh", sudo)
    result = CliRunner().invoke(cli.app, ["upgrade"])
    assert result.exit_code == 0, result.output
    assert "irp upgrade --pkg" in result.output
    assert not calls
    result = CliRunner().invoke(cli.app, ["upgrade", "--pkg"], input=answer)
    assert result.exit_code == 0, result.output
    assert "Continue?" in result.output
    assert calls == (["sudo", "download"] if answer == "y\n" else [])


@pytest.mark.parametrize(
    "available, status",
    [(True, "available"), (False, "current"), (None, "unavailable")],
)
def test_docker_listing_distinguishes_failed_checks(monkeypatch, available, status):
    url = "docker:owner/tool"
    monkeypatch.setattr(cache, "state", {f"{url}#tool": release(url, "latest")})
    monkeypatch.setattr(cli_interact, "docker_needs_update", lambda *a, **kw: available)
    result = CliRunner().invoke(cli.app, ["ls", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)[0]["update_status"] == status


@pytest.mark.parametrize(
    "versions, status",
    [(["v2"], "available"), (["v1"], "current"), ([], "unavailable")],
)
def test_mise_listing_uses_resolved_versions(monkeypatch, versions, status):
    url = "mise:tool"
    monkeypatch.setattr(cache, "state", {f"{url}#tool": release(url)})
    monkeypatch.setattr(
        cli_interact.MiseInteractProvider, "resolve", lambda *a, **kw: versions
    )
    result = CliRunner().invoke(cli.app, ["ls", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)[0]["update_status"] == status


@pytest.mark.parametrize(
    "remote, expected", [("sha256:old", False), ("sha256:new", True), ("", None)]
)
def test_docker_digest_checks_preserve_unknown_status(monkeypatch, remote, expected):
    from InstallRelease.providers.docker import main

    monkeypatch.setattr(main, "_get_local_digest", lambda ref: "sha256:old")
    monkeypatch.setattr(main, "_get_remote_digest", lambda ref: remote)
    assert main.needs_update("owner/tool", "latest") is expected
