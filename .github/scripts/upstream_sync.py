"""Prepare upstream-sync PRs and merge only their successfully tested heads.

Run by the trusted default-branch workflow; never execute this from PR contents
with an App token. GitHub's separate CI ruleset must have no App bypass.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

BASE = "main"
BRANCH = "sync/upstream"
CI_PATH = ".github/workflows/test.yml"


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], check=check, text=True, capture_output=True)


def api(endpoint: str, *, method: str = "GET", **fields):
    command = ["gh", "api", "--method", method, endpoint]
    for key, value in fields.items():
        command.extend(["-f", f"{key}={value}"])
    env = dict(os.environ)
    if method != "GET":
        env["GH_TOKEN"] = env["APP_TOKEN"]
    result = subprocess.run(
        command, env=env, check=True, text=True, capture_output=True
    )
    return json.loads(result.stdout)


def report(message: str) -> None:
    print(message, flush=True)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a") as handle:
            handle.write(message + "\n\n")


def open_pr(repository: str):
    pulls = api(
        f"repos/{repository}/pulls",
        state="open",
        base=BASE,
        head=f"{repository.split('/')[0]}:{BRANCH}",
    )
    if len(pulls) > 1:
        raise RuntimeError("Multiple upstream-sync PRs found; resolve them manually")
    return pulls[0] if pulls else None


def trusted_pr(pr: dict, repository: str, app_slug: str) -> bool:
    return (
        pr["state"] == "open"
        and not pr.get("draft", False)
        and pr["user"]["login"] == f"{app_slug}[bot]"
        and pr["head"]["repo"]["full_name"] == repository
        and pr["head"]["ref"] == BRANCH
        and pr["base"]["repo"]["full_name"] == repository
        and pr["base"]["ref"] == BASE
    )


def prepare_branch(upstream_url: str, upstream_branch: str) -> tuple[str, str] | None:
    """Merge in an isolated CI checkout, leaving origin/main untouched."""
    git("fetch", "origin", f"+refs/heads/{BASE}:refs/remotes/origin/{BASE}")
    git("fetch", upstream_url, f"refs/heads/{upstream_branch}")
    upstream_sha = git("rev-parse", "FETCH_HEAD").stdout.strip()
    contains = git(
        "merge-base", "--is-ancestor", upstream_sha, f"origin/{BASE}", check=False
    )
    if contains.returncode == 0:
        return None
    if contains.returncode != 1:
        raise RuntimeError(contains.stderr)

    remote_branch = git(
        "ls-remote", "--exit-code", "--heads", "origin", BRANCH, check=False
    )
    if remote_branch.returncode == 0:
        git("fetch", "origin", f"+refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}")
        start = f"origin/{BRANCH}"
    elif remote_branch.returncode == 2:
        start = f"origin/{BASE}"
    else:
        raise RuntimeError(remote_branch.stderr)
    git("checkout", "-B", BRANCH, start)
    for args in (
        ("--no-edit", f"origin/{BASE}"),
        ("--no-ff", "--no-edit", upstream_sha),
    ):
        merged = git("merge", *args, check=False)
        if merged.returncode:
            git("merge", "--abort", check=False)
            raise RuntimeError(
                "Upstream sync stopped: resolve merge conflicts manually.\n"
                + merged.stdout
                + merged.stderr
            )
    return git("rev-parse", "HEAD").stdout.strip(), upstream_sha


def sync(repository: str, app_slug: str) -> None:
    upstream = os.environ.get("UPSTREAM_REPOSITORY") or "Rishang/install-release"
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", upstream):
        raise ValueError("UPSTREAM_REPOSITORY must be owner/repository")
    upstream_branch = (
        os.environ.get("UPSTREAM_BRANCH") or api(f"repos/{upstream}")["default_branch"]
    )
    pr = open_pr(repository)
    if pr and not trusted_pr(pr, repository, app_slug):
        raise RuntimeError("The sync PR is not owned by this App; inspect it manually")
    git("config", "user.name", f"{app_slug}[bot]")
    git("config", "user.email", f"{app_slug}[bot]@users.noreply.github.com")
    result = prepare_branch(f"https://github.com/{upstream}.git", upstream_branch)
    if result is None:
        report("Upstream is already included in main; no changes to synchronize.")
        return
    head_sha, upstream_sha = result
    git("push", "origin", f"HEAD:refs/heads/{BRANCH}")
    if pr is None:
        pr = api(
            f"repos/{repository}/pulls",
            method="POST",
            base=BASE,
            head=BRANCH,
            title=f"Sync upstream changes from {upstream}",
            body=(
                f"Merge upstream [{upstream}@{upstream_sha[:12]}]"
                f"(https://github.com/{upstream}/commit/{upstream_sha}) into `{BASE}`.\n\n"
                "CI must pass before the App merges this PR. Conflicts require manual resolution."
            ),
        )
    report(
        f"Upstream sync PR: {pr['html_url']} (head `{head_sha}`). Waiting for Test CLI."
    )
    # Recover if CI completed before this workflow was enabled, or its merge
    # event was missed. A still-running or failed run never qualifies.
    runs = api(
        f"repos/{repository}/actions/workflows/test.yml/runs",
        head_sha=head_sha,
        event="pull_request",
        per_page="1",
    )["workflow_runs"]
    if runs and runs[0]["status"] == "completed" and runs[0]["conclusion"] == "success":
        merge(repository, app_slug, {"workflow_run": runs[0]})


def merge(repository: str, app_slug: str, event: dict) -> None:
    run = event.get("workflow_run", {})
    if not (
        run.get("conclusion") == "success"
        and run.get("event") == "pull_request"
        and run.get("head_branch") == BRANCH
        and run.get("head_repository", {}).get("full_name") == repository
    ):
        report("Ignoring CI event outside the upstream-sync PR.")
        return
    pr = open_pr(repository)
    if not pr or not trusted_pr(pr, repository, app_slug):
        report("No matching open PR owned by this App; nothing merged.")
        return
    # Fetch fresh PR/run details rather than trusting a delayed event payload.
    pr = api(f"repos/{repository}/pulls/{pr['number']}")
    current_run = api(f"repos/{repository}/actions/runs/{run['id']}")
    head_sha = pr["head"]["sha"]
    if not (
        trusted_pr(pr, repository, app_slug)
        and head_sha == run["head_sha"] == current_run["head_sha"]
        and current_run["path"] == CI_PATH
        and current_run["event"] == "pull_request"
        and current_run["head_branch"] == BRANCH
        and current_run["head_repository"]["full_name"] == repository
        and current_run["status"] == "completed"
        and current_run["conclusion"] == "success"
        and current_run["run_attempt"] == run["run_attempt"]
    ):
        report("CI does not match the current PR head and attempt; nothing merged.")
        return
    base_sha = api(f"repos/{repository}/git/ref/heads/{BASE}")["object"]["sha"]
    comparison = api(f"repos/{repository}/compare/{base_sha}...{head_sha}")
    if comparison["merge_base_commit"]["sha"] != base_sha:
        report(
            "Main has advanced; run Sync upstream again to update the PR and rerun CI."
        )
        return
    # No --admin or rule changes. The App may bypass ONLY the separate linear
    # history ruleset. GitHub still enforces all other required checks/reviews.
    result = api(
        f"repos/{repository}/pulls/{pr['number']}/merge",
        method="PUT",
        sha=head_sha,
        merge_method="merge",
    )
    if not result.get("merged"):
        raise RuntimeError(
            f"GitHub declined the merge: {result.get('message', 'unknown reason')}"
        )
    report(f"Merged tested upstream sync: {pr['html_url']}")


def main() -> None:
    repository = os.environ["GITHUB_REPOSITORY"]
    app_slug = os.environ["APP_SLUG"]
    if sys.argv[1:] == ["sync"]:
        sync(repository, app_slug)
    elif sys.argv[1:] == ["merge"]:
        merge(
            repository,
            app_slug,
            json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text()),
        )
    else:
        raise ValueError("Usage: upstream_sync.py sync|merge")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            print(exc.stderr, file=sys.stderr)
        sys.exit(str(exc))
