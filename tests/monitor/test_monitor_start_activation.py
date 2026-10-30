"""Activation: staged CLI branch, monitor adopter, self-wait, and ordering.

Covers `sase-1pj.5.1.4`: in-agent flag-on starts stage instead of launching,
flag-off and non-agent starts keep the immediate path, the post-finalizer
monitor adopter launches from the frozen payload with the real custodian,
self-waits refuse with a `/sase_final` message, discard cleans unstarted
resources while held retains, and adoption waits for finalizer settlement.
"""

from __future__ import annotations

import argparse
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.feature_flags import override_flags


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    for key in (
        "SASE_AGENT",
        "SASE_AGENT_NAME",
        "SASE_ARTIFACTS_DIR",
        "SASE_NATIVE_HELPER",
        "SASE_FINALIZER_OWNED_TURN",
    ):
        monkeypatch.delenv(key, raising=False)


def _start_args(**overrides: Any) -> argparse.Namespace:
    base: dict[str, Any] = {
        "weight": None,
        "join": None,
        "monitor_command": None,
        "monitor_command_words": ["true"],
        "command": None,
        "reason": "verify activation",
        "checkpoint": None,
        "next": "follow up",
        "model": None,
        "profile": None,
        "policy": None,
        "completion": None,
        "start_status": "TESTING",
        "stop_status": "TESTED",
        "tail_lines": None,
        "timeout": "30s",
        "idle_timeout": None,
        "agent": None,
        "cwd": None,
        "label": None,
        "next_output": None,
        "json": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _write_agent_meta(artifacts: Path) -> None:
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "agent",
                "workspace_dir": str(artifacts.parent),
                "finalizer_status": {
                    "phase": "settled",
                    "status": "success",
                    "run_id": "controller-run-1",
                    "plan_digest": "digest-1",
                    "started_at": datetime(2026, 10, 28, 12, 1, tzinfo=UTC).timestamp(),
                },
            }
        ),
        encoding="utf-8",
    )


def test_staged_branch_reports_staged_without_kill_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from sase.main.monitor import start as start_module

    starter = tmp_path / "starter"
    starter.mkdir()
    monkeypatch.setenv("SASE_AGENT", "agent-1")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(starter))

    staged_record = SimpleNamespace(
        record=SimpleNamespace(
            monitor_id="monitor-abc",
            member_agent_name="agent-1--0",
            tool_run_id="run-123",
            tool_run_joined=False,
        ),
        staged_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        payload={},
        replayed=False,
    )
    calls: list[str] = []

    def fake_stage(request: Any) -> Any:
        calls.append("stage")
        return staged_record

    monkeypatch.setattr("sase.monitor.start_stage.stage_monitor", fake_stage)
    monkeypatch.setattr(
        start_module, "will_handoff_monitor_to_agent_runner", lambda: True
    )
    monkeypatch.setattr(
        start_module,
        "maybe_handoff_monitor_from_agent",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("must not kill on staged path")
        ),
    )
    monkeypatch.setattr(start_module, "resolve_cwd", lambda *a, **k: tmp_path)
    monkeypatch.setattr(start_module, "infer_project_name", lambda cwd: "proj")
    monkeypatch.setattr(
        start_module, "_monitor_start_project_name", lambda name: "proj"
    )

    # Enable the staged_handoffs beta flag for this branch.
    with override_flags(staged_handoffs=True):
        from sase.main.monitor.start import handle_monitor_start

        code = handle_monitor_start(_start_args(cwd=str(tmp_path)))
    assert code == 0
    assert calls == ["stage"]
    out = capsys.readouterr()
    assert out.out.startswith("Staged monitor")
    assert "Nothing starts until this turn ends" in out.out
    assert "/sase_final" in out.out
    # Staged path writes no legacy pending/in-flight kill markers.
    assert not (starter / ".sase_monitor_pending").exists()
    assert not (starter / ".sase_handoff_inflight.json").exists()
    assert list(starter.glob(".sase_handoff_inflight*")) == []


def test_staged_json_envelope_is_valid_json_with_prose_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    starter = tmp_path / "starter"
    starter.mkdir()
    monkeypatch.setenv("SASE_AGENT", "agent-1")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(starter))

    staged_record = SimpleNamespace(
        record=SimpleNamespace(
            monitor_id="monitor-abc",
            member_agent_name="agent-1--0",
            tool_run_id="run-123",
            tool_run_joined=False,
        ),
        staged_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        payload={},
        replayed=False,
    )
    monkeypatch.setattr(
        "sase.monitor.start_stage.stage_monitor", lambda request: staged_record
    )
    # monitor_start_json needs a real MonitorRecord shape; stub it.
    from sase.main.monitor import start as start_module2

    monkeypatch.setattr(
        "sase.main.monitor.start.monitor_start_json",
        lambda record, *, handed_off: {
            "schema_version": 3,
            "monitor": {"monitor_id": record.monitor_id},
            "handed_off": handed_off,
        },
    )
    monkeypatch.setattr(
        "sase.main.monitor.start.short_monitor_id", lambda monitor_id: "abc123"
    )
    monkeypatch.setattr(start_module2, "resolve_cwd", lambda *a, **k: tmp_path)
    monkeypatch.setattr(start_module2, "infer_project_name", lambda cwd: "proj")
    monkeypatch.setattr(
        start_module2, "_monitor_start_project_name", lambda name: "proj"
    )

    with override_flags(staged_handoffs=True):
        from sase.main.monitor.start import handle_monitor_start

        code = handle_monitor_start(_start_args(cwd=str(tmp_path), json=True))
    assert code == 0
    out = capsys.readouterr()
    envelope = json.loads(out.out)
    assert envelope["staged"] is True
    assert envelope["status"] == "staged"
    assert envelope["staged_id"] == "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    assert envelope["handed_off"] is False
    assert "Staged monitor" in out.err
    assert "/sase_final" in out.err


