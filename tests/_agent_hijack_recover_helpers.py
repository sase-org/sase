"""Shared fixtures for the agent hijack recovery tests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack.ledger import HijackLedgerConflict
from sase.agent.hijack.recover import recover_hijacked_agent
from sase.agent.hijack.recover_common import (
    InheritanceEvidence,
    RecoveryDeps,
    RecoverySubject,
)


def record(artifacts: Path, **overrides: Any) -> dict[str, Any]:
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
        "expected_claim_owner_pid": 111,
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


def make_preview(
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


def subject(
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
                    record_key = "resolution_action" if key == "action" else key
                    nxt[record_key] = event[key]
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


def autonomy() -> dict[str, Any]:
    from sase.autonomy.record import resolve_selection

    return dict(resolve_selection("manual", source="inherited", surface="launch"))


def evidence(**overrides: Any) -> InheritanceEvidence:
    evidence = InheritanceEvidence(
        predecessor_goal="goal-1",
        successor_goal="goal-1",
        predecessor_bead="sase-1",
        successor_bead="sase-1",
        baseline_inherited=True,
        predecessor_repo_count=0,
        transferred_repo_count=0,
        predecessor_autonomy=autonomy(),
        predecessor_name="acme--3",
        parent_meta={"name": "acme--3"},
        child_meta={"name": "acme--4"},
    )
    if not overrides:
        return evidence
    payload = {**evidence.__dict__, **overrides}
    return InheritanceEvidence(**payload)


class Flow:
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
        execution_facts: Any = None,
    ) -> None:
        from sase.agent.hijack import ledger

        self.log: list[str] = []
        self.terminated: list[int] = []
        self.preview_states: list[str | None] = []
        self.prompt_prepared_before_cas = False
        self.spawned_prompt: str | None = None
        self.spawned_descriptor: dict[str, Any] | None = None
        self.spawned_extra_env: dict[str, str] | None = None
        self.record = record
        self.successor_dir = successor_dir
        project_file = successor_dir.parent / "proj.sase"
        project_file.write_text(
            "\n".join(
                (
                    "# Project: proj",
                    "RUNNING:",
                    "  #3 | 111 | ace(run)-20261105_000000 | acme--3 | "
                    "20261105000000 | PINNED",
                    "",
                )
            ),
            encoding="utf-8",
        )
        self.record["project_file"] = str(project_file)
        self.ledger = FakeLedger(self.record)
        monkeypatch.setattr(ledger, "cas_advance_record", self.ledger.cas)
        monkeypatch.setattr(ledger, "load_record", self.ledger.load)
        from sase.core import paths
        from sase.agent.hijack import recovery_admission

        monkeypatch.setattr(
            recovery_admission, "_target_available", lambda target: (True, None)
        )

        self.admission_root = successor_dir.parent / ".sase"
        monkeypatch.setattr(
            paths,
            "sase_subdir",
            lambda subdir: self.admission_root / subdir,
        )
        self._preview = preview or make_preview()
        self._spawn = spawn
        self._evidence = evidence
        self._claim_ok = claim_ok
        self._execution_facts = execution_facts

    def deps(self) -> RecoveryDeps:
        flow = self

        def load_subject(agent_or_name: object) -> RecoverySubject | None:
            _ = agent_or_name
            return subject(flow.record)

        def preview(record: Mapping[str, Any]) -> FakePreview:
            flow.preview_states.append(
                str(record.get("state")) if record.get("state") is not None else None
            )
            current = flow._preview
            if isinstance(current, list):
                if len(current) > 1:
                    return current.pop(0)
                return current[0]
            return current

        def build_prompt(record: Mapping[str, Any], **kwargs: Any) -> Any:
            _ = record
            flow.prompt_prepared_before_cas = not flow.ledger.events
            return SimpleNamespace(
                prompt=f"PROMPT for {kwargs.get('model_target')}",
                context_mode="fork",
            )

        def execution_facts(
            record: Mapping[str, Any], target: str, mode: str
        ) -> Mapping[str, Any]:
            if flow._execution_facts is not None:
                return flow._execution_facts(record, target, mode)
            return {
                "schema_version": 1,
                "observed_resolver_pid": record.get("resolver_pid"),
                "resolver_pid_live": True,
                "resolver_identity_matches": True,
                "pinned_available": True,
                "pinned_unavailable_reason": None,
                "current_target": target,
                "provider_disabled": False,
                "model_unavailable": False,
            }

        def resolve_plan(session_base: str, project_name: str | None) -> Any:
            assert session_base == "acme"
            assert project_name == "proj"
            return SimpleNamespace(agent_name="acme--4")

        def spawn(**kwargs: Any) -> Any:
            flow.log.append("spawn")
            flow.spawned_prompt = str(kwargs["prompt"])
            flow.spawned_descriptor = dict(kwargs["descriptor"])
            flow.spawned_extra_env = dict(kwargs["extra_env"])
            assert kwargs["workspace_num"] == 3
            assert kwargs["workspace_dir"] == "/ws/3"
            assert kwargs["transfer_from_pid"] == 111
            assert kwargs["lineage"].hijack_id == "h-123"
            assert kwargs["descriptor"]["launch_identity"]
            assert kwargs["descriptor"]["reserved_successor_name"] == "acme--4"
            extra = kwargs["extra_env"]
            assert extra["SASE_HIJACK_RECOVERY_STRICT"] == "1"
            assert "SASE_HIJACK_RECOVERY_LINEAGE" in extra
            assert "SASE_HIJACK_LAUNCH_IDENTITY" in extra
            assert "SASE_HIJACK_RECOVERY_DESCRIPTOR" in extra
            if isinstance(flow._spawn, Exception):
                raise flow._spawn
            return flow._spawn

        def gather(successor_dir: str | None, **kwargs: Any) -> Any:
            _ = (successor_dir, kwargs)
            if flow._evidence == "default":
                return evidence()
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
            execution_facts=execution_facts,
            resolve_session_plan=resolve_plan,
            spawn_successor=spawn,
            gather_inheritance=gather,
            verify_claim=verify,
            terminate_pid=terminate,
            admission_spawn_coordinator=False,
            settle_timeout_seconds=0.01,
            settle_poll_seconds=0.001,
        )

    def recover(self, **kwargs: Any) -> Any:
        params = {"action": "continue", "deps": self.deps()}
        params.update(kwargs)
        return recover_hijacked_agent("acme--3", **params)


def write_done(path: Path, outcome: str = "hijacked") -> None:
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


def spawned(pid: int, successor_dir: Path) -> Any:
    return SimpleNamespace(
        agent_name="acme--4", pid=pid, artifacts_dir=str(successor_dir)
    )
