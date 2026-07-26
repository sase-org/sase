"""Shared helpers for bead claim tests."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject

from .sync_test_helpers import init_git_repo


def project_with_committed_phase(tmp_path: Path) -> tuple[Path, str]:
    init_git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("sdd/beads/beads.db*\n", encoding="utf-8")
    with BeadProject.init(tmp_path) as project:
        epic = project.create("Epic", IssueType.PLAN)
        phase = project.create("Phase", IssueType.PHASE, parent_id=epic.id)
        beads_dir = project.beads_dir
    subprocess.run(
        ["git", "add", ".gitignore", "sdd/beads"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial bead"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return beads_dir, phase.id


def commit_count(repo: Path) -> int:
    result = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return int(result.stdout.strip())


def install_claim_attempts(
    monkeypatch: pytest.MonkeyPatch,
    attempts: list[object],
) -> tuple[
    list[tuple[str, str]],
    list[Path],
    list[tuple[Path, str, str]],
    list[tuple[Path, str, str]],
]:
    claim_calls: list[tuple[str, str]] = []
    refresh_calls: list[Path] = []
    commit_calls: list[tuple[Path, str, str]] = []
    publish_calls: list[tuple[Path, str, str]] = []
    beads_dir = Path("/canonical/beads")

    class _Project:
        def claim_for_agent_wait(self, bead_id: str, agent_name: str) -> object:
            claim_calls.append((bead_id, agent_name))
            outcome = attempts.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    @contextmanager
    def open_project(_beads_dir: Path) -> Iterator[_Project]:
        yield _Project()

    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )
    monkeypatch.setattr(
        "sase.bead.store_locator.open_bead_project_for_beads_dir",
        open_project,
    )
    monkeypatch.setattr(
        "sase.bead.sync.refresh_bead_store",
        lambda path: refresh_calls.append(path),
    )

    def commit(
        path: Path,
        bead_id: str,
        agent_name: str,
        *,
        already_locked: bool,
    ) -> bool:
        commit_calls.append((path, bead_id, agent_name))
        return True

    monkeypatch.setattr("sase.bead.sync.commit_bead_claim", commit)
    monkeypatch.setattr(
        "sase.bead.sync.publish_bead_claim",
        lambda path, bead_id, agent_name: publish_calls.append(
            (path, bead_id, agent_name)
        ),
    )
    monkeypatch.setattr("sase.bead.claims.time.sleep", lambda _delay: None)
    return claim_calls, refresh_calls, commit_calls, publish_calls


def issue(status: Status, assignee: str) -> SimpleNamespace:
    return SimpleNamespace(status=status, assignee=assignee)
