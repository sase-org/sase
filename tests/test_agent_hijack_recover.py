"""Exactly-once keep-work recovery launch and settlement.

Covers phase ``resolution_launch``: the CAS transaction order (reservation
before effects, binding persisted before dispatch), repeat/retry behavior,
queued/error/uncertain outcomes, mandatory inheritance confirmation, and
idempotent predecessor settlement.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack.ledger import HijackLedgerConflict
from sase.agent.hijack.recover import _ClaimQueued, recover_hijacked_agent
from sase.agent.hijack.recover_common import (
    InheritanceEvidence,
    RecoveryDeps,
    RecoveryRefusal,
    RecoverySubject,
)
from sase.agent.hijack.recover_settle import (
    gather_recovery_inheritance,
    settle_recovery,
)


def _record(artifacts: Path, **overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": 1,
        "hijack_id": "h-123",
        "agent_name": "acme--3",
        "artifacts_dir": str(artifacts),
        "session": "acme",
        "project_file": "/tmp/proj.sase",
        "workspace_num": 3,
        "workspace_dir": "/ws/3",
        "pid": 111,
        "provider": "claude",
        "model": "opus",
        "effort": "high",
        "state": "held",
        "revision": 7,
    }
    record.update(overrides)
    return record


@dataclass(frozen=True)
class FakeRow:
    action: str
    available: bool
    reason: str | None
    target: str | None


@dataclass(frozen=True)
class FakePreview:
    revision: int
    rows: tuple[FakeRow, ...]
    state: str = "held"

    def action(self, name: str) -> FakeRow | None:
        return next((row for row in self.rows if row.action == name), None)


def _preview(
    revision: int = 7,
    *,
    escalate: str | None = "claude/opus@xhigh",
    continue_target: str | None = "claude/opus@high",
) -> FakePreview:
    rows = [
        FakeRow(
            "escalate",
            escalate is not None,
            None if escalate is not None else "no different model available",
            escalate,
        ),
        FakeRow("continue", continue_target is not None, None, continue_target),
        FakeRow("instruct", continue_target is not None, None, continue_target),
    ]
    return FakePreview(revision=revision, rows=tuple(rows))


def _subject(
    record: dict[str, Any],
    *,
    project_name: str | None = "proj",
    bead: str | None = "sase-1",
    goal: str | None = "goal-1",
    done_outcome: str | None = "hijacked",
) -> RecoverySubject:
    return RecoverySubject(
        record=dict(record),
        project_name=project_name,
        predecessor_meta={"bead_id": bead, "goal_id": goal} if bead else {},
        done_outcome=done_outcome,
        done_recovery={"state": "pending", "kind": "hijack"},
    )


_LAUNCH_FIELDS = (
    "launch_identity",
    "admission_request_id",
    "admission_identity",
    "launch_stage",
    "successor_pid",
    "successor_process_identity_token",
    "successor_artifacts_dir",
    "inheritance_acknowledged",
)


class FakeLedger:
    """In-memory stand-in for the ledger CAS with the real transition shape."""

    def __init__(self, record: dict[str, Any]) -> None:
        import threading

        self._lock = threading.Lock()
        self.current = dict(record)
        self.events: list[str] = []

    def cas(
        self, record: Mapping[str, Any], event: Mapping[str, Any]
    ) -> dict[str, Any]:
        with self._lock:
            return self._cas_locked(record, event)

    def _cas_locked(
        self, record: Mapping[str, Any], event: Mapping[str, Any]
    ) -> dict[str, Any]:
        if int(record.get("revision", -1)) != int(self.current.get("revision")):
            raise HijackLedgerConflict("stale revision")
        name = str(event.get("event"))
        nxt = dict(self.current)
        if name == "begin_resolution":
            if nxt.get("state") != "held":
                raise ValueError(f"illegal {nxt.get('state')} + begin_resolution")
            nxt["state"] = "resolving"
            for key in (
                "action",
                "reserved_successor_name",
                "concrete_target_model",
                "model_changed",
                "resolver_pid",
                "resolver_process_identity_token",
                *_LAUNCH_FIELDS,
            ):
                if key in event:
                    nxt[key] = event[key]
            nxt["error"] = None
        elif name == "record_launch":
            if nxt.get("state") != "resolving":
                raise ValueError(f"illegal {nxt.get('state')} + record_launch")
            for key in (*_LAUNCH_FIELDS, "error"):
                if key in event:
                    nxt[key] = event[key]
        elif name == "complete_resolution":
            if nxt.get("state") != "resolving":
                raise ValueError(f"illegal {nxt.get('state')} + complete_resolution")
            nxt["state"] = "resolved"
            for key in _LAUNCH_FIELDS:
                if key in event:
                    nxt[key] = event[key]
            nxt["error"] = None
        elif name == "resolution_failed":
            if nxt.get("state") != "resolving":
                raise ValueError(f"illegal {nxt.get('state')} + resolution_failed")
            nxt["state"] = "held"
            for key in _LAUNCH_FIELDS:
                nxt.pop(key, None)
            nxt["error"] = event.get("error")
        else:
            raise ValueError(f"unknown event {name}")
        nxt["revision"] = int(nxt.get("revision", 0)) + 1
        self.current = nxt
        self.events.append(name)
        return dict(nxt)

    def load(self, hijack_id: str) -> dict[str, Any] | None:
        if self.current.get("hijack_id") == hijack_id:
            return dict(self.current)
        return None


def _autonomy() -> dict[str, Any]:
    from sase.autonomy.record import resolve_selection

    return dict(resolve_selection("manual", source="inherited", surface="launch"))


def _evidence(**overrides: Any) -> InheritanceEvidence:
    evidence = InheritanceEvidence(
        predecessor_goal="goal-1",
        successor_goal="goal-1",
        predecessor_bead="sase-1",
        successor_bead="sase-1",
        baseline_inherited=True,
        predecessor_repo_count=0,
        transferred_repo_count=0,
        predecessor_autonomy=_autonomy(),
        predecessor_name="acme--3",
        parent_meta={"name": "acme--3"},
        child_meta={"name": "acme--4"},
    )
    if not overrides:
        return evidence
    payload = {**evidence.__dict__, **overrides}
    return InheritanceEvidence(**payload)


class _Flow:
    """Assembled executor seams with an observable call log."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        record: dict[str, Any],
        successor_dir: Path,
        *,
        preview: FakePreview | list[FakePreview] | None = None,
        spawn: Any = None,
        evidence: Any = "default",
        claim_ok: bool = True,
    ) -> None:
        from sase.agent.hijack import ledger

        self.ledger = FakeLedger(record)
        monkeypatch.setattr(ledger, "cas_advance_record", self.ledger.cas)
        monkeypatch.setattr(ledger, "load_record", self.ledger.load)
        self.log: list[str] = []
        self.terminated: list[int] = []
        self.record = record
        self.successor_dir = successor_dir
        self._preview = preview or _preview()
        self._spawn = spawn
        self._evidence = evidence
        self._claim_ok = claim_ok

    def deps(self) -> RecoveryDeps:
        flow = self

        def load_subject(agent_or_name: object) -> RecoverySubject | None:
            _ = agent_or_name
            return _subject(flow.record)

        def preview(record: Mapping[str, Any]) -> FakePreview:
            _ = record
            current = flow._preview
            if isinstance(current, list):
                if len(current) > 1:
                    return current.pop(0)
                return current[0]
            return current

        def build_prompt(record: Mapping[str, Any], **kwargs: Any) -> Any:
            _ = record
            return SimpleNamespace(
                prompt=f"PROMPT for {kwargs.get('model_target')}",
                context_mode="fork",
            )

        def resolve_plan(session_base: str, project_name: str | None) -> Any:
            assert session_base == "acme"
            assert project_name == "proj"
            return SimpleNamespace(agent_name="acme--4")

        def spawn(**kwargs: Any) -> Any:
            flow.log.append("spawn")
            assert kwargs["workspace_num"] == 3
            assert kwargs["workspace_dir"] == "/ws/3"
            assert kwargs["transfer_from_pid"] == 111
            assert kwargs["lineage"].hijack_id == "h-123"
            extra = kwargs["extra_env"]
            assert extra["SASE_HIJACK_RECOVERY_STRICT"] == "1"
            assert "SASE_HIJACK_RECOVERY_LINEAGE" in extra
            assert "SASE_HIJACK_LAUNCH_IDENTITY" in extra
            if isinstance(flow._spawn, Exception):
                raise flow._spawn
            return flow._spawn

        def gather(successor_dir: str | None, **kwargs: Any) -> Any:
            _ = (successor_dir, kwargs)
            if flow._evidence == "default":
                return _evidence()
            if isinstance(flow._evidence, dict):
                return None
            return flow._evidence

        def verify(**kwargs: Any) -> bool:
            _ = kwargs
            return flow._claim_ok

        def terminate(pid: int) -> None:
            flow.terminated.append(pid)

        return RecoveryDeps(
            load_subject=load_subject,
            preview=preview,  # type: ignore[arg-type]
            build_prompt=build_prompt,
            resolve_session_plan=resolve_plan,
            spawn_successor=spawn,
            gather_inheritance=gather,
            verify_claim=verify,
            terminate_pid=terminate,
            settle_timeout_seconds=0.01,
            settle_poll_seconds=0.001,
        )

    def recover(self, **kwargs: Any) -> Any:
        params = {"action": "continue", "deps": self.deps()}
        params.update(kwargs)
        return recover_hijacked_agent("acme--3", **params)


