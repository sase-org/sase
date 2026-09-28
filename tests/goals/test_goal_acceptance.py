"""Acceptance fixtures for epic ``sase-1bu`` (phase ``acceptance``).

Proves the goal ledger end to end: two-clone convergence across every verb,
settlement-race determinism with marker reconciliation, id-collision
reporting, crash repair through the fault hook, fail-closed schemas,
offline publishing with outbox retry, and the agent refusal matrix.

Ledger-level tests below drive the ``sase_core_rs`` bindings plus plain git
so they stay fast; the shared-mode (hidden-clone) legs reuse the
bare-remote fixtures from the publish-sync suite.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.core import goal_ledger_facade as facade
from tests.sdd_store._helpers import clone, commit_all, git, init_bare_repo

_PROJECT = "acme_goals_accept"


def _human(name: str = "bryan.athena") -> dict[str, Any]:
    return {"principal": name, "kind": "human"}


def _host(name: str) -> dict[str, Any]:
    return {"principal": name, "kind": "host"}


def _new(
    title: str, outcome: str = "A goal is visible on every machine"
) -> dict[str, Any]:
    return {
        "action": "new",
        "title": title,
        "outcome": outcome,
        "criteria": [],
        "project": _PROJECT,
    }


def _commit_goals(repo: Path, message: str) -> None:
    assert git(["add", "-A", "--", "goals"], repo).returncode == 0
    assert git(["commit", "-m", message], repo).returncode == 0


def _rebase_onto_remote(repo: Path) -> None:
    assert git(["fetch", "origin"], repo).returncode == 0
    rebased = git(["rebase", "origin/main"], repo)
    assert rebased.returncode == 0, rebased.stderr


def _seed_pair(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Bare remote plus two clones at the same commit with an empty ledger."""
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
    # Git never tracks the empty live/ dir, so each clone inits its own.
    for repo in (left, right):
        facade.goal_ledger_init(repo / "goals")
    return remote, left, right


def _append(repo: Path, request: dict[str, Any]) -> dict[str, Any]:
    return facade.goal_ledger_append(repo / "goals", request)


def _goal_id(outcome: dict[str, Any]) -> str:
    assert outcome["status"] == "applied", outcome
    states = outcome["states"]
    assert states and states[0].get("id")
    return str(states[0]["id"])


def _canonical_snapshot(repo: Path) -> str:
    """Ledger list + history as canonical JSON, minus wall-clock fields."""
    listed = facade.goal_ledger_list(repo / "goals")
    history = facade.goal_ledger_history(repo / "goals", {"status": "all"})
    for payload in (listed, history):
        payload.pop("generated_at", None)
        for goal in payload.get("goals", []):
            goal.pop("created_at", None)
            goal.pop("updated_at", None)
    return json.dumps({"list": listed, "history": history}, sort_keys=True)


