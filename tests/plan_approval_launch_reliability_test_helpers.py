"""Shared fixtures and helpers for plan-approval-to-launch reliability tests."""

from __future__ import annotations

import json
import os
import select
import subprocess
import time
from pathlib import Path

import pytest

from sase.bead.cli_work_from_plan import work_from_plan_file
from sase.llm_provider.commit_finalizer_git import normalize_path
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.sdd._artifact_link_commit import commit_artifact_link_indexes
from sase.sdd._artifact_link_store_support import sidecar_index_path
from sase.sdd.artifact_link_store import ARTIFACT_LINK_ROW_SCHEMA_VERSION
from tests.sdd_store._helpers import clone, commit_all, git, init_bare_repo
from tests.test_bead.cli_work_from_plan_helpers import write_plan_update

MONTH = "202608"
PLAN_STEM = "family_shell_metadata"
HOST_CREATE_TIME = "2026-08-22 11:33:24"
RUNNER_CREATE_TIME = "2026-08-22 11:33:26"
WAITING_NEEDLE = "waiting for the source-tree swap to finish"


def archived_tale(create_time: str) -> str:
    return (
        "---\n"
        "tier: tale\n"
        "title: Approved implementation\n"
        "goal: Deliver the approved implementation\n"
        "size: small\n"
        f"create_time: {create_time}\n"
        "status: wip\n"
        "---\n"
        "# Plan\n"
        "\n"
        "Implement the requested change.\n"
    )


def plans_sidecar(tmp_path: Path) -> tuple[Path, Path, Path]:
    origin = tmp_path / "plans.git"
    init_bare_repo(origin)
    seed = tmp_path / "plans-seed"
    clone(origin, seed)
    (seed / "README.md").write_text("plans\n", encoding="utf-8")
    commit_all(seed, "init plans")
    git(["push", "-u", "origin", "main"], seed)
    host = tmp_path / "host-plans"
    runner = tmp_path / "runner-plans"
    clone(origin, host)
    clone(origin, runner)
    return origin, host, runner


def git_output(args: list[str], cwd: Path) -> str:
    return git(args, cwd).stdout.strip()


def log_subjects(repo: Path) -> list[str]:
    log = git_output(["log", "--pretty=%s", "HEAD"], repo)
    return [line for line in log.splitlines() if line]


def assert_linear_history(repo: Path) -> None:
    rows = git_output(["rev-list", "--parents", "HEAD"], repo).splitlines()
    assert rows
    for row in rows:
        parts = row.split()
        assert len(parts) <= 2, f"merge commit in {repo}: {row}"


def link_row(plan_ref: str) -> dict[str, object]:
    return {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "source_ref": "agent:planner.coder",
        "relation": "read",
        "target_ref": plan_ref,
        "description": "Coder consumed the canonical approved plan",
        "origin": "read",
        "created_by": "planner.coder",
        "created_at": "2026-08-22T11:34:00Z",
        "uses": 1,
    }


def write_link_index(repo: Path, plan_ref: str) -> Path:
    path = sidecar_index_path(repo, plan_ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "artifact_ref": plan_ref,
        "rows": [link_row(plan_ref)],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def commit_link_index(repo: Path, index: Path) -> None:
    result = commit_artifact_link_indexes(
        [index],
        repo_roots=(repo,),
        push_after_commit=False,
        verify_publication=False,
    )
    assert result.committed is True
    git(["push"], repo)


def dirty_state(repo: Path, changed: tuple[str, ...]) -> DirtyState:
    path = normalize_path(str(repo))
    return DirtyState(
        project_dir=path,
        repos=(
            DirtyRepo(
                name="plans",
                path=path,
                changed_files=changed,
                kind="sdd",
            ),
        ),
        details="",
    )


def clean_state(repo: Path) -> DirtyState:
    return DirtyState(
        project_dir=normalize_path(str(repo)),
        repos=(),
        details="",
    )


def rebase_onto_origin(repo: Path) -> subprocess.CompletedProcess[str]:
    git(["fetch", "origin"], repo)
    return subprocess.run(
        ["git", "rebase", "origin/main"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def readline_until(
    proc: subprocess.Popen[str], needle: str, *, timeout: float
) -> str | None:
    stream = proc.stdout
    if stream is None:
        return None
    deadline = time.monotonic() + timeout
    buf = ""
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        ready, _, _ = select.select([stream], [], [], max(0.0, remaining))
        if not ready:
            continue
        chunk = stream.readline()
        if chunk == "":
            return None
        buf += chunk
        if needle in buf:
            return buf
    return None


def install_fake_sase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    marker = tmp_path / "created.json"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_sase = fake_bin / "sase"
    fake_sase.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, pathlib, sys",
                f"path = pathlib.Path({str(marker)!r})",
                "path.write_text(json.dumps(sys.argv))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_sase.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    return marker


def create_one_epic_dag(plan: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._commit_plan_file",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._write_and_commit_plan_file",
        write_plan_update,
    )
    launches: list[str] = []
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda _project, epic_id, **_kwargs: not launches.append(epic_id),
    )
    monkeypatch.setattr(
        "sase.file_references.format_with_prettier",
        lambda content: content,
    )
    result = work_from_plan_file(
        str(plan),
        dry_run=False,
        yes=True,
        no_push=True,
        render=False,
    )
    assert result.epic_id is not None
    assert launches == [result.epic_id]
    return result.epic_id
