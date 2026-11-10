import json
import subprocess
import time

import pytest

from InstallRelease import update_notice


@pytest.fixture(autouse=True)
def notice_state(monkeypatch, tmp_path):
    monkeypatch.setenv("IRP_STATE_DIR", str(tmp_path))
    (tmp_path / "state.json").write_text("{}")


@pytest.mark.parametrize("count", [1, 2])
def test_banner_uses_cached_count_and_correct_grammar(count):
    update_notice.save_snapshot([{"update_status": "available"}] * count)
    banner = update_notice.banner()
    assert f"{count} IRP update{' is' if count == 1 else 's are'} available." in banner
    assert "irp ls" in banner and "irp upgrade" in banner
    assert "Last checked:" in banner


def test_current_and_held_releases_have_no_banner():
    update_notice.save_snapshot(
        [{"update_status": "current"}, {"update_status": "held"}]
    )
    assert update_notice.banner() == ""


def test_rate_limit_does_not_claim_packages_are_current():
    update_notice.save_snapshot(
        [{"update_status": "unavailable", "update_error": "rate_limit"}]
    )
    banner = update_notice.banner()
    assert "API rate limit" in banner
    assert "irp ls" in banner
    assert "updates are available" not in banner


def test_changed_installations_invalidate_old_counts(tmp_path):
    update_notice.save_snapshot([{"update_status": "available"}])
    (tmp_path / "state.json").write_text('{"changed": true}')
    assert update_notice.banner() == ""


def test_notification_prints_cache_and_refreshes_without_waiting(monkeypatch, capsys):
    update_notice.save_snapshot([{"update_status": "available"}])
    children = []
    monkeypatch.setattr(
        update_notice.subprocess, "Popen", lambda *a, **kw: children.append((a, kw))
    )
    update_notice.notify("/some path/irp")
    assert "1 IRP update is available" in capsys.readouterr().out
    assert len(children) == 1
    args, options = children[0]
    assert args[0][-2:] == ["--refresh", "/some path/irp"]
    assert options["stdout"] == subprocess.DEVNULL
    assert options["stderr"] == subprocess.DEVNULL
    assert options["start_new_session"]


def test_refresh_replaces_snapshot_with_new_results(monkeypatch):
    update_notice.save_snapshot([{"update_status": "available"}])

    def run(argv, **options):
        assert argv == ["/bin/irp", "ls", "--json"]
        assert options["timeout"] == 30
        return subprocess.CompletedProcess(
            argv, 0, json.dumps([{"update_status": "current"}])
        )

    monkeypatch.setattr(update_notice.subprocess, "run", run)
    update_notice.refresh("/bin/irp")
    assert update_notice.banner() == ""


def test_timed_out_refresh_replaces_stale_upgrade_claim(monkeypatch):
    update_notice.save_snapshot([{"update_status": "available"}])

    def run(*args, **options):
        raise subprocess.TimeoutExpired("irp", 30)

    monkeypatch.setattr(update_notice.subprocess, "run", run)
    update_notice.refresh("/bin/irp")
    assert "timed out" in update_notice.banner()
    assert "1 IRP update is available" not in update_notice.banner()


def test_rate_limit_backoff_ends_when_authentication_changes(monkeypatch, tmp_path):
    update_notice.save_snapshot(
        [
            {
                "update_status": "unavailable",
                "update_error": "rate_limit",
                "update_retry_at": time.time() + 3600,
            }
        ]
    )
    calls = []
    monkeypatch.setattr(
        update_notice.subprocess,
        "run",
        lambda *a, **kw: calls.append(a) or subprocess.CompletedProcess(a, 0, "[]"),
    )
    update_notice.refresh("/bin/irp")
    assert not calls
    (tmp_path / "config.json").write_text('{"config": {"token": "test-only"}}')
    update_notice.refresh("/bin/irp")
    assert len(calls) == 1


def test_overlapping_shells_share_one_refresh(monkeypatch):
    import fcntl

    path = update_notice.cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        monkeypatch.setattr(
            update_notice.subprocess,
            "run",
            lambda *a, **kw: pytest.fail("Duplicate request"),
        )
        update_notice.refresh("/bin/irp")


@pytest.mark.parametrize("content", [None, "not json", "[]"])
def test_missing_or_corrupt_cache_never_breaks_shell_startup(
    monkeypatch, capsys, content
):
    if content is not None:
        update_notice.cache_path().write_text(content)
    children = []
    monkeypatch.setattr(
        update_notice.subprocess, "Popen", lambda *a, **kw: children.append(a)
    )
    update_notice.notify("/bin/irp")
    assert capsys.readouterr().out == ""
    assert len(children) == 1


def test_state_changed_during_refresh_cannot_publish_a_stale_count(
    monkeypatch, tmp_path
):
    def run(argv, **options):
        (tmp_path / "state.json").write_text('{"upgraded": true}')
        return subprocess.CompletedProcess(argv, 0, '[{"update_status":"available"}]')

    monkeypatch.setattr(update_notice.subprocess, "run", run)
    update_notice.refresh("/bin/irp")
    assert not update_notice.cache_path().exists()