class TestTwoCloneConvergence:
    def test_concurrent_verbs_converge_byte_identical(self, tmp_path: Path) -> None:
        """Concurrent new/edit/drop/reopen/merge from both clones converge."""
        _, left, right = _seed_pair(tmp_path)

        # Same starting goal on both clones.
        seed_id = _goal_id(
            _append(left, {"action": _new("Shared goal"), "actor": _human()})
        )
        _commit_goals(left, "chore(goals): new goal shared")
        git(["push"], left)
        _rebase_onto_remote(right)

        # Different goals, concurrently.
        left_id = _goal_id(
            _append(left, {"action": _new("Left goal"), "actor": _human("left.athena")})
        )
        _commit_goals(left, "chore(goals): new goal left")
        right_id = _goal_id(
            _append(
                right, {"action": _new("Right goal"), "actor": _human("right.apollo")}
            )
        )
        _commit_goals(right, "chore(goals): new goal right")
        git(["push"], left)
        _rebase_onto_remote(right)
        git(["push"], right)
        _rebase_onto_remote(left)

        # Same goal, concurrent edits from one basis.
        assert (
            _append(
                left,
                {
                    "action": {
                        "action": "edit",
                        "goal_id": seed_id,
                        "title": "Shared goal (left)",
                    },
                    "actor": _human("left.athena"),
                },
            )["status"]
            == "applied"
        )
        _commit_goals(left, "chore(goals): edit goal left")
        assert (
            _append(
                right,
                {
                    "action": {
                        "action": "edit",
                        "goal_id": seed_id,
                        "outcome": "Edited from the right",
                    },
                    "actor": _human("right.apollo"),
                },
            )["status"]
            == "applied"
        )
        _commit_goals(right, "chore(goals): edit goal right")
        git(["push"], left)
        _rebase_onto_remote(right)
        git(["push"], right)
        _rebase_onto_remote(left)

        # Settle cycle across clones: drop on the left, reopen on the right.
        assert (
            _append(
                left,
                {
                    "action": {"action": "drop", "goal_id": left_id, "why": "tried it"},
                    "actor": _human(),
                },
            )["status"]
            == "applied"
        )
        _commit_goals(left, "chore(goals): drop goal left")
        git(["push"], left)
        _rebase_onto_remote(right)
        assert (
            _append(
                right,
                {
                    "action": {
                        "action": "reopen",
                        "goal_id": left_id,
                        "message": "worth a retry",
                    },
                    "actor": _human(),
                },
            )["status"]
            == "applied"
        )
        _commit_goals(right, "chore(goals): reopen goal left")
        git(["push"], right)
        _rebase_onto_remote(left)

        # Merge across clones: the right goal folds into the shared one.
        assert (
            _append(
                left,
                {
                    "action": {
                        "action": "merge",
                        "source_id": right_id,
                        "target_id": seed_id,
                        "why": "same work",
                    },
                    "actor": _human(),
                },
            )["status"]
            == "applied"
        )
        _commit_goals(left, "chore(goals): merge goals")
        git(["push"], left)
        _rebase_onto_remote(right)

        # Both clones integrate to the same head and reduce identically.
        assert _canonical_snapshot(left) == _canonical_snapshot(right)
        for repo in (left, right):
            report = facade.goal_ledger_doctor(repo / "goals", {"repair": False})
            assert report["ok"] is True, report["checks"]
            history = facade.goal_ledger_history(repo / "goals", {"status": "all"})
            ids = {goal["id"] for goal in history["goals"]}
            assert {seed_id, left_id, right_id} <= ids


class TestMarkerRace:
    def test_concurrent_settlements_keep_one_winner(self, tmp_path: Path) -> None:
        """Two host-actor drops race; both clones agree on the winner."""
        _, left, right = _seed_pair(tmp_path)
        goal_id = _goal_id(
            _append(left, {"action": _new("Racy goal"), "actor": _human()})
        )
        _commit_goals(left, "chore(goals): new racy goal")
        git(["push"], left)
        _rebase_onto_remote(right)

        # Concurrent settlements from one basis, committed on both sides.
        for repo, machine, note in (
            (left, "left.athena", "verified on the left"),
            (right, "right.apollo", "verified on the right"),
        ):
            outcome = _append(
                repo,
                {
                    "action": {"action": "drop", "goal_id": goal_id, "why": note},
                    "actor": _host(machine),
                },
            )
            assert outcome["status"] == "applied", outcome
            _commit_goals(repo, f"chore(goals): drop racy goal ({machine})")
        git(["push"], left)
        _rebase_onto_remote(right)
        git(["push"], right)
        _rebase_onto_remote(left)

        assert _canonical_snapshot(left) == _canonical_snapshot(right)
        state = facade.goal_ledger_show(left / "goals", goal_id)
        assert state["status"] == "dropped"
        codes = {entry.get("code") for entry in state.get("diagnostics", [])}
        assert "superseded_settlement" in codes
        for repo in (left, right):
            assert not (repo / "goals" / "live" / goal_id).exists()
            from sase.goals.reconcile import reconcile_goals_after_integration

            from sase.goals.store import GoalLedger

            ledger = GoalLedger(
                project=_PROJECT,
                mode="local",
                root=repo / "goals",
                host_role="beads",
                hidden_clone=None,
                watermark_path=repo / "goals.integration",
                outbox_path=repo / "goals-outbox.json",
                lock_path=repo / "goals.lock",
                projection_path=repo / "goals-hot.json",
                reason="acceptance race",
            )
            result = reconcile_goals_after_integration(ledger, touched_ids=[goal_id])
            assert result["fixed"] is False
            report = facade.goal_ledger_doctor(repo / "goals", {"repair": True})
            assert report["ok"] is True, report["checks"]


