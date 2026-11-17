"""Monitor rerun recovery: command preservation, same workspace, at-most-once."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack import _preview_monitor as monitor_impl
from sase.agent.hijack import preview as recovery_preview
from sase.agent.hijack.core import assemble_hijack_recovery_preview
from sase.agent.hijack.recover import recover_hijacked_agent
from sase.agent.hijack.recover_common import RecoveryDeps, RecoverySubject
from sase.agent.hijack.recover_target import resolve_effective_target


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _descriptor(
    *,
    artifacts: Path,
    command: str | None = "echo rerun-ok",
    cwd: str = "/ws/3",
    workspace_dir: str = "/ws/3",
    argv: list[str] | None = None,
    next_action: str | None = "Resume the recorded follow-up.",
    next_model: str | None = "codex/gpt-5.4@high",
) -> dict[str, Any]:
    followup: dict[str, Any] = {}
    if next_action is not None:
        followup["monitor_next_action"] = next_action
    if next_model is not None:
        followup["monitor_next_model"] = next_model
    payload: dict[str, Any] = {
        "schema_version": 1,
        "hijack_id": "h-mon",
        "monitor_id": "mon-1",
        "command": command,
        "cwd": cwd,
        "workspace_dir": workspace_dir,
        "timeout_seconds": 120,
        "idle_timeout_seconds": 0,
        "output_policy": "tail",
        "followup": followup,
        "command_result": {"state": "stopped", "exit_code": 143},
        "output_locators": {},
    }
    if argv is not None:
        payload["execution_argv"] = argv
    if command is None:
        payload.pop("command", None)
    return payload


def _monitor_record(
    artifacts: Path, descriptor_path: Path | None, **overrides: Any
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": 1,
        "hijack_id": "h-mon",
        "agent_name": "acme--3",
        "artifacts_dir": str(artifacts),
        "session": "acme",
        "project_file": "/tmp/proj.sase",
        "workspace_num": 3,
        "workspace_dir": "/ws/3",
        "provider": "claude",
        "model": "opus",
        "effort": "high",
        "scope": "monitor",
        "state": "held",
        "revision": 7,
        "expected_claim_owner_pid": 111,
        "snapshots": [{"reference": "snap-mon"}],
    }
    if descriptor_path is not None:
        record["suppressed_followup"] = {
            "kind": "monitor_followup",
            "ref": str(descriptor_path),
        }
    record.update(overrides)
    return record


def _write_recovery(
    artifacts: Path, **descriptor_kwargs: Any
) -> tuple[dict[str, Any], Path]:
    artifacts.mkdir(parents=True, exist_ok=True)
    _write_json(artifacts / "agent_meta.json", {})
    _write_json(
        artifacts / "done.json",
        {"outcome": "hijacked", "monitor_followup_outcome": "hijacked"},
    )
    descriptor_path = artifacts / "hijack_recovery" / "h-mon.json"
    _write_json(descriptor_path, _descriptor(artifacts=artifacts, **descriptor_kwargs))
    return _monitor_record(artifacts, descriptor_path), descriptor_path


def test_rerun_available_with_valid_command_and_workspace(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    record, _ = _write_recovery(artifacts)
    assert monitor_impl.monitor_rerun_reason(record, str(artifacts)) is None


def test_rerun_disabled_without_command(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    record, _ = _write_recovery(artifacts, command=None)
    reason = monitor_impl.monitor_rerun_reason(record, str(artifacts))
    assert reason is not None and "command" in reason


def test_rerun_disabled_without_workspace(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    record, _ = _write_recovery(artifacts)
    record["workspace_dir"] = ""
    reason = monitor_impl.monitor_rerun_reason(record, str(artifacts))
    assert reason is not None and "workspace" in reason


def test_rerun_disabled_without_descriptor(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    record = _monitor_record(artifacts, None)
    reason = monitor_impl.monitor_rerun_reason(record, str(artifacts))
    assert reason is not None and "descriptor" in reason


def test_rerun_available_even_when_followup_missing(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    record, _ = _write_recovery(artifacts, next_action=None, next_model=None)
    facts = monitor_impl.monitor_followup_facts(record, str(artifacts))
    assert facts.available is False
    assert monitor_impl.monitor_rerun_reason(record, str(artifacts)) is None


def test_rerun_preview_row_is_available_for_monitor(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    record, _ = _write_recovery(artifacts)
    preview = recovery_preview.hijack_recovery_preview(record)
    row = preview.action("rerun")
    assert row is not None
    assert row.available is True
    assert row.label == "Re-run command"
    assert "held workspace" in row.detail


def test_llm_preview_has_no_rerun_row(tmp_path: Path, monkeypatch: Any) -> None:
    from sase.agent.hijack import _preview_recovery as recovery_impl

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _write_json(artifacts / "agent_meta.json", {})
    monkeypatch.setattr(
        recovery_impl,
        "agent_hijack_config",
        lambda: SimpleNamespace(
            escalation_ladder=("@large", "@xlarge"), successor_context="fork"
        ),
    )
    monkeypatch.setattr(recovery_impl, "build_alias_candidates", lambda ladder: {})
    record: dict[str, Any] = {
        "schema_version": 1,
        "hijack_id": "h-llm",
        "agent_name": "acme--3",
        "artifacts_dir": str(artifacts),
        "session": "acme",
        "workspace_num": 3,
        "workspace_dir": "/ws/3",
        "provider": "claude",
        "model": "opus",
        "scope": "",
        "state": "held",
        "revision": 7,
    }
    preview = recovery_impl.hijack_recovery_preview(record)
    assert preview.action("rerun") is None


def test_rerun_rust_preview_available_when_no_reason() -> None:
    preview = assemble_hijack_recovery_preview(
        {
            "schema_version": 1,
            "hijack_id": "h-mon",
            "revision": 2,
            "state": "held",
            "scope": "monitor",
            "followup_available": False,
            "followup_reason": "recorded monitor follow-up is missing",
            "header": {"agent_name": "acme--3", "workspace_num": 3},
            "escalate": {
                "schema_version": 1,
                "available": False,
                "reason": "missing",
            },
        }
    )
    by_action = {item["action"]: item for item in preview["actions"]}
    assert by_action["rerun"]["available"] is True
    assert by_action["rerun"]["label"] == "Re-run command"


def test_rerun_rust_preview_disabled_with_reason() -> None:
    preview = assemble_hijack_recovery_preview(
        {
            "schema_version": 1,
            "hijack_id": "h-mon",
            "revision": 2,
            "state": "held",
            "scope": "monitor",
            "followup_available": False,
            "rerun_reason": "monitor command is unavailable",
            "header": {"agent_name": "acme--3", "workspace_num": 3},
            "escalate": {
                "schema_version": 1,
                "available": False,
                "reason": "missing",
            },
        }
    )
    by_action = {item["action"]: item for item in preview["actions"]}
    assert by_action["rerun"]["available"] is False
    assert "command" in (by_action["rerun"]["reason"] or "")


def test_rerun_effective_target_uses_stalled_and_refuses_llm(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    record, _ = _write_recovery(artifacts)
    target = resolve_effective_target(
        action="rerun",
        record=record,
        preview_action={"available": True, "reason": None, "target": None},
        model_override=None,
        prompt_text=None,
    )
    assert target.action == "rerun"
    assert target.concrete_target == "claude/opus@high"
    llm_record = dict(record)
    llm_record["scope"] = "llm"
    with pytest.raises(Exception, match="monitor"):
        resolve_effective_target(
            action="rerun",
            record=llm_record,
            preview_action={"available": True, "reason": None, "target": None},
            model_override=None,
            prompt_text=None,
        )


def test_rerun_rejects_model_and_prompt(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    record, _ = _write_recovery(artifacts)
    with pytest.raises(Exception, match="model"):
        resolve_effective_target(
            action="rerun",
            record=record,
            preview_action={"available": True, "reason": None, "target": None},
            model_override="codex/gpt-5.4@high",
            prompt_text=None,
        )
    with pytest.raises(Exception, match="prompt"):
        resolve_effective_target(
            action="rerun",
            record=record,
            preview_action={"available": True, "reason": None, "target": None},
            model_override=None,
            prompt_text="edited",
        )


class _Ledger:
    def __init__(self, record: dict[str, Any]) -> None:
        import threading

        self._lock = threading.Lock()
        self.current = dict(record)
        self.events: list[str] = []

    def cas(self, record: Any, event: Any) -> dict[str, Any]:
        from sase.agent.hijack.ledger import HijackLedgerConflict

        with self._lock:
            if int(record.get("revision", -1)) != int(self.current.get("revision")):
                raise HijackLedgerConflict("stale revision")
            name = str(event.get("event"))
            nxt = dict(self.current)
            if name == "begin_resolution":
                if nxt.get("state") != "held":
                    raise ValueError(f"illegal {nxt.get('state')} + begin_resolution")
                nxt["state"] = "resolving"
                nxt["resolution_action"] = event.get("action")
                for key in (
                    "reserved_successor_name",
                    "concrete_target_model",
                    "model_changed",
                    "resolver_pid",
                    "launch_identity",
                    "admission_request_id",
                    "admission_identity",
                ):
                    if key in event:
                        nxt[key] = event[key]
                nxt["error"] = None
            elif name == "record_launch":
                if nxt.get("state") != "resolving":
                    raise ValueError(f"illegal {nxt.get('state')} + record_launch")
                for key in (
                    "launch_identity",
                    "admission_request_id",
                    "admission_identity",
                    "launch_stage",
                    "error",
                ):
                    if key in event:
                        nxt[key] = event[key]
            elif name == "complete_resolution":
                if nxt.get("state") != "resolving":
                    raise ValueError(
                        f"illegal {nxt.get('state')} + complete_resolution"
                    )
                nxt["state"] = "resolved"
                for key in (
                    "successor_name",
                    "successor_pid",
                    "successor_artifacts_dir",
                    "launch_identity",
                    "admission_request_id",
                    "admission_identity",
                    "launch_stage",
                ):
                    if key in event:
                        nxt[key] = event[key]
                nxt["reserved_successor_name"] = event.get("successor_name")
                nxt["error"] = None
            elif name == "resolution_failed":
                if nxt.get("state") != "resolving":
                    raise ValueError(f"illegal {nxt.get('state')} + resolution_failed")
                nxt["state"] = "held"
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


def _rerun_deps(
    monkeypatch: Any,
    record: dict[str, Any],
    successor_dir: Path,
    *,
    spawn: Any = None,
    verify_claim: bool = True,
) -> tuple[RecoveryDeps, _Ledger, list[Any]]:
    from sase.agent.hijack import ledger

    requests: list[Any] = []
    fake = _Ledger(record)
    monkeypatch.setattr(ledger, "cas_advance_record", fake.cas)
    monkeypatch.setattr(ledger, "load_record", fake.load)

    def load_subject(agent_or_name: object) -> RecoverySubject:
        return RecoverySubject(
            record=dict(record),
            project_name="proj",
            predecessor_meta={},
            done_outcome="hijacked",
            done_recovery={"state": "pending", "kind": "hijack"},
        )

    def preview(rec: Any) -> Any:
        from sase.agent.hijack._preview_models import RecoveryAction, RecoveryPreview

        return RecoveryPreview(
            hijack_id="h-mon",
            revision=int(rec.get("revision", 7)),
            header={},
            default_action="rerun",
            actions=(
                RecoveryAction(
                    action="rerun",
                    available=True,
                    reason=None,
                    label="Re-run command",
                    detail="same command in the held workspace",
                    target=None,
                ),
            ),
            state=str(rec.get("state", "held")),
            _record=dict(rec),
            _artifacts_dir=str(rec.get("artifacts_dir", "")),
        )

    def resolve_plan(session_base: str, project_name: str | None) -> Any:
        assert session_base == "acme"
        return SimpleNamespace(agent_name="acme--4")

    def start_monitor(request: Any) -> Any:
        requests.append(request)
        if isinstance(spawn, Exception):
            raise spawn
        assert request.command == "echo rerun-ok"
        assert request.cwd == "/ws/3"
        assert request.project_name == "proj"
        assert request.lane == "acme"
        assert request.transfer_claim_from_pid == 111
        assert request.inherit_lane_workspace_claim is True
        successor_dir.mkdir(parents=True, exist_ok=True)
        _write_json(
            successor_dir / "agent_meta.json",
            {"name": "acme--4", "monitor_id": "mon-2"},
        )
        return SimpleNamespace(
            member_agent_name="acme--4",
            artifacts_dir=str(successor_dir),
            pid=4242,
            monitor_id="mon-2",
            command="echo rerun-ok",
            cwd="/ws/3",
            workspace_num=3,
            workspace_dir="/ws/3",
        )

    deps = RecoveryDeps(
        load_subject=load_subject,
        preview=preview,
        resolve_session_plan=resolve_plan,
        spawn_successor=start_monitor,
        verify_claim=lambda **kwargs: verify_claim,
    )
    return deps, fake, requests


def test_rerun_preserves_command_and_workspace(
    tmp_path: Path, monkeypatch: Any
) -> None:
    artifacts = tmp_path / "artifacts"
    record, _ = _write_recovery(artifacts)
    successor_dir = tmp_path / "succ"
    deps, fake, requests = _rerun_deps(monkeypatch, record, successor_dir)
    result = recover_hijacked_agent("acme--3", action="rerun", deps=deps)
    assert result.kind == "launched"
    assert result.successor == "acme--4"
    assert len(requests) == 1
    assert requests[0].command == "echo rerun-ok"
    assert requests[0].cwd == "/ws/3"
    assert fake.current["state"] == "resolved"
    done = json.loads((artifacts / "done.json").read_text())
    assert done["monitor_followup_outcome"] == "hijacked"
    assert done["recovery"]["action"] == "rerun"


def test_rerun_uses_new_monitor_id_and_suppresses_old_delivery(
    tmp_path: Path, monkeypatch: Any
) -> None:
    artifacts = tmp_path / "artifacts"
    record, _ = _write_recovery(artifacts)
    successor_dir = tmp_path / "succ"
    deps, _, requests = _rerun_deps(monkeypatch, record, successor_dir)
    result = recover_hijacked_agent("acme--3", action="rerun", deps=deps)
    assert result.kind == "launched"
    assert requests[0].command == "echo rerun-ok"
    done = json.loads((artifacts / "done.json").read_text())
    assert done["monitor_followup_outcome"] == "hijacked"
    assert done["recovery"]["successor"] == "acme--4"


def test_duplicate_rerun_does_not_launch_twice(
    tmp_path: Path, monkeypatch: Any
) -> None:
    artifacts = tmp_path / "artifacts"
    record, _ = _write_recovery(artifacts)
    successor_dir = tmp_path / "succ"
    calls: list[int] = []

    def counting_start(request: Any) -> Any:
        calls.append(1)
        successor_dir.mkdir(parents=True, exist_ok=True)
        _write_json(successor_dir / "agent_meta.json", {"name": "acme--4"})
        return SimpleNamespace(
            member_agent_name="acme--4",
            artifacts_dir=str(successor_dir),
            pid=4242,
            monitor_id="mon-2",
            command="echo rerun-ok",
            cwd="/ws/3",
            workspace_num=3,
            workspace_dir="/ws/3",
        )

    from sase.agent.hijack import ledger

    fake = _Ledger(record)
    monkeypatch.setattr(ledger, "cas_advance_record", fake.cas)
    monkeypatch.setattr(ledger, "load_record", fake.load)

    def load_subject(agent_or_name: object) -> RecoverySubject:
        return RecoverySubject(
            record=dict(fake.current),
            project_name="proj",
            predecessor_meta={},
            done_outcome="hijacked",
            done_recovery={"state": "pending", "kind": "hijack"},
        )

    def preview(rec: Any) -> Any:
        from sase.agent.hijack._preview_models import RecoveryAction, RecoveryPreview

        return RecoveryPreview(
            hijack_id="h-mon",
            revision=int(rec.get("revision", 7)),
            header={},
            default_action="rerun",
            actions=(
                RecoveryAction(
                    action="rerun",
                    available=rec.get("state") == "held",
                    reason=None
                    if rec.get("state") == "held"
                    else "already being resolved",
                    label="Re-run command",
                    detail="",
                    target=None,
                ),
            ),
            state=str(rec.get("state", "held")),
            _record=dict(rec),
            _artifacts_dir=str(rec.get("artifacts_dir", "")),
        )

    deps = RecoveryDeps(
        load_subject=load_subject,
        preview=preview,
        resolve_session_plan=lambda s, p: SimpleNamespace(agent_name="acme--4"),
        spawn_successor=counting_start,
        verify_claim=lambda **kwargs: True,
    )
    first = recover_hijacked_agent("acme--3", action="rerun", deps=deps)
    assert first.kind == "launched"
    second = recover_hijacked_agent("acme--3", action="rerun", deps=deps)
    assert second.kind == "already_resolved"
    assert second.successor == "acme--4"
    assert len(calls) == 1


def test_failed_rerun_start_returns_to_held(tmp_path: Path, monkeypatch: Any) -> None:
    artifacts = tmp_path / "artifacts"
    record, _ = _write_recovery(artifacts)
    successor_dir = tmp_path / "succ"
    deps, fake, _ = _rerun_deps(
        monkeypatch, record, successor_dir, spawn=RuntimeError("boom")
    )
    result = recover_hijacked_agent("acme--3", action="rerun", deps=deps)
    assert result.kind == "error"
    assert fake.current["state"] == "held"


def test_stale_claim_refuses_rerun_with_reason(
    tmp_path: Path, monkeypatch: Any
) -> None:
    artifacts = tmp_path / "artifacts"
    record, _ = _write_recovery(artifacts)
    successor_dir = tmp_path / "succ"
    deps, fake, _ = _rerun_deps(monkeypatch, record, successor_dir, verify_claim=False)
    result = recover_hijacked_agent("acme--3", action="rerun", deps=deps)
    assert result.kind == "error"
    assert "claim" in (result.message or "").lower()
    assert fake.current["state"] == "held"


def test_real_short_command_runs_with_recorded_argv(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    _, descriptor_path = _write_recovery(
        artifacts,
        command="echo rerun-ok",
        argv=["echo", "rerun-ok"],
        cwd=str(tmp_path),
        workspace_dir=str(tmp_path),
    )
    descriptor = json.loads(descriptor_path.read_text())
    assert descriptor["command"] == "echo rerun-ok"
    assert descriptor["execution_argv"] == ["echo", "rerun-ok"]
    completed = subprocess.run(
        [str(item) for item in descriptor["execution_argv"]],
        cwd=descriptor["cwd"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == "rerun-ok"
