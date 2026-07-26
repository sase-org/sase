"""Waiting-agent bead claim lifecycle tests."""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.axe.run_agent_runner_bead import claim_bead_for_agent_launch
from sase.bead.claims import (
    BEAD_CLAIM_MARKER,
    BeadClaimReleaseOutcome,
    claim_bead_for_waiting_agent,
    clear_bead_claim_marker,
    read_bead_claim_marker,
    release_bead_claim_for_agent,
    write_bead_claim_marker,
)
from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject
from sase.bead.sync import _PushOutcome, bead_state_is_clean
from sase.sdd._repository_transaction import integrate_sdd_repository
from sase.sdd._repository_types import SddIntegrationOutcome, SddIntegrationStatus
from sase.sdd.store import SddStore

from .sync_test_helpers import init_git_repo


def _project_with_committed_phase(tmp_path: Path) -> tuple[Path, str]:
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


def _commit_count(repo: Path) -> int:
    result = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return int(result.stdout.strip())


def _install_claim_attempts(
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

    monkeypatch.setattr(
        "sase.bead.sync.commit_bead_claim",
        commit,
    )
    monkeypatch.setattr(
        "sase.bead.sync.publish_bead_claim",
        lambda path, bead_id, agent_name: publish_calls.append(
            (path, bead_id, agent_name)
        ),
    )
    monkeypatch.setattr("sase.bead.claims.time.sleep", lambda _delay: None)
    return claim_calls, refresh_calls, commit_calls, publish_calls


def _issue(status: Status, assignee: str) -> SimpleNamespace:
    return SimpleNamespace(status=status, assignee=assignee)


def test_wait_claim_hit_performs_no_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    claim_calls, refresh_calls, commit_calls, publish_calls = _install_claim_attempts(
        monkeypatch,
        [(_issue(Status.CLAIMED, "worker"), True)],
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
            return _issue(Status.CLAIMED, "worker"), True

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
    claim_calls, refresh_calls, _commit_calls, _publish_calls = _install_claim_attempts(
        monkeypatch,
        [
            KeyError("Issue not found: sase-1"),
            (_issue(Status.CLAIMED, "worker"), True),
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
    claim_calls, refresh_calls, _commit_calls, _publish_calls = _install_claim_attempts(
        monkeypatch,
        [
            ValueError("lock_timeout: timed out waiting for bead mutation lock"),
            (_issue(Status.CLAIMED, "worker"), True),
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
    claim_calls, refresh_calls, commit_calls, publish_calls = _install_claim_attempts(
        monkeypatch,
        [(_issue(Status.IN_PROGRESS, "active"), False)],
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
    claim_calls, _refresh_calls, commit_calls, publish_calls = _install_claim_attempts(
        monkeypatch,
        [(_issue(Status.CLAIMED, "worker"), False)],
    )

    assert claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id="sase-1",
        agent_name="worker",
    )

    assert claim_calls == [("sase-1", "worker")]
    assert commit_calls == []
    assert publish_calls == []


def test_retained_wait_claim_commits_dirty_state_after_failed_commit_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir, bead_id = _project_with_committed_phase(tmp_path)
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )
    monkeypatch.setattr("sase.bead.claims.time.sleep", lambda _delay: None)

    from sase.bead.sync import commit_bead_claim as real_commit

    commit_calls = 0

    def fail_then_commit(
        path: Path,
        claimed_bead_id: str,
        agent_name: str,
        *,
        already_locked: bool,
    ) -> bool:
        nonlocal commit_calls
        commit_calls += 1
        if commit_calls == 1:
            raise ValueError("lock_timeout: injected commit failure")
        return real_commit(
            path,
            claimed_bead_id,
            agent_name,
            already_locked=already_locked,
        )

    publish_calls: list[tuple[Path, str, str]] = []
    monkeypatch.setattr("sase.bead.sync.commit_bead_claim", fail_then_commit)
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

    assert commit_calls == 2
    assert publish_calls == [(beads_dir, bead_id, "worker")]
    assert (
        subprocess.run(
            ["git", "status", "--porcelain=v1", "--", "sdd/beads"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == ""
    )


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
    claim_calls, refresh_calls, _commit_calls, _publish_calls = _install_claim_attempts(
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


def test_claim_reclaim_and_release_use_canonical_store_without_commit_churn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    beads_dir, bead_id = _project_with_committed_phase(tmp_path)
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )
    initial_commits = _commit_count(tmp_path)

    assert claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id=bead_id,
        agent_name="worker",
    )
    assert _commit_count(tmp_path) == initial_commits + 1
    with BeadProject(tmp_path) as project:
        issue = project.show(bead_id)
        assert (issue.status, issue.assignee) == (Status.CLAIMED, "worker")

    assert claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id=bead_id,
        agent_name="worker",
    )
    assert _commit_count(tmp_path) == initial_commits + 1

    assert (
        release_bead_claim_for_agent(
            project_name="proj",
            bead_id=bead_id,
            agent_name="worker",
        )
        is BeadClaimReleaseOutcome.RELEASED
    )
    assert _commit_count(tmp_path) == initial_commits + 2
    with BeadProject(tmp_path) as project:
        issue = project.show(bead_id)
        assert (issue.status, issue.assignee) == (Status.OPEN, "")

    subjects = subprocess.run(
        ["git", "log", "-2", "--format=%s"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert subjects == [
        f"chore(beads): release claim on {bead_id} from worker",
        f"chore(beads): claim {bead_id} for worker",
    ]


def test_claim_publication_failures_warn_and_preserve_local_transitions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    beads_dir, bead_id = _project_with_committed_phase(tmp_path)
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )
    publish_calls: list[Path] = []
    log_path = tmp_path / "managed-sync.log"

    def fail_publication(path: Path) -> _PushOutcome:
        publish_calls.append(path)
        return _PushOutcome(
            pushed=False,
            skipped_no_remote=False,
            error="git push failed: rejected",
            log_path=log_path,
        )

    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        fail_publication,
    )
    monkeypatch.setattr("sase.bead.sync._is_in_tree_beads_dir", lambda _path: False)

    assert claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id=bead_id,
        agent_name="worker",
    )
    with BeadProject(tmp_path) as project:
        issue = project.show(bead_id)
        assert (issue.status, issue.assignee) == (Status.CLAIMED, "worker")

    assert (
        release_bead_claim_for_agent(
            project_name="proj",
            bead_id=bead_id,
            agent_name="worker",
        )
        is BeadClaimReleaseOutcome.RELEASED
    )
    with BeadProject(tmp_path) as project:
        issue = project.show(bead_id)
        assert (issue.status, issue.assignee) == (Status.OPEN, "")

    assert publish_calls == [beads_dir, beads_dir]
    stderr = capsys.readouterr().err
    assert stderr.count("Failed to publish bead claim transition") == 2
    assert bead_id in stderr
    assert "worker" in stderr
    assert "git push failed: rejected" in stderr
    assert str(log_path) in stderr


def test_wait_claim_release_and_launch_promotion_publish_to_remote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
    )
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    init_git_repo(canonical)
    subprocess.run(
        ["git", "branch", "-M", "main"],
        cwd=canonical,
        check=True,
        capture_output=True,
    )
    (canonical / ".gitignore").write_text("beads/beads.db*\n", encoding="utf-8")
    with BeadProject.init(canonical, beads_dirname="beads") as project:
        bead_id = project.create("Remote claim", IssueType.PLAN).id
    subprocess.run(
        ["git", "add", ".gitignore", "beads"],
        cwd=canonical,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "seed remote bead"],
        cwd=canonical,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote)],
        cwd=canonical,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=canonical,
        check=True,
        capture_output=True,
    )
    beads_dir = canonical / "beads"
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )

    def observe_remote(name: str) -> tuple[Status, str]:
        clone = tmp_path / name
        subprocess.run(
            ["git", "clone", str(remote), str(clone)],
            check=True,
            capture_output=True,
        )
        with BeadProject(clone, beads_dirname="beads") as project:
            issue = project.show(bead_id)
            return issue.status, issue.assignee

    assert claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id=bead_id,
        agent_name="worker",
    )
    assert observe_remote("claimed") == (Status.CLAIMED, "worker")

    assert (
        release_bead_claim_for_agent(
            project_name="proj",
            bead_id=bead_id,
            agent_name="worker",
        )
        is BeadClaimReleaseOutcome.RELEASED
    )
    assert observe_remote("released") == (Status.OPEN, "")

    assert claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id=bead_id,
        agent_name="worker",
    )
    store = SddStore(
        storage="separate_repo",
        sdd_dir=canonical,
        repo_root=canonical,
        remote_url=str(remote),
    )
    with patch("sase.sdd.store.resolve_sdd_store", return_value=store):
        promoted = claim_bead_for_agent_launch(
            agent_name="worker",
            bead_id=bead_id,
            workspace_dir=str(tmp_path),
            workspace_num=1,
            artifacts_dir=str(tmp_path / "artifacts"),
        )

    assert (promoted.status, promoted.assignee) == (Status.IN_PROGRESS, "worker")
    assert observe_remote("promoted") == (Status.IN_PROGRESS, "worker")