class TestIdCollision:
    def test_duplicate_mint_reports_collision_with_remedy(self, tmp_path: Path) -> None:
        """Two clones minting one id get a reported collision, never a merge."""
        _, left, right = _seed_pair(tmp_path)
        for repo in (left, right):
            outcome = _append(
                repo,
                {
                    "action": _new("Colliding goal"),
                    "actor": _human(),
                    "new_goal_id": "zz001",
                },
            )
            assert outcome["status"] == "applied", outcome
            _commit_goals(repo, "chore(goals): new colliding goal")
        git(["push"], left)
        _rebase_onto_remote(right)

        state = facade.goal_ledger_show(right / "goals", "zz001")
        assert state["readable"] is False
        assert str(state.get("unreadable_reason", "")).startswith("id_collision")
        remedies = [entry.get("message", "") for entry in state.get("diagnostics", [])]
        assert any("recreate" in message for message in remedies)

        report = facade.goal_ledger_doctor(right / "goals", {"repair": False})
        assert report["ok"] is False
        collision = [
            check
            for check in report["checks"]
            if check.get("code") == "unreadable" and check.get("goal_id") == "zz001"
        ]
        assert len(collision) == 1
        assert "id_collision" in collision[0]["message"]

        # The collision is listed with a warning; neighbors reduce normally.
        neighbor = _goal_id(
            _append(right, {"action": _new("Healthy neighbor"), "actor": _human()})
        )
        listed = facade.goal_ledger_list(right / "goals")
        rows = {goal["id"]: goal for goal in listed["goals"]}
        assert rows["zz001"]["readable"] is False
        assert rows[neighbor]["readable"] is True
        assert rows[neighbor]["title"] == "Healthy neighbor"


class TestCrashRepair:
    def test_fault_between_event_and_marker_repaired(self, tmp_path: Path) -> None:
        """A crash after the event write converges under doctor --repair."""
        root = tmp_path / "goals"
        facade.goal_ledger_init(root)
        outcome = facade.goal_ledger_append(
            root,
            {
                "action": _new("Crashed goal"),
                "actor": _human(),
                "fault_after_event_write": True,
            },
        )
        assert outcome["status"] == "applied"
        goal_id = _goal_id(outcome)
        # `new` unsettles, so the pre-step wrote the marker before the
        # event: the crash lands in a consistent state by construction.
        assert (root / "live" / goal_id).exists()
        assert (root / "items" / goal_id / "events").exists()
        listed = facade.goal_ledger_list(root)
        assert [goal["id"] for goal in listed["goals"]] == [goal_id]
        report = facade.goal_ledger_doctor(root, {"repair": False})
        assert report["ok"] is True, report["checks"]

    def test_fault_on_settle_leaves_repairable_stale_marker(
        self, tmp_path: Path
    ) -> None:
        """A crash after a settle event converges under doctor --repair."""
        root = tmp_path / "goals"
        facade.goal_ledger_init(root)
        goal_id = _goal_id(
            facade.goal_ledger_append(
                root, {"action": _new("Doomed goal"), "actor": _human()}
            )
        )
        outcome = facade.goal_ledger_append(
            root,
            {
                "action": {"action": "drop", "goal_id": goal_id, "why": "tried it"},
                "actor": _human(),
                "fault_after_event_write": True,
            },
        )
        assert outcome["status"] == "applied"
        # The settle event is durable but the marker removal never ran; the
        # hot read omits the settled goal anyway.
        assert (root / "live" / goal_id).exists()
        assert facade.goal_ledger_list(root)["goals"] == []
        before = facade.goal_ledger_doctor(root, {"repair": False})
        assert before["ok"] is False
        assert before["stale_markers"] == [goal_id]
        repaired = facade.goal_ledger_doctor(root, {"repair": True})
        assert repaired["changed_paths"] == [f"live/{goal_id}"]
        assert not (root / "live" / goal_id).exists()
        final = facade.goal_ledger_doctor(root, {"repair": False})
        assert final["ok"] is True, final["checks"]


