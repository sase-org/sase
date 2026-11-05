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

    def test_identity_mismatch_is_uncertain(
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
        assert result.kind == "uncertain"
        assert flow.ledger.current["state"] == "resolving"

    def test_missing_boot_evidence_is_uncertain(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        flow = self._base(
            monkeypatch,
            tmp_path,
            spawn=spawned(4242, tmp_path / "succ"),
            evidence={},
        )
        result = flow.recover()
        assert result.kind == "uncertain"
        assert flow.ledger.current["state"] == "resolving"

    def test_unverified_claim_is_uncertain(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        flow = self._base(
            monkeypatch,
            tmp_path,
            spawn=spawned(4242, tmp_path / "succ"),
            claim_ok=False,
        )
        result = flow.recover()
        assert result.kind == "uncertain"
        assert flow.ledger.current["state"] == "resolving"

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
        assert result.detail["code"] == "inheritance_failed"
        assert flow.ledger.current["state"] == "held"
        assert flow.terminated == [4242]
        assert not (successor_dir / "hijack_recovery_ack.json").exists()

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
