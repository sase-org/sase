"""Ledger-root phase: resolution, write transaction, bead coexistence.

Covers epic ``sase-1bu`` phase ``ledger-root`` (plus the sase-side
``ledger-io`` remainder it depends on): the goal facade round-trips, the
resolution matrix, the locked write transaction that commits only
``goals/``, crash-leftover recovery, local-mode writes without git, and
proof that bead commits and readers stay clear of ``goals/``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import sase.goals.store as goal_store
from sase.bead.conflict_resolver import (
    _resolve_bead_conflicts_from_cwd,
    resolve_bead_conflicts_for_paths,
)
from sase.bead.model import IssueType
from sase.bead.project import BEADS_DIRNAME_ROOT, BeadProject
from sase.core import goal_ledger_facade as facade
from sase.goals.store import GoalLedger, resolve_goal_ledger
from sase.goals.write import apply_goal_action
from sase.linked_repos import hidden_sidecar_clone_dir
from sase.sdd._commit_store import commit_sdd_files, normalize_sdd_commit_pathspecs
from sase.sdd.store import write_sdd_store_record
from tests.sdd_store._helpers import clone, commit_all, git, init_bare_repo

_PROJECT_KEY = "acme_goals"


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
    """A primary checkout whose beads sidecar resolves to a hidden clone."""
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


class TestGoalLedgerFacade:
    def test_wire_schema_mirrors_match_core(self) -> None:
        assert facade.GOAL_LEDGER_WIRE_SCHEMA_VERSION == 1
        assert facade.GOAL_LEDGER_STORE_SCHEMA_VERSION == 1

    def test_init_append_list_show_doctor_round_trip(self, tmp_path: Path) -> None:
        root = tmp_path / "goals"
        facade.goal_ledger_init(root)
        assert (root / "STORE.json").is_file()

        outcome = facade.goal_ledger_append(
            root, {"action": _new_action(), "actor": _actor()}
        )
        assert outcome["status"] == "applied"
        goal_id = outcome["states"][0]["id"]

        listed = facade.goal_ledger_list(root)
        assert [goal["id"] for goal in listed["goals"]] == [goal_id]

        shown = facade.goal_ledger_show(root, goal_id)
        assert shown["title"] == "Try goals"

        report = facade.goal_ledger_doctor(root, {"repair": False})
        assert report["ok"] is True

        settled = facade.goal_ledger_history(root)
        assert settled["goals"] == []
        everything = facade.goal_ledger_history(root, {"status": "all"})
        assert [goal["id"] for goal in everything["goals"]] == [goal_id]

    def test_stale_core_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "sase.core.goal_ledger_facade.require_rust_binding",
            lambda name: (lambda: 999) if "schema_version" in name else None,
        )
        with pytest.raises(AttributeError, match="stale"):
            facade.goal_ledger_list(tmp_path / "goals")


class TestGoalLedgerResolution:
    def test_shared_resolution_uses_hidden_beads_clone(
        self, shared_project: Path
    ) -> None:
        ledger = resolve_goal_ledger(_PROJECT_KEY)
        assert ledger.mode == "shared"
        assert ledger.hidden_clone == _hidden_beads()
        assert ledger.root == _hidden_beads() / "goals"
        assert ledger.reason == ""
        assert ledger.projection_path.is_file()
        projection = json.loads(ledger.projection_path.read_text(encoding="utf-8"))
        assert Path(projection["ledger_root"]) == ledger.root

    def test_visibility_local_forces_local_only(
        self, shared_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(goal_store, "goals_visibility", lambda: "local")
        ledger = resolve_goal_ledger(_PROJECT_KEY)
        assert ledger.mode == "local"
        assert ledger.hidden_clone is None
        assert "local" in ledger.reason

    def test_missing_host_role_falls_back_to_local(self, shared_project: Path) -> None:
        write_sdd_store_record(
            shared_project,
            {
                "schema_version": 3,
                "storage": "sidecar_repos",
                "provider": "github",
                "sidecars": {
                    "plans": {
                        "repo": "acme/goals--plans",
                        "remote_url": "file:///nonexistent-plans",
                    },
                },
            },
        )
        ledger = resolve_goal_ledger(_PROJECT_KEY)
        assert ledger.mode == "local"
        assert "beads" in ledger.reason

    def test_no_push_remote_falls_back_to_local(
        self, shared_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ledger = resolve_goal_ledger(_PROJECT_KEY)
        assert ledger.mode == "shared"
        monkeypatch.setattr(
            "sase.bead._sync_publication.has_push_remote", lambda _root: False
        )
        again = resolve_goal_ledger(_PROJECT_KEY)
        assert again.mode == "local"
        assert "push remote" in again.reason

    def test_unmaterializable_clone_falls_back_to_local(
        self, shared_project: Path
    ) -> None:
        write_sdd_store_record(
            shared_project,
            {
                "schema_version": 3,
                "storage": "sidecar_repos",
                "provider": "github",
                "sidecars": {
                    "plans": {
                        "repo": "acme/goals--plans",
                        "remote_url": "file:///nonexistent-plans",
                    },
                    "beads": {
                        "repo": "acme/goals--beads",
                        "remote_url": "file:///nonexistent-beads",
                    },
                },
            },
        )
        ledger = resolve_goal_ledger(_PROJECT_KEY)
        assert ledger.mode == "local"
        assert ledger.reason != ""

    def test_unresolvable_project_falls_back_to_local(
        self, shared_project: Path
    ) -> None:
        ledger = resolve_goal_ledger("no_such_project")
        assert ledger.mode == "local"
        assert ledger.reason != ""

    def test_custom_host_role(
        self,
        shared_project: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        remote = tmp_path / "research.git"
        seed = tmp_path / "research-seed"
        init_bare_repo(remote)
        clone(remote, seed)
        (seed / "README.md").write_text("# research\n", encoding="utf-8")
        commit_all(seed, "seed research")
        git(["push", "-u", "origin", "main"], seed)
        write_sdd_store_record(
            shared_project,
            {
                "schema_version": 3,
                "storage": "sidecar_repos",
                "provider": "github",
                "sidecars": {
                    "plans": {
                        "repo": "acme/goals--plans",
                        "remote_url": "file:///nonexistent-plans",
                    },
                    "research": {
                        "repo": "acme/goals--research",
                        "remote_url": str(remote),
                    },
                },
            },
        )
        monkeypatch.setattr(goal_store, "goals_host_role", lambda: "research")
        ledger = resolve_goal_ledger(_PROJECT_KEY)
        assert ledger.mode == "shared"
        assert ledger.host_role == "research"
        assert ledger.hidden_clone == Path(
            hidden_sidecar_clone_dir(_PROJECT_KEY, "research")
        )


class TestGoalWriteTransaction:
    def test_shared_write_commits_only_goals(self, shared_project: Path) -> None:
        from tests.sdd_store._helpers import init_git_identity

        ledger = resolve_goal_ledger(_PROJECT_KEY)
        assert ledger.hidden_clone is not None
        init_git_identity(ledger.hidden_clone)
        stray = ledger.hidden_clone / "STRAY.md"
        stray.write_text("bead-side stray change\n", encoding="utf-8")

        outcome = apply_goal_action(ledger, _new_action(), _actor(), publish=False)
        assert outcome.status == "applied"
        assert outcome.goal_id
        assert outcome.committed is True
        assert outcome.commit_message is not None
        assert outcome.commit_message.startswith(
            f"chore(goals): new goal {outcome.goal_id}"
        )
        assert "SASE_TYPE=goals" in outcome.commit_message

        shown = git(
            ["show", "--name-only", "--pretty=format:", "HEAD"],
            ledger.hidden_clone,
        ).stdout.split()
        assert shown, "expected the goal commit to contain files"
        assert all(name.startswith("goals/") for name in shown)
        dirty = git(
            ["status", "--porcelain", "--", "STRAY.md"], ledger.hidden_clone
        ).stdout.strip()
        assert dirty, "bead-side stray change must stay uncommitted"

    def test_shared_write_publishes_to_remote(self, shared_project: Path) -> None:
        from tests.sdd_store._helpers import init_git_identity

        ledger = resolve_goal_ledger(_PROJECT_KEY)
        assert ledger.hidden_clone is not None
        init_git_identity(ledger.hidden_clone)
        outcome = apply_goal_action(
            ledger, _new_action(), _actor(), push_timeout_seconds=120.0
        )
        assert outcome.status == "applied"
        assert outcome.published is True, outcome.publish_error
        assert outcome.publish_error is None

    def test_crash_leftover_is_recovered_first(self, shared_project: Path) -> None:
        from tests.sdd_store._helpers import init_git_identity

        ledger = resolve_goal_ledger(_PROJECT_KEY)
        assert ledger.hidden_clone is not None
        init_git_identity(ledger.hidden_clone)
        leftover = ledger.root / "live" / "crashed"
        leftover.parent.mkdir(parents=True, exist_ok=True)
        leftover.write_text("", encoding="utf-8")

        outcome = apply_goal_action(ledger, _new_action(), _actor(), publish=False)
        assert outcome.status == "applied"
        assert outcome.recovery_commit is not None
        subjects = git(
            ["log", "--pretty=format:%s", "-2"], ledger.hidden_clone
        ).stdout.splitlines()
        assert subjects[0].startswith("chore(goals): new goal ")
        assert subjects[1] == "chore(goals): recover uncommitted ledger files"

    def test_refused_action_commits_nothing(self, shared_project: Path) -> None:
        from tests.sdd_store._helpers import init_git_identity

        ledger = resolve_goal_ledger(_PROJECT_KEY)
        assert ledger.hidden_clone is not None
        init_git_identity(ledger.hidden_clone)
        created = apply_goal_action(ledger, _new_action(), _actor(), publish=False)
        assert created.status == "applied"
        assert created.goal_id is not None
        before = git(["rev-parse", "HEAD"], ledger.hidden_clone).stdout.strip()
        outcome = apply_goal_action(
            ledger,
            {"action": "edit", "goal_id": created.goal_id},
            _actor(),
            publish=False,
        )
        assert outcome.status == "refused"
        after = git(["rev-parse", "HEAD"], ledger.hidden_clone).stdout.strip()
        assert after == before

    def test_local_mode_writes_without_git(
        self, shared_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(goal_store, "goals_visibility", lambda: "local")
        ledger = resolve_goal_ledger(_PROJECT_KEY)
        assert ledger.mode == "local"
        outcome = apply_goal_action(ledger, _new_action(), _actor())
        assert outcome.status == "applied"
        assert outcome.goal_id
        assert outcome.committed is False
        assert not (ledger.root / ".git").exists()
        shown = facade.goal_ledger_show(ledger.root, outcome.goal_id or "")
        assert shown["title"] == "Try goals"


class TestBeadCoexistence:
    def test_root_pathspec_excludes_goals(self, tmp_path: Path) -> None:
        assert normalize_sdd_commit_pathspecs(tmp_path, None) == [
            ".",
            ":(exclude)goals",
        ]
        assert normalize_sdd_commit_pathspecs(tmp_path, []) == [
            ".",
            ":(exclude)goals",
        ]
        assert normalize_sdd_commit_pathspecs(tmp_path, ["goals"]) == ["goals"]
        assert normalize_sdd_commit_pathspecs(tmp_path, ["beads"]) == ["beads"]

    def test_split_store_bead_commit_leaves_dirty_goals(
        self, shared_project: Path
    ) -> None:
        from tests.sdd_store._helpers import init_git_identity

        ledger = resolve_goal_ledger(_PROJECT_KEY)
        assert ledger.hidden_clone is not None
        repo = ledger.hidden_clone
        init_git_identity(repo)
        goal_file = ledger.root / "live" / "dirty"
        goal_file.parent.mkdir(parents=True, exist_ok=True)
        goal_file.write_text("", encoding="utf-8")
        bead_file = repo / "beads" / "note.txt"
        bead_file.parent.mkdir(parents=True, exist_ok=True)
        bead_file.write_text("bead note\n", encoding="utf-8")

        committed = commit_sdd_files(repo, "bead work")
        assert committed is True
        dirty = git(["status", "--porcelain"], repo).stdout
        assert "goals/" in dirty
        tracked = git(
            ["show", "--name-only", "--pretty=format:", "HEAD"], repo
        ).stdout.split()
        assert not [name for name in tracked if name.startswith("goals/")]

    def test_bead_readers_ignore_goals_dir(self, tmp_path: Path) -> None:
        repo = tmp_path / "beads-repo"
        repo.mkdir()
        with BeadProject.init(repo, beads_dirname=BEADS_DIRNAME_ROOT) as project:
            issue = project.create("Bead beside goals", IssueType.PLAN)
            issue_id = issue.id
        junk = repo / "goals" / "live" / "not-a-goal"
        junk.parent.mkdir(parents=True, exist_ok=True)
        junk.write_text("{broken", encoding="utf-8")

        with BeadProject(repo, beads_dirname=BEADS_DIRNAME_ROOT) as project:
            assert project.show(issue_id).id == issue_id
            assert issue_id in {issue.id for issue in project.list_issues()}

    def test_conflict_resolver_ignores_goals_paths(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        git(["init", "-b", "main"], repo)
        (repo / "goals").mkdir()

        resolution = _resolve_bead_conflicts_from_cwd(repo)
        assert resolution.ok is True

        scoped = resolve_bead_conflicts_for_paths(repo, ("goals/live/x",))
        assert scoped.resolved_files == ()


def test_resolve_goal_ledger_dataclass_shape() -> None:
    ledger = GoalLedger(
        project="demo",
        mode="local",
        root=Path("/tmp/demo/goals"),
        host_role="beads",
        hidden_clone=None,
        watermark_path=Path("/tmp/demo/goals.integration"),
        outbox_path=Path("/tmp/demo/goals-outbox.json"),
        lock_path=Path("/tmp/demo/goals.lock"),
        projection_path=Path("/tmp/demo/goals-hot.json"),
        reason="local only",
    )
    assert ledger.mode == "local"
