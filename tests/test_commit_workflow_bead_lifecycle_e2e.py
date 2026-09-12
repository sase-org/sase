"""Subprocess coverage for explicit bead actions against a real bead store."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from sase.bead.model import BeadTier, Issue, IssueType, Resolution, Status
from sase.bead.project import BeadProject
from tests.finalizers_live_e2e_test_helpers import (
    attach_bare_remote,
    init_live_repo,
    run_git,
)


def _seed_phase_beads(repo: Path) -> tuple[str, str, str]:
    with BeadProject.init(repo) as project:
        epic = project.create(
            "Lifecycle epic",
            IssueType.PLAN,
            tier=BeadTier.EPIC,
        )
        phase = project.create(
            "Lifecycle phase",
            IssueType.PHASE,
            parent_id=epic.id,
        )
        dependent = project.create(
            "Dependent phase",
            IssueType.PHASE,
            parent_id=epic.id,
        )
        project.add_dependency(dependent.id, phase.id)
        project.update(
            phase.id,
            status=Status.IN_PROGRESS.value,
            assignee=phase.id,
        )
    run_git(repo, "add", "sdd")
    run_git(repo, "commit", "-q", "-m", "seed beads")
    run_git(repo, "push", "-q", "origin", "HEAD")
    return epic.id, phase.id, dependent.id


def _subprocess_env(
    base_env: dict[str, str],
    tmp_path: Path,
    repo: Path,
    bead_id: str,
) -> dict[str, str]:
    env = dict(base_env)
    for key in tuple(env):
        if key.startswith(("SASE_LINKED_REPO_", "SASE_SIBLING_REPO_")):
            env.pop(key, None)
    for key in (
        "CLAUDE_PROJECT_DIR",
        "GEMINI_PROJECT_DIR",
        "OPENCODE_PROJECT_DIR",
        "QWEN_PROJECT_DIR",
        "SASE_ACTIVE_PROJECT_DIR",
        "SASE_AGENT_NAME",
        "SASE_COMMIT_METHOD",
        "SASE_COMMIT_METHOD_ALLOW_OVERRIDE",
        "SASE_GIT_WORKSPACE_DIR",
        "SASE_SDD_BEADS_DIR",
        "SASE_SDD_DIR",
        "SASE_SDD_PLANS_DIR",
        "SASE_SDD_RESEARCH_DIR",
    ):
        env.pop(key, None)
    env.update(
        {
            "CODEX_PROJECT_DIR": str(repo),
            "HOME": str(tmp_path / "home"),
            "SASE_AGENT_TIMESTAMP": "run-bead-lifecycle",
            "SASE_ARTIFACTS_DIR": str(tmp_path / "artifacts"),
            "SASE_BEAD_ID": bead_id,
            "SASE_HOME": str(tmp_path / "sase-home"),
        }
    )
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    return env


def _run_stitch(
    repo: Path,
    tmp_path: Path,
    bead_id: str,
    message: str,
    *,
    action: str | None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    message_file = repo / ".sase" / "commit-message.md"
    message_file.parent.mkdir(exist_ok=True)
    message_file.write_text(message, encoding="utf-8")
    argv = [
        sys.executable,
        "-m",
        "sase",
        "stitch",
        "create",
        "-M",
        str(message_file),
    ]
    if action is not None:
        argv.extend(["-B", action])
    completed = subprocess.run(
        argv,
        cwd=repo,
        env=_subprocess_env(dict(os.environ), tmp_path, repo, bead_id),
        capture_output=True,
        text=True,
        check=False,
    )
    return completed, message_file


def _show(repo: Path, bead_id: str) -> Issue:
    with BeadProject(repo) as project:
        return project.show(bead_id)


def test_stitch_create_requires_keep_then_closes_only_assigned_phase(
    tmp_path: Path,
) -> None:
    repo = init_live_repo(tmp_path / "repo")
    attach_bare_remote(repo, tmp_path / "remote.git")
    epic_id, phase_id, dependent_id = _seed_phase_beads(repo)
    starting_commits = run_git(repo, "rev-list", "--count", "HEAD").stdout.strip()
    (repo / "agent.py").write_text("print('missing')\n", encoding="utf-8")

    missing, missing_message = _run_stitch(
        repo,
        tmp_path,
        phase_id,
        "fix(lifecycle): first phase change",
        action=None,
    )

    assert missing.returncode == 1
    assert "bead_action is required" in missing.stdout + missing.stderr
    assert missing_message.is_file()
    assert run_git(repo, "rev-list", "--count", "HEAD").stdout.strip() == (
        starting_commits
    )
    assert run_git(repo, "status", "--short", "--", "agent.py").stdout == (
        "?? agent.py\n"
    )
    (repo / "agent.py").write_text("print('keep')\n", encoding="utf-8")

    kept, kept_message = _run_stitch(
        repo,
        tmp_path,
        phase_id,
        "fix(lifecycle): keep phase open",
        action="keep",
    )

    assert kept.returncode == 0, kept.stdout + kept.stderr
    assert not kept_message.exists()
    assert run_git(repo, "rev-list", "--count", "HEAD").stdout.strip() == (
        str(int(starting_commits) + 1)
    )
    head_message = run_git(repo, "show", "-s", "--format=%B", "HEAD").stdout
    assert f"SASE_BEAD={phase_id}" in head_message
    assert _show(repo, phase_id).status is Status.IN_PROGRESS
    assert _show(repo, epic_id).status is Status.OPEN
    assert _show(repo, dependent_id).status is Status.OPEN

    (repo / "agent.py").write_text("print('close')\n", encoding="utf-8")
    closed, closed_message = _run_stitch(
        repo,
        tmp_path,
        phase_id,
        "fix(lifecycle): close phase",
        action="close",
    )

    assert closed.returncode == 0, closed.stdout + closed.stderr
    assert not closed_message.exists()
    phase = _show(repo, phase_id)
    assert phase.status is Status.CLOSED
    assert phase.resolution is Resolution.DONE
    assert any(
        "Closed by explicit `sase stitch create -B close`" in note.text
        for note in phase.notes
    )
    assert _show(repo, epic_id).status is Status.OPEN
    assert _show(repo, dependent_id).status is Status.OPEN
    remote_sha = run_git(
        tmp_path / "remote.git",
        "rev-parse",
        "refs/heads/main",
    ).stdout.strip()
    assert run_git(repo, "rev-parse", "HEAD").stdout.strip() == remote_sha