def test_wait_claim_holds_store_lock_from_materialization_through_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir, bead_id = _project_with_committed_phase(tmp_path)
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )
    materialized = threading.Event()
    allow_commit = threading.Event()
    integration_finished = threading.Event()
    original_claim = BeadProject.claim_for_agent_wait

    def pause_after_materialization(
        self: BeadProject,
        claimed_bead_id: str,
        agent_name: str,
    ) -> tuple[object, bool]:
        result = original_claim(self, claimed_bead_id, agent_name)
        materialized.set()
        assert allow_commit.wait(2.0)
        return result

    monkeypatch.setattr(
        BeadProject, "claim_for_agent_wait", pause_after_materialization
    )
    claim_results: list[bool] = []
    integration_results: list[SddIntegrationOutcome] = []

    claim_thread = threading.Thread(
        target=lambda: claim_results.append(
            claim_bead_for_waiting_agent(
                project_name="proj",
                bead_id=bead_id,
                agent_name="worker",
            )
        )
    )

    def integrate() -> None:
        integration_results.append(
            integrate_sdd_repository(
                tmp_path,
                beads_dir=beads_dir,
                fetch=False,
                op_prefix="test.claim_serialization",
            )
        )
        integration_finished.set()

    claim_thread.start()
    assert materialized.wait(2.0)
    integration_thread = threading.Thread(target=integrate)
    integration_thread.start()
    assert not integration_finished.wait(0.1)

    allow_commit.set()
    claim_thread.join(timeout=2.0)
    integration_thread.join(timeout=2.0)

    assert claim_results == [True]
    assert integration_finished.is_set()
    assert integration_results[0].status is SddIntegrationStatus.SUCCESS
    assert integration_results[0].status is not SddIntegrationStatus.UNRECOVERABLE


