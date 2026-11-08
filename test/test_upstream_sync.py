"""Exercise sync merges locally and privileged merge decisions without GitHub."""

import copy
import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / ".github/scripts/upstream_sync.py"
spec = importlib.util.spec_from_file_location("upstream_sync", SCRIPT)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def git(root, *args):
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def repositories(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    origin = tmp_path / "origin.git"
    upstream = tmp_path / "upstream.git"
    for bare in (origin, upstream):
        git(tmp_path, "init", "--bare", "-b", "main", str(bare))
    writer = tmp_path / "writer"
    writer.mkdir()
    git(writer, "init", "-b", "main")
    git(writer, "config", "user.name", "Fixture")
    git(writer, "config", "user.email", "fixture@example.invalid")
    (writer / "shared").write_text("base\n")
    git(writer, "add", ".")
    git(writer, "commit", "-m", "Initial")
    base = git(writer, "rev-parse", "HEAD")
    git(writer, "remote", "add", "origin", str(origin))
    git(writer, "remote", "add", "upstream", str(upstream))
    git(writer, "push", "origin", "main")
    git(writer, "push", "upstream", "main")
    (writer / "fork-only").write_text("fork changes\n")
    git(writer, "add", ".")
    git(writer, "commit", "-m", "Fork changes")
    git(writer, "push", "origin", "main")
    runner = tmp_path / "runner"
    git(tmp_path, "clone", str(origin), str(runner))
    git(runner, "config", "user.name", "Sync")
    git(runner, "config", "user.email", "sync@example.invalid")
    git(writer, "switch", "-c", "upstream-work", base)
    monkeypatch.chdir(runner)

    def publish(filename="upstream-only", contents="upstream changes\n"):
        (writer / filename).write_text(contents)
        git(writer, "add", ".")
        git(writer, "commit", "-m", "Upstream changes")
        git(writer, "push", "upstream", "HEAD:main")
        return git(writer, "rev-parse", "HEAD")

    return origin, upstream, writer, runner, publish


def test_no_upstream_changes_do_not_create_sync_branch(repositories):
    _, upstream, _, runner, _ = repositories
    assert sync.prepare_branch(str(upstream), "main") is None
    assert git(runner, "branch", "--show-current") == "main"


def test_merge_preserves_fork_and_upstream_ancestry_without_pushing_main(repositories):
    origin, upstream, _, runner, publish = repositories
    main_before = git(origin, "rev-parse", "main")
    upstream_sha = publish()
    head, imported = sync.prepare_branch(str(upstream), "main")
    assert imported == upstream_sha
    assert (runner / "fork-only").read_text() == "fork changes\n"
    assert (runner / "upstream-only").read_text() == "upstream changes\n"
    git(runner, "merge-base", "--is-ancestor", main_before, head)
    git(runner, "merge-base", "--is-ancestor", upstream_sha, head)
    assert git(origin, "rev-parse", "main") == main_before
    assert len(git(runner, "show", "-s", "--format=%P", head).split()) == 2


def test_pending_sync_branch_is_updated_without_rewriting_its_history(repositories):
    origin, upstream, writer, runner, publish = repositories
    publish()
    first, _ = sync.prepare_branch(str(upstream), "main")
    git(runner, "push", "origin", "HEAD:sync/upstream")
    git(writer, "switch", "main")
    (writer / "fork-next").write_text("next fork change")
    git(writer, "add", ".")
    git(writer, "commit", "-m", "More fork changes")
    git(writer, "push", "origin", "main")
    latest_main = git(origin, "rev-parse", "main")
    git(writer, "switch", "upstream-work")
    latest_upstream = publish("upstream-next", "next upstream change")
    head, _ = sync.prepare_branch(str(upstream), "main")
    for ancestor in (first, latest_main, latest_upstream):
        git(runner, "merge-base", "--is-ancestor", ancestor, head)
    git(runner, "push", "origin", "HEAD:sync/upstream")


def test_conflicting_merge_stops_without_changing_remote_branches(repositories):
    origin, upstream, writer, runner, publish = repositories
    git(writer, "switch", "main")
    (writer / "shared").write_text("fork version\n")
    git(writer, "add", ".")
    git(writer, "commit", "-m", "Fork edits shared file")
    git(writer, "push", "origin", "main")
    before = git(origin, "show-ref")
    git(writer, "switch", "upstream-work")
    publish("shared", "conflicting upstream version\n")
    with pytest.raises(RuntimeError, match="resolve merge conflicts manually"):
        sync.prepare_branch(str(upstream), "main")
    assert git(origin, "show-ref") == before
    assert not git(runner, "status", "--porcelain")


@pytest.fixture
def merge_context(monkeypatch):
    repository, app = "owner/fork", "sync-app"
    pr = {
        "number": 7,
        "state": "open",
        "draft": False,
        "user": {"login": "sync-app[bot]"},
        "html_url": "https://example.invalid/pr/7",
        "head": {
            "sha": "tested-head",
            "ref": "sync/upstream",
            "repo": {"full_name": repository},
        },
        "base": {"ref": "main", "repo": {"full_name": repository}},
    }
    run = {
        "id": 123,
        "conclusion": "success",
        "status": "completed",
        "event": "pull_request",
        "head_branch": "sync/upstream",
        "head_repository": {"full_name": repository},
        "head_sha": "tested-head",
        "path": ".github/workflows/test.yml",
        "run_attempt": 1,
    }
    current = copy.deepcopy(run)
    comparison = {"merge_base_commit": {"sha": "latest-main"}}
    writes = []

    def api(endpoint, *, method="GET", **fields):
        if method != "GET":
            writes.append((endpoint, method, fields))
            return {"merged": True}
        if endpoint.endswith("/pulls"):
            return [pr]
        if endpoint.endswith("/pulls/7"):
            return pr
        if endpoint.endswith("/actions/runs/123"):
            return current
        if endpoint.endswith("/git/ref/heads/main"):
            return {"object": {"sha": "latest-main"}}
        if "/compare/" in endpoint:
            return comparison
        pytest.fail(f"Unexpected API call: {endpoint}")

    monkeypatch.setattr(sync, "api", api)
    return repository, app, pr, run, current, comparison, writes


def test_merge_uses_exact_successful_head_and_merge_commit(merge_context):
    repo, app, _, run, _, _, writes = merge_context
    sync.merge(repo, app, {"workflow_run": run})
    assert writes == [
        (
            f"repos/{repo}/pulls/7/merge",
            "PUT",
            {"sha": "tested-head", "merge_method": "merge"},
        )
    ]


@pytest.mark.parametrize(
    "problem",
    [
        "failed",
        "foreign-run",
        "wrong-branch",
        "manual-ci",
        "head-moved",
        "foreign-pr",
        "human-pr",
        "draft",
        "wrong-base",
        "rerun-failed",
        "rerun-pending",
        "old-attempt",
        "wrong-workflow",
        "main-advanced",
    ],
)
def test_unsafe_or_stale_ci_never_merges(merge_context, problem):
    repo, app, pr, run, current, comparison, writes = merge_context
    if problem == "failed":
        run["conclusion"] = "failure"
    elif problem == "foreign-run":
        run["head_repository"]["full_name"] = "other/fork"
    elif problem == "wrong-branch":
        run["head_branch"] = "feature"
    elif problem == "manual-ci":
        run["event"] = "workflow_dispatch"
    elif problem == "head-moved":
        pr["head"]["sha"] = "untested-head"
    elif problem == "foreign-pr":
        pr["head"]["repo"]["full_name"] = "other/fork"
    elif problem == "human-pr":
        pr["user"]["login"] = "human"
    elif problem == "draft":
        pr["draft"] = True
    elif problem == "wrong-base":
        pr["base"]["ref"] = "release"
    elif problem == "rerun-failed":
        current["conclusion"] = "failure"
    elif problem == "rerun-pending":
        current["status"] = "in_progress"
    elif problem == "old-attempt":
        current["run_attempt"] = 2
    elif problem == "wrong-workflow":
        current["path"] = ".github/workflows/other.yml"
    elif problem == "main-advanced":
        comparison["merge_base_commit"]["sha"] = "older-main"
    sync.merge(repo, app, {"workflow_run": run})
    assert not writes


def test_missing_sync_pr_does_not_merge(merge_context, monkeypatch):
    repo, app, _, run, _, _, writes = merge_context
    monkeypatch.setattr(sync, "open_pr", lambda repository: None)
    sync.merge(repo, app, {"workflow_run": run})
    assert not writes


@pytest.mark.parametrize("has_passing_ci", [False, True])
def test_sync_opens_pr_and_recovers_previously_completed_ci(
    merge_context, monkeypatch, has_passing_ci
):
    repo, app, pr, run, _, _, _ = merge_context
    monkeypatch.setenv("UPSTREAM_REPOSITORY", "owner/upstream")
    monkeypatch.setenv("UPSTREAM_BRANCH", "main")
    monkeypatch.setattr(
        sync, "prepare_branch", lambda *a: ("tested-head", "upstream-head")
    )
    commands, writes, merges = [], [], []
    monkeypatch.setattr(sync, "git", lambda *a, **kw: commands.append(a))
    monkeypatch.setattr(sync, "merge", lambda *a: merges.append(a))

    def api(endpoint, *, method="GET", **fields):
        if method == "POST":
            writes.append((endpoint, fields))
            return pr
        if endpoint.endswith("/pulls"):
            return []
        if endpoint.endswith("/actions/workflows/test.yml/runs"):
            return {"workflow_runs": [run] if has_passing_ci else []}
        pytest.fail(f"Unexpected API call: {endpoint}")

    monkeypatch.setattr(sync, "api", api)
    sync.sync(repo, app)
    assert ("push", "origin", "HEAD:refs/heads/sync/upstream") in commands
    assert len(writes) == 1
    assert writes[0][1]["base"] == "main"
    assert len(merges) == int(has_passing_ci)


def test_sync_will_not_modify_another_authors_pr(merge_context, monkeypatch):
    repo, app, pr, _, _, _, _ = merge_context
    pr["user"]["login"] = "someone-else"
    monkeypatch.setenv("UPSTREAM_BRANCH", "main")
    monkeypatch.setattr(
        sync, "git", lambda *a, **kw: pytest.fail("Touched sync branch")
    )
    with pytest.raises(RuntimeError, match="not owned by this App"):
        sync.sync(repo, app)


def test_api_uses_read_token_for_reads_and_app_token_for_writes(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "read-token")
    monkeypatch.setenv("APP_TOKEN", "write-token")
    tokens = []

    def run(command, *, env, **kwargs):
        tokens.append(env["GH_TOKEN"])
        return subprocess.CompletedProcess(command, 0, stdout="{}")

    monkeypatch.setattr(sync.subprocess, "run", run)
    sync.api("repos/owner/fork")
    sync.api("repos/owner/fork/pulls/7/merge", method="PUT", sha="tested")
    assert tokens == ["read-token", "write-token"]
