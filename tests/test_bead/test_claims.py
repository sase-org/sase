"""Waiting-agent bead claim behavior tests."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.bead.claims import claim_bead_for_waiting_agent
from sase.bead.model import Status
from sase.bead.project import BeadProject

from .claims_test_helpers import (
    commit_count,
    install_claim_attempts,
    issue,
    project_with_committed_phase,
)


def test_wait_claim_hit_performs_no_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    claim_calls, refresh_calls, commit_calls, publish_calls = install_claim_attempts(
        monkeypatch,
        [(issue(Status.CLAIMED, "worker"), True)],
    )

    assert claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id="sase-1",
        agent_name="worker",
    )

    assert claim_calls == [("sase-1", "worker")]
    assert refresh_calls == []
    assert commit_calls == [(Path("/canonical/beads"), "sase-1", "worker")]
    assert publish_calls == [(Path("/canonical/beads"), "sase-1", "worker")]


def test_wait_claim_publishes_after_store_lock_is_released(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir = Path("/canonical/beads")
    lock_held = False
    events: list[str] = []

    class _Project:
        def claim_for_agent_wait(
            self, _bead_id: str, _agent_name: str
        ) -> tuple[SimpleNamespace, bool]:
            assert lock_held
            return issue(Status.CLAIMED, "worker"), True

    @contextmanager
    def open_project(_beads_dir: Path) -> Iterator[_Project]:
        yield _Project()

    @contextmanager
    def store_lock(_beads_dir: Path) -> Iterator[bool]:
        nonlocal lock_held
        lock_held = True
        events.append("lock")
        try:
            yield True
        finally:
            lock_held = False
            events.append("unlock")

    def commit(
        _beads_dir: Path,
        _bead_id: str,
        _agent_name: str,
        *,
        already_locked: bool,
    ) -> bool:
        assert lock_held
        assert already_locked
        events.append("commit")
        return True

    def publish(_beads_dir: Path, _bead_id: str, _agent_name: str) -> None:
        assert not lock_held
        events.append("publish")

    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )
    monkeypatch.setattr(
        "sase.bead.store_locator.open_bead_project_for_beads_dir",
        open_project,
    )
    monkeypatch.setattr("sase.bead.sync.bead_store_write_lock", store_lock)
    monkeypatch.setattr("sase.bead.sync.commit_bead_claim", commit)
    monkeypatch.setattr("sase.bead.sync.publish_bead_claim", publish)

    assert claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id="sase-1",
        agent_name="worker",
    )
    assert events == ["lock", "commit", "unlock", "publish"]


def test_wait_claim_not_found_refreshes_once_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim_calls, refresh_calls, _commit_calls, _publish_calls = install_claim_attempts(
        monkeypatch,
        [
            KeyError("Issue not found: sase-1"),
            (issue(Status.CLAIMED, "worker"), True),
        ],
    )

    assert claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id="sase-1",
        agent_name="worker",
    )

    assert claim_calls == [("sase-1", "worker"), ("sase-1", "worker")]
    assert refresh_calls == [Path("/canonical/beads")]


def test_wait_claim_lock_timeout_retries_without_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim_calls, refresh_calls, _commit_calls, _publish_calls = install_claim_attempts(
        monkeypatch,
        [
            ValueError("lock_timeout: timed out waiting for bead mutation lock"),
            (issue(Status.CLAIMED, "worker"), True),
        ],
    )

    assert claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id="sase-1",
        agent_name="worker",
    )

    assert claim_calls == [("sase-1", "worker"), ("sase-1", "worker")]
    assert refresh_calls == []


def test_wait_claim_legitimate_decline_does_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim_calls, refresh_calls, commit_calls, publish_calls = install_claim_attempts(
        monkeypatch,
        [(issue(Status.IN_PROGRESS, "active"), False)],
    )

    assert not claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id="sase-1",
        agent_name="worker",
    )

    assert claim_calls == [("sase-1", "worker")]
    assert refresh_calls == []
    assert commit_calls == []
    assert publish_calls == []


def test_same_owner_wait_claim_does_not_commit_or_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim_calls, _refresh_calls, commit_calls, publish_calls = install_claim_attempts(
        monkeypatch,
        [(issue(Status.CLAIMED, "worker"), False)],
    )

    assert claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id="sase-1",
        agent_name="worker",
    )

    assert claim_calls == [("sase-1", "worker")]
    assert commit_calls == []
    assert publish_calls == []


def test_same_owner_in_progress_wait_claim_is_held_without_commit_or_warning(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _claim_calls, _refresh_calls, commit_calls, publish_calls = install_claim_attempts(
        monkeypatch,
        [(issue(Status.IN_PROGRESS, "worker"), False)],
    )

    assert claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id="sase-1",
        agent_name="worker",
    )

    assert commit_calls == []
    assert publish_calls == []
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ("Retained claim on bead sase-1 for waiting agent worker\n")


def test_retained_wait_claim_does_not_commit_preexisting_dirty_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir, bead_id = project_with_committed_phase(tmp_path)
    with BeadProject(tmp_path) as project:
        project.update(
            bead_id,
            status=Status.CLAIMED.value,
            assignee="worker",
        )
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )
    monkeypatch.setattr("sase.bead.claims.time.sleep", lambda _delay: None)

    commit_calls = 0

    def record_commit(*_args: object, **_kwargs: object) -> bool:
        nonlocal commit_calls
        commit_calls += 1
        return True

    publish_calls: list[tuple[Path, str, str]] = []
    monkeypatch.setattr("sase.bead.sync.commit_bead_claim", record_commit)
    monkeypatch.setattr(
        "sase.bead.sync.publish_bead_claim",
        lambda path, claimed_bead_id, agent_name: publish_calls.append(
            (path, claimed_bead_id, agent_name)
        ),
    )

    assert claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id=bead_id,
        agent_name="worker",
    )

    assert commit_calls == 0
    assert publish_calls == []
    assert subprocess.run(
        ["git", "status", "--porcelain=v1", "--", "sdd/beads"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_home_wait_claim_is_silently_skipped(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: pytest.fail("home mode must not resolve a bead store"),
    )

    assert not claim_bead_for_waiting_agent(
        project_name="home",
        bead_id="sase-1",
        agent_name="worker",
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_wait_claim_exhausted_budget_warns_without_raising(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    claim_calls, refresh_calls, _commit_calls, _publish_calls = install_claim_attempts(
        monkeypatch,
        [
            KeyError("Issue not found: sase-1"),
            KeyError("Issue not found: sase-1"),
            KeyError("Issue not found: sase-1"),
        ],
    )

    assert not claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id="sase-1",
        agent_name="worker",
    )

    assert len(claim_calls) == 3
    assert refresh_calls == [Path("/canonical/beads")]
    assert "Warning: Failed to claim bead 'sase-1'" in capsys.readouterr().err


def test_declined_wait_claim_leaves_in_progress_store_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    beads_dir, bead_id = project_with_committed_phase(tmp_path)
    with BeadProject(tmp_path) as project:
        project.update(bead_id, status=Status.IN_PROGRESS.value, assignee="active")
    subprocess.run(["git", "add", "sdd/beads"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "mark active"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )
    before = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    commits = commit_count(tmp_path)

    assert not claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id=bead_id,
        agent_name="waiting",
    )

    assert commit_count(tmp_path) == commits
    assert (
        subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == before
    )
    with BeadProject(tmp_path) as project:
        issue = project.show(bead_id)
        assert (issue.status, issue.assignee) == (Status.IN_PROGRESS, "active")