def test_launch_claim_holds_store_lock_from_materialization_through_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir, bead_id = _project_with_committed_phase(tmp_path)
    store = SddStore(
        storage="separate_repo",
        sdd_dir=beads_dir.parent,
        repo_root=tmp_path,
    )
    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_args: store)
    monkeypatch.setattr(
        "sase.bead.sync.publish_bead_claim",
        lambda *_args, **_kwargs: None,
    )
    materialized = threading.Event()
    allow_commit = threading.Event()
    integration_finished = threading.Event()
    original_claim = BeadProject.claim_for_agent_launch

    def pause_after_materialization(
        self: BeadProject,
        claimed_bead_id: str,
        agent_name: str,
    ) -> object:
        result = original_claim(self, claimed_bead_id, agent_name)
        materialized.set()
        assert allow_commit.wait(2.0)
        return result

    monkeypatch.setattr(
        BeadProject, "claim_for_agent_launch", pause_after_materialization
    )
    launch_results: list[object] = []
    integration_results: list[SddIntegrationOutcome] = []

    claim_thread = threading.Thread(
        target=lambda: launch_results.append(
            claim_bead_for_agent_launch(
                agent_name="worker",
                bead_id=bead_id,
                workspace_dir=str(tmp_path),
                workspace_num=1,
                artifacts_dir=str(tmp_path / "artifacts"),
            )
        )
    )

    def integrate() -> None:
        integration_results.append(
            integrate_sdd_repository(
                tmp_path,
                beads_dir=beads_dir,
                fetch=False,
                op_prefix="test.launch_claim_serialization",
            )
        )
        integration_finished.set()

    claim_thread.start()
    assert materialized.wait(2.0)
    integration_thread = threading.Thread(target=integrate)
    integration_thread.start()
    assert not integration_finished.wait(0.1)

    allow_commit.set()
    claim_thread.join(timeout=5.0)
    integration_thread.join(timeout=5.0)

    assert integration_finished.is_set()
    assert integration_results[0].status is SddIntegrationStatus.SUCCESS
    assert len(launch_results) == 1
    with BeadProject(tmp_path) as project:
        issue = project.show(bead_id)
        assert (issue.status, issue.assignee) == (Status.IN_PROGRESS, "worker")
    assert bead_state_is_clean(beads_dir)


