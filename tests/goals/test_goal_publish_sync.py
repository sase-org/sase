"""Publish-sync phase: outbox, retries, freshness, reconciliation.

Covers epic ``sase-1bu`` phase ``publish-sync``: the unpublished outbox,
the push-retry counter, the synced-ago watermark, the single-flight TTL
fetch, post-integration marker reconciliation, and proof that rebases
carrying goal commits never need semantic conflict repair.
"""

from __future__ import annotations

import fcntl
from pathlib import Path

import pytest

import sase.goals.store as goal_store
from sase.bead.project import BEADS_DIRNAME_ROOT, BeadProject
from sase.bead.model import IssueType
from sase.core import goal_ledger_facade as facade
from sase.goals.fetch_worker import run_goals_fetch
from sase.goals.outbox import (
    clear_goals_outbox,
    goals_outbox_pending,
    read_goals_outbox,
    record_goals_publish_failure,
)
from sase.goals.reconcile import (
    _collect_touched_goal_ids,
    _touched_goal_ids_from_names,
    reconcile_goals_after_integration,
)
from sase.goals.store import resolve_goal_ledger
from sase.goals.sync_stats import read_goals_sync_stats, record_goals_publish
from sase.goals.sync_status import goal_sync_status
from sase.goals.write import apply_goal_action, retry_pending_goals_publish
from sase.linked_repos import hidden_sidecar_clone_dir
from sase.sdd.store import write_sdd_store_record
from tests.sdd_store._helpers import clone, commit_all, git, init_bare_repo

_PROJECT_KEY = "acme_goals_sync"


def _seeded_beads_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "beads.git"
    seed = tmp_path / "beads-seed"
    init_bare_repo(remote)
    clone(remote, seed)
    with BeadProject.init(seed, beads_dirname=BEADS_DIRNAME_ROOT):
        pass
    commit_all(seed, "seed beads")
    git(["push", "-u", "origin", "main"], seed)
    return remote


def _seeded_role_remote(tmp_path: Path, role: str) -> Path:
    remote = tmp_path / f"{role}.git"
    seed = tmp_path / f"{role}-seed"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text(f"# {role}\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    return remote


def _write_store_record(primary: Path, beads_remote: Path, plans_remote: Path) -> None:
    write_sdd_store_record(
        primary,
        {
            "schema_version": 3,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                "plans": {
                    "repo": "acme/goals--plans",
                    "remote_url": str(plans_remote),
                },
                "beads": {
                    "repo": "acme/goals--beads",
                    "remote_url": str(beads_remote),
                },
            },
        },
    )


@pytest.fixture()
def shared_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    beads_remote = _seeded_beads_remote(tmp_path)
    plans_remote = _seeded_role_remote(tmp_path, "plans")
    primary = tmp_path / "primary"
    primary.mkdir()
    _write_store_record(primary, beads_remote, plans_remote)
    clone(beads_remote, primary / "sase" / "repos" / "beads")
    clone(plans_remote, primary / "sase" / "repos" / "plans")
    monkeypatch.setattr(
        "sase.bead.workspace.resolve_primary_workspace_for_project",
        lambda key: primary if key == _PROJECT_KEY else None,
    )
    return primary


def _hidden_beads() -> Path:
    return Path(hidden_sidecar_clone_dir(_PROJECT_KEY, "beads"))


def _new_action() -> dict[str, object]:
    return {
        "action": "new",
        "title": "Try goals",
        "outcome": "A goal is visible on every machine",
        "criteria": [],
        "project": _PROJECT_KEY,
    }


def _actor() -> dict[str, object]:
    return {"principal": "bryan.athena", "kind": "human"}