def _write_done(path: Path, outcome: str = "hijacked") -> None:
    import json

    path.write_text(
        json.dumps(
            {
                "outcome": outcome,
                "recovery": {"state": "pending", "kind": "hijack"},
            }
        ),
        encoding="utf-8",
    )


class TestRecoveryRefusals:
    def test_record_not_found(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        deps = RecoveryDeps(load_subject=lambda name: None)
        result = recover_hijacked_agent("ghost", action="continue", deps=deps)
        assert result.kind == "refused"
        assert result.detail["code"] == "record_not_found"

    def test_hijack_id_mismatch(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        flow = _Flow(monkeypatch, _record(artifacts), tmp_path / "succ")
        result = flow.recover(expected_hijack_id="other")
        assert result.kind == "refused"
        assert result.detail["code"] == "hijack_mismatch"
        assert flow.ledger.events == []

    def test_not_held_refuses(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        flow = _Flow(
            monkeypatch, _record(artifacts, state="requested"), tmp_path / "succ"
        )
        result = flow.recover()
        assert result.kind == "refused"
        assert result.detail["code"] == "not_held"
        assert flow.ledger.events == []

    def test_resolved_returns_resolution(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        record = _record(
            artifacts,
            state="resolved",
            reserved_successor_name="acme--4",
            launch_identity="launch-1",
        )
        flow = _Flow(monkeypatch, record, tmp_path / "succ")
        result = flow.recover()
        assert result.kind == "already_resolved"
        assert result.successor == "acme--4"
        assert result.launch_identity == "launch-1"
        assert flow.log == []

    def test_resolving_returns_current_resolution(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        record = _record(
            artifacts,
            state="resolving",
            reserved_successor_name="acme--4",
            launch_identity="launch-1",
        )
        flow = _Flow(monkeypatch, record, tmp_path / "succ")
        result = flow.recover(expected_revision=7)
        assert result.kind == "already_resolving"
        assert result.successor == "acme--4"
        assert flow.log == []

    def test_stale_revision_refuses(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        flow = _Flow(monkeypatch, _record(artifacts), tmp_path / "succ")
        result = flow.recover(expected_revision=6)
        assert result.kind == "refused"
        assert result.detail["code"] == "stale_revision"
        assert flow.ledger.events == []

    def test_stale_resolving_revision_refuses(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        record = _record(artifacts, state="resolving")
        flow = _Flow(monkeypatch, record, tmp_path / "succ")
        result = flow.recover(expected_revision=6)
        assert result.kind == "refused"
        assert result.detail["code"] == "stale_revision"

    def test_outcome_changed_refuses_before_cas(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        _write_done(artifacts / "done.json", outcome="done")
        record = _record(artifacts)
        flow = _Flow(monkeypatch, record, tmp_path / "succ")
        deps = flow.deps()
        deps.load_subject = lambda name: _subject(record, done_outcome="done")
        result = recover_hijacked_agent("acme--3", action="continue", deps=deps)
        assert result.kind == "refused"
        assert result.detail["code"] == "outcome_changed"
        assert flow.ledger.events == []


def _spawned(pid: int, successor_dir: Path) -> Any:
    return SimpleNamespace(
        agent_name="acme--4", pid=pid, artifacts_dir=str(successor_dir)
    )


class TestLaunchedRecovery:
    def _happy_flow(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        **kwargs: Any,
    ) -> tuple[_Flow, Any]:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        _write_done(artifacts / "done.json")
        successor_dir = tmp_path / "succ"
        successor_dir.mkdir()
        record = _record(artifacts)
        action = str(kwargs.pop("action", "continue"))
        flow = _Flow(monkeypatch, record, successor_dir, **kwargs)
        if flow._spawn is None:
            flow._spawn = _spawned(4242, successor_dir)
        result = flow.recover(action=action)
        return flow, result

    def test_continue_launches_and_settles(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import json

        flow, result = self._happy_flow(monkeypatch, tmp_path)
        assert result.kind == "launched"
        assert result.successor == "acme--4"
        assert result.launch_identity
        assert result.admission_request_id
        assert result.concrete_target == "claude/opus@high"
        assert result.model_changed is False
        # Binding persisted before dispatch: begin, then queued record_launch.
        assert flow.ledger.events[:2] == ["begin_resolution", "record_launch"]
        assert flow.ledger.events[-1] == "complete_resolution"
        assert flow.log == ["spawn"]
        # Ack staged in the successor dir; predecessor marker settled.
        from sase.agent.hijack.recovery_successor import read_recovery_ack

        ack = read_recovery_ack(str(flow.successor_dir))
        assert ack is not None and ack["goal"] == "goal-1"
        done = json.loads((tmp_path / "artifacts" / "done.json").read_text())
        assert done["outcome"] == "hijacked"
        assert done["recovery"]["state"] == "resolved"
        assert done["recovery"]["successor"] == "acme--4"
        assert done["recovery"]["model_changed"] is False
        from sase.agent.hijack.core import agent_hijack_status_for_done_marker

        assert (
            agent_hijack_status_for_done_marker("hijacked", done["recovery"])
            == "CONTINUED"
        )

    def test_escalate_settles_model_changed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import json

        flow, result = self._happy_flow(monkeypatch, tmp_path, action="escalate")
        assert result.kind == "launched"
        assert result.concrete_target == "claude/opus@xhigh"
        assert result.model_changed is True
        done = json.loads((tmp_path / "artifacts" / "done.json").read_text())
        assert done["recovery"]["model_changed"] is True
        from sase.agent.hijack.core import agent_hijack_status_for_done_marker

        assert (
            agent_hijack_status_for_done_marker("hijacked", done["recovery"])
            == "ESCALATED"
        )

    def test_repeat_call_returns_resolution_without_relaunch(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        flow, first = self._happy_flow(monkeypatch, tmp_path)
        assert first.kind == "launched"
        spawns = list(flow.log)
        # Fresh subject at the resolved revision: no second spawn.
        second = flow.recover()
        assert second.kind == "already_resolved"
        assert second.successor == "acme--4"
        assert flow.log == spawns

    def test_concurrent_resolvers_yield_one_successor(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import threading

        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        _write_done(artifacts / "done.json")
        successor_dir = tmp_path / "succ"
        successor_dir.mkdir()
        record = _record(artifacts)
        flow = _Flow(
            monkeypatch,
            record,
            successor_dir,
            spawn=_spawned(4242, successor_dir),
        )
        results: list[Any] = []

        def worker() -> None:
            results.append(flow.recover())

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        # Exactly one winner launches; the loser learns the resolution
        # (still resolving or already resolved, depending on interleaving).
        kinds = sorted(result.kind for result in results)
        assert kinds[1] == "launched"
        assert kinds[0] in ("already_resolving", "already_resolved")
        assert results[0].successor == results[1].successor == "acme--4"
        assert flow.log == ["spawn"]
        assert flow.ledger.current["state"] == "resolved"
        assert flow.ledger.current["reserved_successor_name"] == "acme--4"

    def test_stale_snapshot_loses_to_winner(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        _write_done(artifacts / "done.json")
        successor_dir = tmp_path / "succ"
        successor_dir.mkdir()
        record = _record(artifacts)
        flow = _Flow(
            monkeypatch,
            record,
            successor_dir,
            spawn=_spawned(4242, successor_dir),
        )
        first = flow.recover()
        assert first.kind == "launched"
        # A second resolver holding the pre-win snapshot retries the CAS,
        # loses, and learns the winner's resolution instead of launching.
        second = flow.recover()
        assert second.kind == "already_resolved"
        assert second.successor == "acme--4"
        assert flow.log == ["spawn"]


class TestQueuedAndFailedLaunches:
    def _base(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **kwargs: Any
    ) -> _Flow:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir(exist_ok=True)
        _write_done(artifacts / "done.json")
        successor_dir = tmp_path / "succ"
        successor_dir.mkdir(exist_ok=True)
        return _Flow(monkeypatch, _record(artifacts), successor_dir, **kwargs)

    def test_claim_contention_queues_and_holds(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        flow = self._base(monkeypatch, tmp_path, spawn=_ClaimQueued("no runner"))
        result = flow.recover()
        assert result.kind == "queued"
        assert result.successor == "acme--4"
        assert result.launch_identity
        # No terminal write: still resolving, custody keeps the workspace.
        assert flow.ledger.current["state"] == "resolving"
        assert flow.ledger.current["launch_stage"] == "queued"
        assert flow.log == ["spawn"]

    def test_definite_failure_returns_to_held(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        flow = self._base(monkeypatch, tmp_path, spawn=ValueError("bad workspace"))
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
        assert flow.ledger.current["error"] == "uncertain launch outcome: lost contact"

    def test_identity_mismatch_is_uncertain(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        flow = self._base(
            monkeypatch,
            tmp_path,
            spawn=_spawned(4242, tmp_path / "succ"),
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
            spawn=_spawned(4242, tmp_path / "succ"),
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
            spawn=_spawned(4242, tmp_path / "succ"),
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
            spawn=_spawned(4242, successor_dir),
            evidence=_evidence(successor_bead="other-bead"),
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
        _write_done(artifacts / "done.json")
        successor_dir = tmp_path / "succ"
        successor_dir.mkdir()
        record = _record(artifacts)
        flow = _Flow(
            monkeypatch,
            record,
            successor_dir,
            spawn=_spawned(4242, successor_dir),
            preview=[_preview(), _preview(escalate=None)],
        )
        # The fresh preview (used for revalidation) no longer offers the pin.
        result = flow.recover(action="escalate")
        assert result.kind == "refused"
        assert result.detail["code"] == "target_unavailable"
        assert flow.ledger.current["state"] == "held"
        assert flow.log == []


class TestSettleRecovery:
    def _resolving(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **overrides: Any
    ) -> tuple[FakeLedger, dict[str, Any]]:
        from sase.agent.hijack import ledger as ledger_module

        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        _write_done(artifacts / "done.json")
        record = _record(
            artifacts,
            state="resolving",
            resolution_action="continue",
            reserved_successor_name="acme--4",
            concrete_target_model="claude/opus@high",
            model_changed=False,
            launch_identity="launch-1",
            admission_request_id="req-1",
            admission_identity="fp-1",
        )
        record.update(overrides)
        ledger = FakeLedger(record)
        monkeypatch.setattr(ledger_module, "cas_advance_record", ledger.cas)
        monkeypatch.setattr(ledger_module, "load_record", ledger.load)
        return ledger, record

    def test_settle_writes_resolved_marker(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import json

        ledger, record = self._resolving(monkeypatch, tmp_path)
        updated = settle_recovery(
            record,
            action="continue",
            successor_name="acme--4",
            successor_pid=4242,
            successor_artifacts_dir=str(tmp_path / "succ"),
        )
        assert updated["state"] == "resolved"
        assert ledger.events == ["complete_resolution"]
        done = json.loads((tmp_path / "artifacts" / "done.json").read_text())
        assert done["outcome"] == "hijacked"
        assert done["recovery"] == {
            "state": "resolved",
            "kind": "hijack",
            "hijack_id": "h-123",
            "action": "continue",
            "successor": "acme--4",
            "model_changed": False,
            "launch_identity": "launch-1",
        }

    def test_settle_preserves_unrelated_done_fields(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import json

        ledger, record = self._resolving(monkeypatch, tmp_path)
        done_path = tmp_path / "artifacts" / "done.json"
        payload = json.loads(done_path.read_text())
        payload["patch_name"] = "keep-me"
        done_path.write_text(json.dumps(payload))
        settle_recovery(record, action="continue", successor_name="acme--4")
        done = json.loads(done_path.read_text())
        assert done["patch_name"] == "keep-me"
        assert done["recovery"]["successor"] == "acme--4"

    def test_settle_missing_done_marker_writes_minimal(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import json

        ledger, record = self._resolving(monkeypatch, tmp_path)
        (tmp_path / "artifacts" / "done.json").unlink()
        settle_recovery(record, action="escalate", successor_name="acme--4")
        done = json.loads((tmp_path / "artifacts" / "done.json").read_text())
        assert done["outcome"] == "hijacked"
        assert done["recovery"]["state"] == "resolved"

    def test_settle_refuses_non_hijack_outcome(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ledger, record = self._resolving(monkeypatch, tmp_path)
        _write_done(tmp_path / "artifacts" / "done.json", outcome="done")
        with pytest.raises(RecoveryRefusal, match="not hijacked"):
            settle_recovery(record, action="continue", successor_name="acme--4")
        assert ledger.events == []

    def test_settle_requires_resolving(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ledger, record = self._resolving(monkeypatch, tmp_path)
        record = {**record, "state": "held"}
        with pytest.raises(RecoveryRefusal, match="resolving"):
            settle_recovery(record, action="continue", successor_name="acme--4")
        assert ledger.events == []

    def test_settle_repairs_done_without_recas(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import json

        ledger, record = self._resolving(monkeypatch, tmp_path)
        resolved = dict(record, state="resolved")
        (tmp_path / "artifacts" / "done.json").unlink()
        # The ledger already advanced before the crash; repair only rewrites
        # the predecessor marker.
        ledger.current = dict(resolved)

        def _no_advance(record: Any, event: Any) -> Any:
            raise AssertionError("settlement repair must not CAS again")

        updated = settle_recovery(
            resolved,
            action="continue",
            successor_name="acme--4",
            advance_fn=_no_advance,
        )
        assert ledger.events == []
        done = json.loads((tmp_path / "artifacts" / "done.json").read_text())
        assert done["recovery"]["successor"] == "acme--4"
        assert updated["state"] == "resolved"

    def test_settle_resolved_for_other_successor_conflicts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ledger, record = self._resolving(monkeypatch, tmp_path)
        resolved = dict(record, state="resolved")
        with pytest.raises(HijackLedgerConflict):
            settle_recovery(resolved, action="continue", successor_name="acme--9")


class TestGatherInheritance:
    def test_no_successor_meta_is_not_ready(self, tmp_path: Path) -> None:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        subject = _subject(_record(artifacts))
        assert (
            gather_recovery_inheritance(subject, str(tmp_path / "succ-ghost")) is None
        )

    def test_populated_successor_gathers(self, tmp_path: Path) -> None:
        import json

        from sase.llm_provider.commit_finalizer_baseline import BASELINE_FILENAME

        predecessor = tmp_path / "artifacts"
        predecessor.mkdir()
        successor = tmp_path / "succ"
        successor.mkdir()
        (successor / "agent_meta.json").write_text(
            json.dumps({"name": "acme--4", "bead_id": "sase-1", "goal_id": "goal-1"})
        )
        (successor / BASELINE_FILENAME).write_text(json.dumps({"ok": True}))
        subject = _subject(_record(predecessor))
        evidence = gather_recovery_inheritance(subject, str(successor))
        assert evidence is not None
        assert evidence.baseline_inherited is True
        assert evidence.baseline_diagnostics == ()
        assert evidence.predecessor_repo_count == 0
        assert evidence.transferred_repo_count == 0
        assert evidence.successor_goal == "goal-1"
        assert evidence.successor_bead == "sase-1"

    def test_diagnostics_fail_the_baseline(self, tmp_path: Path) -> None:
        import json

        from sase.llm_provider.commit_finalizer_baseline import BASELINE_FILENAME
        from sase.llm_provider.commit_finalizer_inheritance import (
            INHERITANCE_DIAGNOSTICS_FILENAME,
        )

        predecessor = tmp_path / "artifacts"
        predecessor.mkdir()
        successor = tmp_path / "succ"
        successor.mkdir()
        (successor / "agent_meta.json").write_text(json.dumps({"name": "acme--4"}))
        (successor / BASELINE_FILENAME).write_text(json.dumps({"ok": True}))
        (successor / INHERITANCE_DIAGNOSTICS_FILENAME).write_text(
            json.dumps({"diagnostics": ["repo linked:checkout unavailable"]})
        )
        subject = _subject(_record(predecessor))
        evidence = gather_recovery_inheritance(subject, str(successor))
        assert evidence is not None
        assert evidence.baseline_inherited is False
        assert evidence.repo_diagnostics == ("repo linked:checkout unavailable",)
