"""Shared builders for terminal workspace-retention adapter tests.

Split from ``tests.turns.test_workspace_retention``. Public helpers used by
more than one split module live here under public names so no new module
imports a ``_``-prefixed name from another new module.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sase.llm_provider.commit_finalizer_baseline import FINALIZER_BASELINE_FILENAME
from sase.llm_provider.commit_finalizer_git import normalize_path
from sase.llm_provider.commit_finalizer_git_status import dirty_path_fingerprints
from sase.running_field import WorkspaceClaim
from sase.turns.workspace_retention import (
    WorkspaceRetentionOwner,
    WorkspaceRetentionRepo,
)
from sase.workspace_provider.occupant import (
    OccupantRecord,
    write_occupant_record,
)

__all__ = [
    "CL_NAME",
    "PID",
    "TIMESTAMP",
    "WORKFLOW",
    "WORKSPACE",
    "claim",
    "init_repo",
    "occupant",
    "owner",
    "write_empty_baseline",
]

WORKFLOW = "ace(run)-260101_000000"
CL_NAME = "feature"
TIMESTAMP = "20260101000000"
PID = 111
WORKSPACE = 17


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def init_repo(
    path: Path,
    *,
    tracked_dirty: bool = False,
    untracked: bool = False,
    staged: bool = False,
) -> Path:
    path.mkdir(parents=True)
    _git(path, "init")
    _git(path, "config", "user.email", "sase-test@example.invalid")
    _git(path, "config", "user.name", "SASE Test")
    (path / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(path, "add", "tracked.txt")
    _git(path, "commit", "-m", "init")
    if tracked_dirty:
        (path / "tracked.txt").write_text("session owned\n", encoding="utf-8")
    if untracked:
        (path / "untracked.txt").write_text("new file\n", encoding="utf-8")
    if staged:
        (path / "staged.txt").write_text("staged\n", encoding="utf-8")
        _git(path, "add", "staged.txt")
    return path


def write_empty_baseline(artifacts: Path, repo_id: str, repo: Path) -> None:
    artifacts.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "repositories": [
            {
                "repo_id": repo_id,
                "path": normalize_path(str(repo)),
                "kind": "primary" if repo_id == "primary" else "linked",
                "name": repo_id,
                "scope": "run_start",
                "captured_at": "2026-01-01T00:00:00+00:00",
                "fingerprints": {},
            }
        ],
    }
    (artifacts / FINALIZER_BASELINE_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )


def claim() -> WorkspaceClaim:
    return WorkspaceClaim(
        WORKSPACE,
        WORKFLOW,
        CL_NAME,
        pid=PID,
        artifacts_timestamp=TIMESTAMP,
    )


def owner(
    project_file: str,
    checkout: Path,
    artifacts: Path,
    *,
    repos: tuple[WorkspaceRetentionRepo, ...] | None = None,
) -> WorkspaceRetentionOwner:
    return WorkspaceRetentionOwner(
        project_file=project_file,
        workspace_num=WORKSPACE,
        workflow=WORKFLOW,
        cl_name=CL_NAME,
        artifacts_timestamp=TIMESTAMP,
        pid=PID,
        artifacts_dir=str(artifacts),
        checkout_dir=str(checkout),
        repos=repos
        or (
            WorkspaceRetentionRepo(
                repo_id="primary",
                path=str(checkout),
                is_primary=True,
                positive_custody=True,
            ),
        ),
        terminal_reason="stopped",
        session_id="sess-1",
        turn_id="turn-1",
    )


def occupant(checkout: Path) -> None:
    write_occupant_record(
        str(checkout),
        OccupantRecord(
            pid=PID,
            workflow=WORKFLOW,
            project="sase",
            workspace_num=WORKSPACE,
            artifacts_timestamp=TIMESTAMP,
            cl_name=CL_NAME,
            claimed_at=1.0,
        ),
    )