def test_declined_wait_claim_leaves_in_progress_store_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    beads_dir, bead_id = _project_with_committed_phase(tmp_path)
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
    commits = _commit_count(tmp_path)

    assert not claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id=bead_id,
        agent_name="waiting",
    )

    assert _commit_count(tmp_path) == commits
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


def test_claim_helpers_degrade_store_failures_to_warnings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: (_ for _ in ()).throw(RuntimeError("store unavailable")),
    )

    assert not claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id="sase-1",
        agent_name="worker",
    )
    assert (
        release_bead_claim_for_agent(
            project_name="proj",
            bead_id="sase-1",
            agent_name="worker",
        )
        is BeadClaimReleaseOutcome.ERROR
    )

    stderr = capsys.readouterr().err
    assert "Warning: Failed to claim bead 'sase-1'" in stderr
    assert "Warning: Failed to release bead claim on 'sase-1'" in stderr


def test_release_claim_distinguishes_nothing_to_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir, bead_id = _project_with_committed_phase(tmp_path)
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )

    assert (
        release_bead_claim_for_agent(
            project_name="proj",
            bead_id=bead_id,
            agent_name="worker",
        )
        is BeadClaimReleaseOutcome.NOTHING_TO_RELEASE
    )


def test_bead_claim_marker_helpers_round_trip(tmp_path: Path) -> None:
    assert write_bead_claim_marker(
        tmp_path,
        project_name="sase",
        bead_id="sase-1.2",
        agent_name="sase-1.2",
    )

    marker = read_bead_claim_marker(tmp_path)

    assert marker is not None
    assert marker.project_name == "sase"
    assert marker.bead_id == "sase-1.2"
    assert marker.agent_name == "sase-1.2"
    assert clear_bead_claim_marker(tmp_path)
    assert read_bead_claim_marker(tmp_path) is None


def test_bead_claim_marker_failures_warn_without_raising(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact_file = tmp_path / "not-a-directory"
    artifact_file.write_text("", encoding="utf-8")

    assert not write_bead_claim_marker(
        artifact_file,
        project_name="sase",
        bead_id="sase-1.2",
        agent_name="sase-1.2",
    )

    corrupt_dir = tmp_path / "corrupt"
    corrupt_dir.mkdir()
    (corrupt_dir / BEAD_CLAIM_MARKER).write_text("{", encoding="utf-8")

    assert read_bead_claim_marker(corrupt_dir) is None

    stderr = capsys.readouterr().err
    assert "Warning: Failed to write bead claim marker" in stderr
    assert "Warning: Failed to read bead claim marker" in stderr