def test_flag_off_and_non_agent_keep_immediate_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main.monitor import start as start_module

    # Non-agent: even with the flag on, the immediate path is preserved.
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    starter = tmp_path / "starter"
    starter.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(starter))
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.monitor.start_stage.stage_monitor",
        lambda request: (_ for _ in ()).throw(
            AssertionError("must not stage off-agent")
        ),
    )
    monkeypatch.setattr(
        start_module,
        "start_monitor",
        lambda request: (
            calls.append("immediate")
            or SimpleNamespace(
                monitor_id="m1",
                member_agent_name="a",
                tool_run_id=None,
                tool_run_joined=False,
            )
        ),
    )
    monkeypatch.setattr(
        start_module, "will_handoff_monitor_to_agent_runner", lambda: False
    )
    monkeypatch.setattr(
        start_module, "maybe_handoff_monitor_from_agent", lambda record: False
    )
    monkeypatch.setattr(start_module, "short_monitor_id", lambda mid: "m1")
    monkeypatch.setattr(start_module, "resolve_cwd", lambda *a, **k: str(tmp_path))
    monkeypatch.setattr(start_module, "infer_project_name", lambda cwd: "proj")
    monkeypatch.setattr(
        start_module, "_monitor_start_project_name", lambda name: "proj"
    )
    with override_flags(staged_handoffs=True):
        from sase.main.monitor.start import handle_monitor_start

        assert handle_monitor_start(_start_args(agent="test-agent")) == 0
    assert calls == ["immediate"]

    # In-agent with the flag off also stays immediate.
    monkeypatch.setenv("SASE_AGENT", "agent-1")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    calls.clear()
    with override_flags(staged_handoffs=False):
        from sase.main.monitor.start import handle_monitor_start as handle2

        assert handle2(_start_args()) == 0
    assert calls == ["immediate"]


def test_monitor_adopter_is_registered_and_returns_real_custodian(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.axe.run_agent_exec_staged_adopters import STAGED_HANDOFF_ADOPTERS

    assert "monitor" in STAGED_HANDOFF_ADOPTERS
    adopter = STAGED_HANDOFF_ADOPTERS["monitor"]

    staged_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    member_dir = tmp_path / "member"
    member_dir.mkdir()
    monkeypatch.setattr(
        "sase.monitor.staged_owner.read_staged_owner_index",
        lambda monitor_id: {"staged_id": staged_id, "artifacts_dir": str(member_dir)},
    )
    launched: list[str] = []

    def fake_launch(artifacts_dir: str) -> Any:
        launched.append(artifacts_dir)
        return SimpleNamespace(monitor_id="monitor-1", artifacts_dir=str(member_dir))

    monkeypatch.setattr(
        "sase.monitor.start_stage.launch_from_persisted_payload", fake_launch
    )
    staged_record = {
        "staged_id": staged_id,
        "kind": "monitor",
        "payload": {"monitor_id": "monitor-1"},
    }
    from tests._axe_run_agent_exec_helpers import make_exec_ctx
    from sase.axe.run_agent_exec import LoopState as ExecLoopState

    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    # Align persisted identity with the live runner identity.
    from pathlib import Path as _Path

    meta_path = _Path(ctx.artifacts_dir) / "agent_meta.json"
    try:
        persisted = json.loads(meta_path.read_text(encoding="utf-8"))
        persisted_name = persisted.get("name") if isinstance(persisted, dict) else None
    except Exception:  # noqa: BLE001 - fall back to ctx identity.
        persisted_name = None
    run_metadata: dict[str, Any] = {"name": persisted_name or ctx.agent_name}
    state = ExecLoopState(
        current_prompt="p",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="p",
    )
    from sase.axe.run_agent_exec_staged import StagedInlineContinuation as _Cont

    continuation = _Cont(ctx=ctx, state=state)
    outcome = adopter(staged_record, run_metadata, continuation, "real response")
    assert launched == [str(member_dir)]
    assert outcome.outcome == "monitored"
    assert outcome.custodian == str(member_dir)
    assert outcome.refs is not None and outcome.refs["monitor_id"] == "monitor-1"


def test_self_wait_refuses_own_pending_staged_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.tool.control_wait import _staged_self_wait_refusal

    staged_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    starter = tmp_path / "starter"
    starter.mkdir()
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(starter))
    monkeypatch.setattr(
        "sase.agent.staged_handoff.read_staged_handoff",
        lambda artifacts_dir=None: {
            "staged_id": staged_id,
            "kind": "monitor",
            "payload": {
                "monitor_id": "monitor-1",
                "starter": {"agent_id": "agent-1"},
                "resources": {"tool_run_id": "run-reserved"},
            },
        },
    )
    monkeypatch.setattr(
        "sase.monitor.staged_owner.read_staged_owner_index",
        lambda monitor_id: {
            "staged_id": staged_id,
            "artifacts_dir": str(tmp_path / "m"),
        },
    )
    # Owned reserved run: same id refuses.
    msg = _staged_self_wait_refusal("run-reserved", {"run_id": "run-reserved"})
    assert msg is not None and "/sase_final" in msg
    # Joined run id stored in the same field also refuses.
    msg = _staged_self_wait_refusal("run-reserved", {"run_id": "run-reserved"})
    assert msg is not None
    # Unrelated run is allowed.
    assert _staged_self_wait_refusal("run-other", {"run_id": "run-other"}) is None


