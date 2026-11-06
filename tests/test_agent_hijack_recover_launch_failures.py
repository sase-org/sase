"""Queued and failed hijack recovery launch cases."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack.recovery_successor import RecoveryInheritanceError
from sase.running_field import WorkspaceClaimError
from tests._agent_hijack_recover_helpers import (
    Flow,
    evidence,
    make_preview,
    record as make_record,
    spawned,
    subject as make_subject,
    write_done,
)


class TestQueuedAndFailedLaunches:
    def _base(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **kwargs: Any
    ) -> Flow:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir(exist_ok=True)
        write_done(artifacts / "done.json")
        successor_dir = tmp_path / "succ"
        successor_dir.mkdir(exist_ok=True)
        return Flow(monkeypatch, make_record(artifacts), successor_dir, **kwargs)

    def test_claim_contention_is_a_terminal_admission_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        flow = self._base(
            monkeypatch, tmp_path, spawn=WorkspaceClaimError("foreign claim")
        )
        result = flow.recover()
        assert result.kind == "error"
        assert result.successor == "acme--4"
        assert result.launch_identity
        assert flow.ledger.current["state"] == "held"
        assert flow.log == ["spawn"]

    def test_definite_failure_returns_to_held(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        flow = self._base(
            monkeypatch,
            tmp_path,
            spawn=RecoveryInheritanceError("bad workspace"),
        )
        result = flow.recover()
        assert result.kind == "error"
        assert result.detail["code"] == "launch_failed"
        assert flow.ledger.current["state"] == "held"
        assert flow.ledger.current["error"] == "bad workspace"
        assert "launch_identity" not in flow.ledger.current

    def test_uncertain_post_spawn_retains_resolving(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        flow = self._base(monkeypatch, tmp_path, spawn=Exception("lost contact"))
        result = flow.recover()
        assert result.kind == "uncertain"
        assert flow.ledger.current["state"] == "resolving"
        assert (
            flow.ledger.current["error"] == "uncertain admission outcome: lost contact"
        )

    def test_repeated_resolving_call_keeps_the_same_uncertain_request(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        flow = self._base(monkeypatch, tmp_path, spawn=Exception("lost contact"))
        first = flow.recover()
        assert first.kind == "uncertain"
        deps = flow.deps()
        deps.load_subject = lambda _agent: make_subject(flow.ledger.current)

        resumed = flow.recover(deps=deps)
        assert resumed.kind == "already_resolving"
        assert resumed.admission_request_id == first.admission_request_id
        assert resumed.detail["admission"]["state"] == "dispatching"
        assert flow.log == ["spawn"]

    def test_identity_mismatch_rolls_back_only_after_verified_stop(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        flow = self._base(
            monkeypatch,
            tmp_path,
            spawn=spawned(4242, tmp_path / "succ"),
        )
        flow._spawn = SimpleNamespace(
            agent_name="acme--9", pid=4242, artifacts_dir=str(tmp_path / "succ")
        )
        result = flow.recover()
        assert result.kind == "error"
        assert result.detail["code"] == "identity_mismatch"
        assert flow.ledger.current["state"] == "held"

    def test_missing_boot_ack_returns_held_after_safe_rollback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        flow = self._base(
            monkeypatch,
            tmp_path,
            spawn=spawned(4242, tmp_path / "succ"),
            evidence={},
        )
        result = flow.recover()
        assert result.kind == "error"
        assert result.detail["code"] == "ack_missing"
        assert flow.ledger.current["state"] == "held"

    def test_unverified_claim_returns_held_after_safe_rollback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        flow = self._base(
            monkeypatch,
            tmp_path,
            spawn=spawned(4242, tmp_path / "succ"),
            claim_ok=False,
        )
        result = flow.recover()
        assert result.kind == "error"
        assert result.detail["code"] == "workspace_mismatch"
        assert flow.ledger.current["state"] == "held"

    def test_inheritance_failure_terminates_and_holds(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from sase.agent.hijack.recovery_successor import write_recovery_ack

        successor_dir = tmp_path / "succ"
        write_recovery_ack(str(successor_dir), {"schema_version": 1})
        flow = self._base(
            monkeypatch,
            tmp_path,
            spawn=spawned(4242, successor_dir),
            evidence=evidence(successor_bead="other-bead"),
        )
        result = flow.recover()
        assert result.kind == "error"
        assert result.detail["code"] == "ack_mismatch"
        assert flow.ledger.current["state"] == "held"
        assert flow.terminated == [4242]
        assert (successor_dir / "hijack_recovery_ack.json").exists()

    def test_failed_process_tree_stop_retains_resolving(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        flow = self._base(
            monkeypatch,
            tmp_path,
            spawn=spawned(4242, tmp_path / "succ"),
            evidence={},
            terminate_verified=False,
        )
        result = flow.recover()
        assert result.kind == "uncertain"
        assert result.detail["termination"]["verified_dead"] is False
        assert flow.ledger.current["state"] == "resolving"
        assert flow.terminated == [4242]

    def test_failed_custody_restoration_retains_resolving(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        flow = self._base(
            monkeypatch,
            tmp_path,
            spawn=spawned(4242, tmp_path / "succ"),
            evidence={},
            restore_custody_ok=False,
        )
        result = flow.recover()
        assert result.kind == "uncertain"
        assert result.detail["custody"]["restored"] is False
        assert flow.ledger.current["state"] == "resolving"

    def test_cancellation_must_be_observed_before_rollback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from sase.agent.hijack.recover_common import RecoveryDeps
        from sase.agent.hijack._recover_confirm_rollback import (
            _make_request_non_dispatchable,
        )

        flow = self._base(monkeypatch, tmp_path)
        flow.ledger.current["state"] = "resolving"
        calls: list[tuple[str, str]] = []

        def cancel(request_id: str, reason: str) -> dict[str, Any]:
            calls.append((request_id, reason))
            return {
                "request_id": request_id,
                "dispatch_fingerprint": "fingerprint-1",
                "state": "cancelled",
                "in_flight": False,
                "cancel_requested": True,
            }

        request_state, observed = _make_request_non_dispatchable(
            {
                "request_id": "request-1",
                "dispatch_fingerprint": "fingerprint-1",
                "state": "waiting",
                "in_flight": True,
            },
            request_id="request-1",
            admission_identity="fingerprint-1",
            seams=RecoveryDeps(cancel_admission=cancel),
        )
        assert request_state == "canceled"
        assert observed["cancel_requested"] is True
        assert calls == [("request-1", "recovery successor confirmation failed")]
        assert flow.ledger.current["state"] == "resolving"

    def test_rollback_restores_and_pins_the_recorded_workspace_owner(
        self, tmp_path: Path
    ) -> None:
        from sase.agent.hijack._recover_confirm_rollback import (
            _restore_held_workspace_custody,
        )
        from sase.running_field import get_claimed_workspaces

        project_file = tmp_path / "proj.sase"
        project_file.write_text(
            "# Project: proj\nRUNNING:\n"
            "  #3 | 4242 | ace(run)-20261105_000000 | acme--4 | "
            "20261105000000\n",
            encoding="utf-8",
        )
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        record = make_record(
            artifacts,
            project_file=str(project_file),
            expected_claim_owner_pid=111,
        )
        launched = SimpleNamespace(
            workspace_num=3,
            workspace_dir="/ws/3",
            workflow_name="ace(run)-20261105_000000",
            cl_name="acme--4",
            timestamp="20261105000000",
        )

        restored, message = _restore_held_workspace_custody(record, 4242, launched)

        claims = get_claimed_workspaces(str(project_file))
        assert restored is True, message
        assert len(claims) == 1
        assert claims[0].workspace_num == 3
        assert claims[0].pid == 111
        assert claims[0].pinned is True

    def test_rollback_reclaims_missing_fixed_workspace_for_held_owner(
        self, tmp_path: Path
    ) -> None:
        from sase.agent.hijack._recover_confirm_rollback import (
            _restore_held_workspace_custody,
        )
        from sase.running_field import get_claimed_workspaces

        project_file = tmp_path / "proj.sase"
        project_file.write_text("# Project: proj\nRUNNING:\n", encoding="utf-8")
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        record = make_record(
            artifacts,
            project_file=str(project_file),
            expected_claim_owner_pid=111,
        )
        launched = SimpleNamespace(
            workspace_num=3,
            workspace_dir="/ws/3",
            workflow_name="ace(run)-20261105_000000",
            cl_name="acme--4",
            timestamp="20261105000000",
        )

        restored, message = _restore_held_workspace_custody(record, 4242, launched)

        claims = get_claimed_workspaces(str(project_file))
        assert restored is True, message
        assert len(claims) == 1
        assert claims[0].workspace_num == 3
        assert claims[0].pid == 111
        assert claims[0].pinned is True

    def test_rollback_does_not_take_a_foreign_workspace_claim(
        self, tmp_path: Path
    ) -> None:
        from sase.agent.hijack._recover_confirm_rollback import (
            _restore_held_workspace_custody,
        )
        from sase.running_field import get_claimed_workspaces

        project_file = tmp_path / "proj.sase"
        project_file.write_text(
            "# Project: proj\nRUNNING:\n"
            "  #3 | 9999 | run | other-agent | 20261105000000\n",
            encoding="utf-8",
        )
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        record = make_record(
            artifacts,
            project_file=str(project_file),
            expected_claim_owner_pid=111,
        )
        launched = SimpleNamespace(workspace_num=3, workspace_dir="/ws/3")

        restored, message = _restore_held_workspace_custody(record, 4242, launched)

        claims = get_claimed_workspaces(str(project_file))
        assert restored is False
        assert "foreign pid 9999" in message
        assert len(claims) == 1
        assert claims[0].pid == 9999

    @pytest.mark.parametrize(
        ("ack_overrides", "expected_code"),
        [
            ({"model": "sonnet"}, "model_mismatch"),
            ({"effort": "low"}, "model_mismatch"),
            (
                {
                    "lineage": {
                        "hijack_id": "other-hijack",
                        "from_rung": "claude/opus@high",
                        "to_rung": "claude/opus@high",
                        "predecessor": "acme--3",
                    }
                },
                "lineage_mismatch",
            ),
        ],
    )
    def test_ack_mismatch_never_settles(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        ack_overrides: dict[str, Any],
        expected_code: str,
    ) -> None:
        flow = self._base(
            monkeypatch,
            tmp_path,
            spawn=spawned(4242, tmp_path / "succ"),
            ack_overrides=ack_overrides,
        )
        result = flow.recover()
        assert result.kind == "error"
        assert result.detail["code"] == expected_code
        assert flow.ledger.current["state"] == "held"
        assert flow.terminated == [4242]

    def test_rotated_target_fails_back_to_held(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        write_done(artifacts / "done.json")
        successor_dir = tmp_path / "succ"
        successor_dir.mkdir()
        record = make_record(artifacts)
        flow = Flow(
            monkeypatch,
            record,
            successor_dir,
            spawn=spawned(4242, successor_dir),
            execution_facts=lambda record, target, mode: {
                "schema_version": 1,
                "observed_resolver_pid": record.get("resolver_pid"),
                "resolver_pid_live": True,
                "resolver_identity_matches": True,
                "pinned_available": True,
                "current_target": (target if mode == "prepare" else "claude/opus@low"),
                "provider_disabled": False,
                "model_unavailable": False,
            },
        )
        # The public preview is not reopened after CAS. Execution policy sees
        # that the pinned target changed and refuses before spawn.
        result = flow.recover(action="escalate")
        assert result.kind == "refused"
        assert result.detail["code"] == "target_changed"
        assert flow.ledger.current["state"] == "held"
        assert flow.log == []