class TestFailClosed:
    def test_unsupported_store_refuses_every_verb(self, tmp_path: Path) -> None:
        """A STORE.json from the future fails closed with the update hint."""
        root = tmp_path / "goals"
        facade.goal_ledger_init(root)
        (root / "STORE.json").write_text(
            json.dumps({"schema_version": 2, "layout": "sase-goal-ledger"}),
            encoding="utf-8",
        )
        for probe in (
            lambda: facade.goal_ledger_list(root),
            lambda: facade.goal_ledger_show(root, "7k2mq"),
            lambda: facade.goal_ledger_history(root, {"status": "all"}),
            lambda: facade.goal_ledger_append(
                root, {"action": _new("Future goal"), "actor": _human()}
            ),
        ):
            with pytest.raises(ValueError, match=r"goal_ledger:store.*sase update"):
                probe()
        # Doctor is the diagnostic surface: it reports the store problem
        # with the same update hint instead of raising.
        report = facade.goal_ledger_doctor(root, {"repair": False})
        assert report["ok"] is False
        store_checks = [
            check for check in report["checks"] if check.get("code") == "store"
        ]
        assert len(store_checks) == 1
        assert "sase update" in store_checks[0]["message"]

    def test_unknown_event_kind_isolates_one_goal(self, tmp_path: Path) -> None:
        """A future event kind marks one goal unreadable; neighbors render."""
        root = tmp_path / "goals"
        facade.goal_ledger_init(root)
        future_id = _goal_id(
            facade.goal_ledger_append(
                root, {"action": _new("Future goal"), "actor": _human()}
            )
        )
        neighbor_id = _goal_id(
            facade.goal_ledger_append(
                root, {"action": _new("Present goal"), "actor": _human()}
            )
        )
        events_dir = root / "items" / future_id / "events"
        edited = next(
            path for path in sorted(events_dir.iterdir()) if path.suffix == ".json"
        )
        payload = json.loads(edited.read_text(encoding="utf-8"))
        payload["kind"] = "time_travelled"
        payload["event_id"] = "0" * 25 + "1"
        (events_dir / f"{payload['event_id']}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

        state = facade.goal_ledger_show(root, future_id)
        assert state["readable"] is False
        listed = facade.goal_ledger_list(root)
        rows = {goal["id"]: goal for goal in listed["goals"]}
        assert rows[future_id]["readable"] is False
        assert rows[neighbor_id]["readable"] is True
        assert rows[neighbor_id]["title"] == "Present goal"

        rendered = facade.goal_render_list(
            {
                "goals": [
                    {
                        "id": future_id,
                        "title": "Future goal",
                        "status": "active",
                        "readable": False,
                        "created_at": "2026-09-28T13:00:00Z",
                        "updated_at": "2026-09-28T13:00:00Z",
                    }
                ],
                "project": _PROJECT,
                "mode": "local",
                "synced_ago_seconds": 5.0,
                "unpublished": False,
                "refreshing": False,
                "color": False,
                "compact": True,
                "now": "2026-09-28T14:00:00Z",
            }
        )
        assert "⚠" in rendered
        assert "unreadable" in rendered


class TestOfflinePublish:
    """An unreachable remote leaves a durable goal plus outbox debt."""

    @pytest.fixture()
    def shared_project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        from sase.bead.project import BEADS_DIRNAME_ROOT, BeadProject
        from sase.sdd.store import write_sdd_store_record
        from tests.sdd_store._helpers import clone as _clone
        from tests.sdd_store._helpers import commit_all as _commit_all
        from tests.sdd_store._helpers import git as _git
        from tests.sdd_store._helpers import init_bare_repo as _init_bare

        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        beads_remote = tmp_path / "beads.git"
        plans_remote = tmp_path / "plans.git"
        for remote, seed in (
            (beads_remote, tmp_path / "beads-seed"),
            (plans_remote, tmp_path / "plans-seed"),
        ):
            _init_bare(remote)
            _clone(remote, seed)
            if seed.name == "beads-seed":
                with BeadProject.init(seed, beads_dirname=BEADS_DIRNAME_ROOT):
                    pass
            else:
                (seed / "README.md").write_text("# plans\n", encoding="utf-8")
            _commit_all(seed, "seed")
            _git(["push", "-u", "origin", "main"], seed)
        primary = tmp_path / "primary"
        primary.mkdir()
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
        _clone(beads_remote, primary / "sase" / "repos" / "beads")
        _clone(plans_remote, primary / "sase" / "repos" / "plans")
        monkeypatch.setattr(
            "sase.bead.workspace.resolve_primary_workspace_for_project",
            lambda key: primary if key == _PROJECT else None,
        )
        return primary

    def test_unreachable_remote_then_retry_publishes(
        self, shared_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tests.sdd_store._helpers import init_git_identity

        import sase.goals.write as goal_write
        from sase.goals.outbox import goals_outbox_pending
        from sase.goals.store import resolve_goal_ledger
        from sase.goals.sync_status import goal_sync_status
        from sase.goals.write import apply_goal_action, retry_pending_goals_publish

        ledger = resolve_goal_ledger(_PROJECT)
        assert ledger.hidden_clone is not None
        init_git_identity(ledger.hidden_clone)
        monkeypatch.setattr(
            goal_write,
            "_publish_hidden_clone",
            lambda ledger, timeout: (False, "timeout", 1),
        )
        outcome = apply_goal_action(
            ledger,
            {
                "action": "new",
                "title": "Offline goal",
                "outcome": "Durable without a network",
                "criteria": [],
                "project": _PROJECT,
            },
            _human(),
            push_timeout_seconds=5.0,
        )
        assert outcome.status == "applied"
        assert outcome.published is False
        assert outcome.outbox_pending is True
        assert outcome.goal_id is not None
        # The goal is durable locally despite the failed publish.
        state = facade.goal_ledger_show(ledger.root, outcome.goal_id)
        assert state["title"] == "Offline goal"
        assert goals_outbox_pending(ledger.outbox_path) is True
        assert goal_sync_status(ledger)["unpublished"] is True

        # The remote returns: the retry leg publishes and clears the debt.
        monkeypatch.undo()
        try:
            retried = retry_pending_goals_publish(ledger, push_timeout_seconds=30.0)
        except Exception as exc:  # noqa: BLE001 - local git should publish.
            pytest.fail(f"retry after remote return failed: {exc}")
        assert retried["retried"] is True
        assert retried["published"] is True, retried["error"]
        assert goals_outbox_pending(ledger.outbox_path) is False


class TestResolutionWiring:
    def test_bad_config_warns_and_falls_back(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Invalid `goals:` config warns but never breaks resolution."""
        import logging

        import sase.goals.config as goal_config
        import sase.goals.store as goal_store

        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        monkeypatch.setattr(
            goal_config, "goals_config", lambda: {"visibility": "bogus"}
        )
        with caplog.at_level(logging.WARNING, logger="sase.goals.store"):
            ledger = goal_store.resolve_goal_ledger("acme_accept")
        assert ledger.mode == "local"
        assert any("goals.visibility" in message for message in caplog.messages)

    def test_fresh_projection_skips_refresh(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Resolution classifies the projection before paying for a refresh."""
        import sase.goals.store as goal_store
        from sase.core import goal_ledger_facade as facade_mod

        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        ledger = goal_store.resolve_goal_ledger("acme_accept")
        assert ledger.mode == "local"
        calls: list[str] = []
        monkeypatch.setattr(
            facade_mod,
            "goal_projection_status",
            lambda root, path: {"status": "Fresh"},
        )

        def _boom(*args: object, **kwargs: object) -> object:
            calls.append("refresh")
            raise AssertionError("refresh must be skipped for a Fresh projection")

        monkeypatch.setattr(facade_mod, "goal_projection_refresh", _boom)
        again = goal_store.resolve_goal_ledger("acme_accept")
        assert again.projection_path == ledger.projection_path
        assert calls == []


class TestAgentRefusalMatrix:
    def test_show_is_allowed_inside_agent_runs(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """`show` joins `list` and `doctor` as agent-safe read verbs."""
        import argparse

        import sase.goals.cli as goal_cli
        import sase.goals.store as goal_store
        from sase.main.goal_handler import handle_goal_group
        from sase.main.parser import create_parser

        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        monkeypatch.setenv("SASE_AGENT", "1")
        monkeypatch.setattr(goal_store, "goals_visibility", lambda: "local")
        monkeypatch.setattr(goal_cli, "_current_project_name", lambda: "acme_accept")

        def run(argv: list[str]) -> tuple[int, argparse.Namespace | None]:
            args = create_parser().parse_args(argv)
            try:
                handle_goal_group(args)
            except SystemExit as exc:
                assert isinstance(exc.code, int)
                return exc.code, args
            raise AssertionError("goal handler did not exit")

        code, _ = run(["goal", "new", "-t", "T", "-o", "O"])
        assert code == 2
        assert "is a human verb" in capsys.readouterr().err

        monkeypatch.delenv("SASE_AGENT")
        ledger = goal_store.resolve_goal_ledger("acme_accept")
        goal_id = _goal_id(
            facade.goal_ledger_append(
                ledger.root,
                {"action": _new("Agent-visible goal"), "actor": _human()},
            )
        )
        monkeypatch.setenv("SASE_AGENT", "1")
        for argv in (["goal", "list"], ["goal", "show", goal_id], ["goal", "doctor"]):
            code, _ = run(argv)
            assert code == 0, argv