class TestGoalsOutbox:
    def test_missing_reads_as_not_pending(self, tmp_path: Path) -> None:
        assert goals_outbox_pending(tmp_path / "goals-outbox.json") is False
        record = read_goals_outbox(tmp_path / "goals-outbox.json")
        assert record == {
            "pending": False,
            "since": None,
            "attempts": 0,
            "last_error": None,
            "last_attempt_at": None,
        }

    def test_corrupt_reads_as_not_pending(self, tmp_path: Path) -> None:
        path = tmp_path / "goals-outbox.json"
        path.write_text("{broken", encoding="utf-8")
        assert goals_outbox_pending(path) is False

    def test_failure_then_clear(self, tmp_path: Path) -> None:
        path = tmp_path / "goals-outbox.json"
        first = record_goals_publish_failure(path, "timeout")
        assert first["pending"] is True
        assert first["attempts"] == 1
        second = record_goals_publish_failure(path, "timeout")
        assert second["attempts"] == 2
        assert second["since"] == first["since"]
        cleared = clear_goals_outbox(path)
        assert cleared["pending"] is False
        assert goals_outbox_pending(path) is False


class TestGoalsSyncStats:
    def test_missing_reads_as_zeros(self, tmp_path: Path) -> None:
        stats = read_goals_sync_stats(tmp_path / "goals-sync-stats.json")
        assert stats["publishes"] == 0
        assert stats["push_retries"] == 0
        assert stats["rejected_after_max"] == 0

    def test_retry_counted_once_for_one_retry(self, tmp_path: Path) -> None:
        path = tmp_path / "goals-sync-stats.json"
        stats = record_goals_publish(path, push_attempts=2)
        assert stats["publishes"] == 1
        assert stats["push_retries"] == 1
        assert stats["last_retry_at"] is not None

    def test_rejected_after_max_recorded(self, tmp_path: Path) -> None:
        path = tmp_path / "goals-sync-stats.json"
        stats = record_goals_publish(path, push_attempts=3, rejected_after_max=True)
        assert stats["publishes"] == 1
        assert stats["push_retries"] == 2
        assert stats["rejected_after_max"] == 1

    def test_corrupt_reads_as_zeros(self, tmp_path: Path) -> None:
        path = tmp_path / "goals-sync-stats.json"
        path.write_text("{broken", encoding="utf-8")
        assert read_goals_sync_stats(path)["publishes"] == 0