def test_self_wait_allows_after_adoption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.tool.control_wait import _staged_self_wait_refusal

    staged_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    starter = tmp_path / "starter"
    starter.mkdir()
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(starter))
    monkeypatch.setattr(
        "sase.agent.staged_handoff.read_staged_handoff",
        lambda artifacts_dir=None: {
            "staged_id": staged_id,
            "kind": "monitor",
            "payload": {
                "monitor_id": "monitor-1",
                "starter": {"agent_id": "agent-1"},
                "resources": {"tool_run_id": "run-reserved"},
            },
        },
    )
    # Index gone after adoption: the wait is allowed.
    monkeypatch.setattr(
        "sase.monitor.staged_owner.read_staged_owner_index", lambda monitor_id: None
    )
    assert _staged_self_wait_refusal("run-reserved", {"run_id": "run-reserved"}) is None


def test_adoption_waits_for_finalizer_settlement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The monitor check cannot launch before the commit finalizer settles."""
    from sase.axe.run_agent_exec_staged import dispatch_completed_staged_handoff
    from sase.axe.run_agent_exec_staged import StagedInlineContinuation
    from sase.agent.staged_handoff import write_staged_handoff
    from tests._axe_run_agent_exec_helpers import make_exec_ctx
    from sase.axe.run_agent_exec import LoopState

    staged_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    monkeypatch.setenv("SASE_AGENT", "agent")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent")
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    artifacts = Path(ctx.artifacts_dir)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    state = LoopState(
        current_prompt="p",
        current_role_suffix="",
        current_artifacts_dir=str(artifacts),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="p",
    )
    record = {
        "schema_version": 1,
        "staged_id": staged_id,
        "kind": "monitor",
        "created_at": "2026-10-26T12:00:00Z",
        "payload": {"monitor_id": "monitor-1"},
        "successor_workspace": "inherit",
        "carry_allowed": True,
        "dirty_obligations_at_stage": [],
    }
    write_staged_handoff(record, artifacts_dir=str(artifacts))
    _write_agent_meta(artifacts)
    # Unsettled finalizer: adoption is held and no proc launches.
    (artifacts / "finalizer_result.json").write_text(
        json.dumps({"status": "running", "instances": []}), encoding="utf-8"
    )
    launches: list[str] = []
    monkeypatch.setattr(
        "sase.monitor.staged_owner.read_staged_owner_index",
        lambda monitor_id: {
            "staged_id": staged_id,
            "artifacts_dir": str(tmp_path / "m"),
        },
    )
    monkeypatch.setattr(
        "sase.monitor.start_stage.launch_from_persisted_payload",
        lambda member_dir: (
            launches.append(member_dir)
            or SimpleNamespace(monitor_id="m", artifacts_dir=member_dir)
        ),
    )
    dispatch = dispatch_completed_staged_handoff(
        str(artifacts), StagedInlineContinuation(ctx=ctx, state=state)
    )
    assert dispatch is not None and dispatch.adopted is False
    assert launches == []

    # Settled finalizer (commit hook included): one launch proceeds.
    (artifacts / "finalizer_result.json").write_text(
        json.dumps({"status": "success", "instances": []}), encoding="utf-8"
    )
    import sase.axe.run_agent_exec_staged_dispatch as dispatch_mod

    monkeypatch.setattr(
        dispatch_mod, "finalizer_settlement_refusal", lambda *a, **k: None
    )
    monkeypatch.setattr(
        dispatch_mod, "read_staged_handoff_response", lambda *a, **k: "real response"
    )
    dispatch = dispatch_completed_staged_handoff(
        str(artifacts), StagedInlineContinuation(ctx=ctx, state=state)
    )
    assert dispatch is not None and dispatch.adopted is True
    assert dispatch.outcome == "monitored"
    assert launches == [str(tmp_path / "m")]