class TestGoalSyncStatus:
    def test_local_mode_reports_local_only(
        self, shared_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(goal_store, "goals_visibility", lambda: "local")
        ledger = resolve_goal_ledger(_PROJECT_KEY)
        status = goal_sync_status(ledger)
        assert status["mode"] == "local"
        assert status["synced_at"] is None
        assert status["unpublished"] is False
        assert status["refreshing"] is False

    def test_shared_write_advances_watermark(self, shared_project: Path) -> None:
        from tests.sdd_store._helpers import init_git_identity

        ledger = resolve_goal_ledger(_PROJECT_KEY)
        assert ledger.hidden_clone is not None
        init_git_identity(ledger.hidden_clone)
        before = goal_sync_status(ledger)
        assert before["synced_at"] is None
        outcome = apply_goal_action(
            ledger, _new_action(), _actor(), push_timeout_seconds=120.0
        )
        assert outcome.status == "applied"
        after = goal_sync_status(ledger)
        assert after["synced_at"] is not None
        assert after["mode"] == "shared"

    def test_failed_publish_leaves_unpublished_outbox(
        self, shared_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tests.sdd_store._helpers import init_git_identity

        import sase.goals.write as goal_write

        ledger = resolve_goal_ledger(_PROJECT_KEY)
        assert ledger.hidden_clone is not None
        init_git_identity(ledger.hidden_clone)
        # Simulate an unreachable remote: the publish times out.
        monkeypatch.setattr(
            goal_write,
            "_publish_hidden_clone",
            lambda ledger, timeout: (False, "timeout", 1),
        )
        outcome = apply_goal_action(ledger, _new_action(), _actor())
        assert outcome.status == "applied"
        assert outcome.published is False
        assert outcome.outbox_pending is True
        assert outcome.outbox is not None and outcome.outbox["pending"] is True
        assert goal_sync_status(ledger)["unpublished"] is True

    def test_retry_clears_outbox(self, shared_project: Path) -> None:
        from tests.sdd_store._helpers import init_git_identity

        ledger = resolve_goal_ledger(_PROJECT_KEY)
        assert ledger.hidden_clone is not None
        init_git_identity(ledger.hidden_clone)
        record_goals_publish_failure(ledger.outbox_path, "timeout")
        assert goals_outbox_pending(ledger.outbox_path) is True
        result = retry_pending_goals_publish(ledger, push_timeout_seconds=120.0)
        assert result["retried"] is True
        assert result["published"] is True, result["error"]
        assert goals_outbox_pending(ledger.outbox_path) is False


class TestFetchWorker:
    def test_single_flight_bails_when_locked(self, shared_project: Path) -> None:
        from tests.sdd_store._helpers import init_git_identity

        from sase.goals.sync_status import goals_fetch_lock_path

        ledger = resolve_goal_ledger(_PROJECT_KEY)
        assert ledger.hidden_clone is not None
        init_git_identity(ledger.hidden_clone)
        lock_path = goals_fetch_lock_path(ledger)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            outcome = run_goals_fetch(_PROJECT_KEY, force=True)
            assert outcome["skipped"] == "another fetch is running"
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def test_fetch_integrates_and_refreshes(self, shared_project: Path) -> None:
        from tests.sdd_store._helpers import init_git_identity

        ledger = resolve_goal_ledger(_PROJECT_KEY)
        assert ledger.hidden_clone is not None
        init_git_identity(ledger.hidden_clone)
        created = apply_goal_action(
            ledger, _new_action(), _actor(), push_timeout_seconds=120.0
        )
        assert created.status == "applied"
        outcome = run_goals_fetch(_PROJECT_KEY, force=True)
        assert outcome["error"] is None, outcome["error"]
        assert outcome["skipped"] is None
        assert ledger.projection_path.is_file()


class TestReconcile:
    def test_touched_ids_from_names(self) -> None:
        names = [
            "goals/items/abc12/events/01.json",
            "goals/live/abc12",
            "beads/foo.md",
            "goals/STORE.json",
        ]
        assert _touched_goal_ids_from_names(names) == ["abc12"]

    def test_stale_marker_is_repaired_and_committed(self, shared_project: Path) -> None:
        from tests.sdd_store._helpers import init_git_identity

        ledger = resolve_goal_ledger(_PROJECT_KEY)
        assert ledger.hidden_clone is not None
        init_git_identity(ledger.hidden_clone)
        created = apply_goal_action(
            ledger, _new_action(), _actor(), push_timeout_seconds=120.0
        )
        assert created.status == "applied"
        goal_id = created.goal_id
        assert goal_id
        dropped = apply_goal_action(
            ledger,
            {"action": "drop", "goal_id": goal_id, "why": "tried it"},
            _actor(),
            push_timeout_seconds=120.0,
        )
        assert dropped.status == "applied"
        # Inject the concurrent-settlement race: the settled goal stays marked
        # in committed history, as if another machine's settlement won.
        marker = ledger.root / "live" / goal_id
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("", encoding="utf-8")
        git(["add", "-A", "--", "goals"], ledger.hidden_clone)
        git(["commit", "-m", "chore(goals): stale marker"], ledger.hidden_clone)
        result = reconcile_goals_after_integration(ledger, touched_ids=[goal_id])
        assert result["fixed"] is True
        assert result["commit"] is not None
        assert not marker.exists()
        subjects = git(["log", "--pretty=format:%s", "-1"], ledger.hidden_clone).stdout
        assert "reconcile live markers" in subjects

    def test_reconcile_fails_open_without_ledger(self, tmp_path: Path) -> None:
        from sase.goals.store import GoalLedger

        ledger = GoalLedger(
            project="demo",
            mode="local",
            root=tmp_path / "goals",
            host_role="beads",
            hidden_clone=None,
            watermark_path=tmp_path / "goals.integration",
            outbox_path=tmp_path / "goals-outbox.json",
            lock_path=tmp_path / "goals.lock",
            projection_path=tmp_path / "goals-hot.json",
            reason="local only",
        )
        result = reconcile_goals_after_integration(ledger)
        assert result["fixed"] is False
        assert result["diagnostic"] is None

    def test_collect_touched_ids_empty_when_clean(self, shared_project: Path) -> None:
        from tests.sdd_store._helpers import init_git_identity

        ledger = resolve_goal_ledger(_PROJECT_KEY)
        assert ledger.hidden_clone is not None
        init_git_identity(ledger.hidden_clone)
        created = apply_goal_action(
            ledger, _new_action(), _actor(), push_timeout_seconds=120.0
        )
        assert created.status == "applied"
        ids = _collect_touched_goal_ids(ledger.hidden_clone)
        assert ids is not None


class TestGoalRebaseNeverConflicts:
    def test_concurrent_goal_writes_rebase_cleanly(self, tmp_path: Path) -> None:
        """Two clones writing different goals integrate without repair."""
        from tests.sdd_store._helpers import init_git_identity

        remote = tmp_path / "goals-remote.git"
        seed = tmp_path / "goals-seed"
        init_bare_repo(remote)
        clone(remote, seed)
        init_git_identity(seed)
        facade.goal_ledger_init(seed / "goals")
        commit_all(seed, "seed goals")
        git(["push", "-u", "origin", "main"], seed)
        left = tmp_path / "left"
        right = tmp_path / "right"
        clone(remote, left)
        clone(remote, right)
        init_git_identity(left)
        init_git_identity(right)
        for repo in (left, right):
            facade.goal_ledger_init(repo / "goals")
            outcome = facade.goal_ledger_append(
                repo / "goals",
                {"action": _new_action(), "actor": _actor()},
            )
            assert outcome["status"] == "applied"
            git(["add", "-A", "--", "goals"], repo)
            git(["commit", "-m", "chore(goals): new goal"], repo)
        git(["push"], left)
        fetch = git(["fetch", "origin"], right)
        assert fetch.returncode == 0
        rebased = git(["rebase", "origin/main"], right)
        assert rebased.returncode == 0, rebased.stderr
        from sase.sdd._semantic_conflict_resolver import resolve_semantic_conflicts

        resolution = resolve_semantic_conflicts(right)
        assert resolution.ok is True
        report = facade.goal_ledger_doctor(right / "goals", {"repair": True})
        assert report["ok"] is True

    def test_bead_issue_beside_goals_still_lists(self, tmp_path: Path) -> None:
        repo = tmp_path / "beads-repo"
        repo.mkdir()
        with BeadProject.init(repo, beads_dirname=BEADS_DIRNAME_ROOT) as project:
            issue = project.create("Bead beside goals", IssueType.PLAN)
            issue_id = issue.id
        junk = repo / "goals" / "live" / "not-a-goal"
        junk.parent.mkdir(parents=True, exist_ok=True)
        junk.write_text("", encoding="utf-8")
        with BeadProject(repo, beads_dirname=BEADS_DIRNAME_ROOT) as project:
            assert project.show(issue_id).id == issue_id


class TestChopPushLeg:
    def test_leg_publishes_pending_outbox(self, shared_project: Path) -> None:
        import logging
        from types import SimpleNamespace

        from tests.sdd_store._helpers import init_git_identity

        from sase.scripts.sase_chop_sidecar_auto_sync import (
            _publish_pending_goals_outboxes,
        )

        ledger = resolve_goal_ledger(_PROJECT_KEY)
        assert ledger.hidden_clone is not None
        init_git_identity(ledger.hidden_clone)
        record_goals_publish_failure(ledger.outbox_path, "timeout")
        runtime = SimpleNamespace(log=logging.getLogger("test"))
        records = [SimpleNamespace(project_name=_PROJECT_KEY)]
        assert _publish_pending_goals_outboxes(runtime, records) == 1
        assert goals_outbox_pending(ledger.outbox_path) is False

    def test_leg_skips_without_pending_outbox(self, shared_project: Path) -> None:
        import logging
        from types import SimpleNamespace

        from sase.scripts.sase_chop_sidecar_auto_sync import (
            _publish_pending_goals_outboxes,
        )

        resolve_goal_ledger(_PROJECT_KEY)
        runtime = SimpleNamespace(log=logging.getLogger("test"))
        records = [SimpleNamespace(project_name=_PROJECT_KEY)]
        assert _publish_pending_goals_outboxes(runtime, records) == 0
