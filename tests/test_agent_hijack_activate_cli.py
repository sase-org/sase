"""Activate-CLI tests: finalizer/staged latch, exit 3, cancel/explain/now."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack._stop_models import StopDeps
from sase.agent.hijack.stop import stop_agent_for_hijack
from sase.running_field import WorkspaceClaim
from tests._running_field_helpers import create_project_file_with_running

_AGENT = "sase-7f.2"
_TS = "20260712120000"
_PID = 424242
_WS = 4


def _artifacts(tmp_path: Path, meta: dict[str, Any]) -> Path:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(exist_ok=True)
    base = {
        "name": _AGENT,
        "agent_session": "sase-7f",
        "pid": _PID,
        "runner_capabilities": ["hijack"],
        "process_identity": "boot:123",
    }
    base.update(meta)
    (artifacts / "agent_meta.json").write_text(json.dumps(base))
    return artifacts


def _project_file(tmp_path: Path) -> str:
    return create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(
                _WS,
                "ace(run)-260712_120000",
                "feature",
                pid=_PID,
                artifacts_timestamp=_TS,
            )
        ],
    )


def _install_target(
    monkeypatch: pytest.MonkeyPatch, artifacts: Path, project_file: str
) -> None:
    def fake_fields(agent: Any) -> tuple[Any, str, str, str, bool]:
        return Path(agent.artifacts_dir), "proj", project_file, _TS, False

    monkeypatch.setattr("sase.agent.running.named_agent_project_fields", fake_fields)
    monkeypatch.setattr(
        "sase.agent.hijack._stop_target._claim_workspace_dir",
        lambda _project, _claim: None,
    )


def _deps(artifacts: Path) -> StopDeps:
    row = SimpleNamespace(
        name=_AGENT,
        artifacts_dir=str(artifacts),
        status="RUNNING",
        pid=_PID,
        is_monitor=False,
        agent_session=None,
        workspace_num=_WS,
    )
    return StopDeps(
        find_agent=lambda name: (
            SimpleNamespace(
                name=_AGENT,
                artifacts_dir=str(artifacts),
                is_done=False,
                outcome=None,
            )
            if name == _AGENT
            else None
        ),
        list_running=lambda: [row],
        process_alive=lambda _meta, _path: True,
    )


def test_finalizing_decision_latches_with_boundary_hint() -> None:
    from sase.agent.hijack.core import agent_hijack_decide
    from sase.agent.hijack.core import agent_hijack_eligibility_wire_schema_version

    facts = {
        "schema_version": agent_hijack_eligibility_wire_schema_version(),
        "is_local": True,
        "occupying_kind": "llm",
        "status": "RUNNING",
        "turn_phase": "finalizing",
        "workspace_num": _WS,
        "has_numbered_claim": True,
        "pid": _PID,
        "process_alive": True,
        "has_hijack_capability": True,
        "successor_attachable": True,
    }
    decision = agent_hijack_decide(facts)
    assert decision["mode"] == "latched"
    assert decision["eligible"] is True
    assert decision["adapter"] is None
    assert decision["boundary"] == "finalizer"
    assert decision["code"] == "finalizing"


def test_staged_decision_latches_and_done_staged_is_not_completed() -> None:
    from sase.agent.hijack.core import agent_hijack_decide
    from sase.agent.hijack.core import agent_hijack_eligibility_wire_schema_version

    version = agent_hijack_eligibility_wire_schema_version()
    base = {
        "schema_version": version,
        "is_local": True,
        "occupying_kind": "llm",
        "status": "RUNNING",
        "turn_phase": "provider_running",
        "workspace_num": _WS,
        "has_numbered_claim": True,
        "pid": _PID,
        "process_alive": True,
        "has_hijack_capability": True,
        "successor_attachable": True,
        "has_staged_handoff": True,
        "staged_kind": "pipe",
    }
    staged = agent_hijack_decide(dict(base))
    assert staged["mode"] == "latched"
    assert staged["boundary"] == "staged_adoption"
    assert staged["code"] == "staged_pending"

    done_staged = agent_hijack_decide({**base, "done_outcome": "succeeded"})
    assert done_staged["mode"] == "latched"

    done = agent_hijack_decide(
        {
            **{
                k: v
                for k, v in base.items()
                if k not in {"has_staged_handoff", "staged_kind"}
            },
            "done_outcome": "succeeded",
        }
    )
    assert done["mode"] == "refused"
    assert done["code"] == "already_completed"


def test_orchestrator_latches_finalizing_with_exit_3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = _artifacts(
        tmp_path, {"lifecycle_phase": "finalizing", "process_identity": "boot:123"}
    )
    monkeypatch.setattr(
        "sase.agent.hijack._latch_request.owner_identity_for",
        lambda _target: "boot:123",
    )
    monkeypatch.setattr(
        "sase.agent.hijack._latch_common.owner_identity_for",
        lambda _target: "boot:123",
    )
    project_file = _project_file(tmp_path)
    _install_target(monkeypatch, artifacts, project_file)
    result = stop_agent_for_hijack(_AGENT, deps=_deps(artifacts))
    assert result.exit_code == 3
    assert result.status == "latched"
    assert result.hijack_id is not None
    assert result.record is not None
    assert result.record["state"] == "latched"
    # Pending requests never stop the owner.
    assert not (artifacts / "done.json").exists()


def test_repeated_latch_requests_coalesce_to_one_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = _artifacts(
        tmp_path, {"lifecycle_phase": "handoff", "process_identity": "boot:123"}
    )
    monkeypatch.setattr(
        "sase.agent.hijack._latch_request.owner_identity_for",
        lambda _target: "boot:123",
    )
    monkeypatch.setattr(
        "sase.agent.hijack._latch_common.owner_identity_for",
        lambda _target: "boot:123",
    )
    project_file = _project_file(tmp_path)
    _install_target(monkeypatch, artifacts, project_file)
    first = stop_agent_for_hijack(_AGENT, deps=_deps(artifacts))
    second = stop_agent_for_hijack(_AGENT, deps=_deps(artifacts))
    assert first.exit_code == 3
    assert second.exit_code == 3
    assert first.hijack_id == second.hijack_id


def test_cli_latched_json_has_member_latched_boundary(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    from sase.agents.cli_hijack import handle_agents_hijack
    from sase.agent.hijack.stop import HijackStopResult

    decision = {
        "mode": "latched",
        "eligible": True,
        "code": "finalizing",
        "message": "finalizing",
        "next_action": "request now",
        "redirect_op": None,
        "adapter": None,
        "boundary": "finalizer",
    }
    expected = HijackStopResult(
        status="latched",
        message="latched",
        exit_code=3,
        hijack_id="h-latch",
        record={"workspace_num": 4, "boundary": "finalizer"},
        reason="finalizing",
        decision=decision,
        occupant_name=_AGENT,
        occupant_reason="holds the claim",
        workspace_num=4,
    )
    monkeypatch.setattr(
        "sase.agents.cli_hijack.stop_agent_for_hijack", lambda *a, **k: expected
    )
    args = argparse.Namespace(
        name=_AGENT, reason=None, json=True, cancel=False, explain=False, now=False
    )
    assert handle_agents_hijack(args) == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["member"] == _AGENT
    assert payload["latched"] is True
    assert payload["boundary"] == "finalizer"
    assert payload["mode"] == "latched"

    args.json = False
    assert handle_agents_hijack(args) == 3


def test_cli_mutually_exclusive_flags_are_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    from sase.agents.cli_hijack import handle_agents_hijack

    args = argparse.Namespace(
        name=_AGENT, reason=None, json=True, cancel=True, explain=True, now=False
    )
    assert handle_agents_hijack(args) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["code"] == "mutually_exclusive"


def test_cli_cancel_success_and_race_reports_state(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    from sase.agents.cli_hijack import handle_agents_hijack

    monkeypatch.setattr(
        "sase.agent.hijack.facts.resolve_hijack_subject",
        lambda name: SimpleNamespace(
            occupant_name=_AGENT,
            occupant_reason="holds",
            target=SimpleNamespace(workspace_num=4),
        ),
    )
    monkeypatch.setattr(
        "sase.agent.hijack._stop_orchestrator_targets.compute_target_key",
        lambda _subject, _target: "key-1",
    )

    def fake_decide(name: str, deps: object = None) -> tuple[object, dict[str, str]]:
        return (
            SimpleNamespace(occupant_name=_AGENT, occupant_reason="holds"),
            {"mode": "refused", "code": "cancelled"},
        )

    monkeypatch.setattr(
        "sase.agent.hijack.facts.resolve_and_decide",
        fake_decide,
    )
    monkeypatch.setattr(
        "sase.agents.cli_hijack.resolve_and_decide",
        fake_decide,
    )
    monkeypatch.setattr(
        "sase.agent.hijack.latch.cancel_latch",
        lambda _key: {
            "verdict": "cancelled",
            "code": "cancelled",
            "message": "cancelled",
            "hijack_id": "h-1",
            "record": {"hijack_id": "h-1", "state": "cancelled"},
        },
    )
    args = argparse.Namespace(
        name=_AGENT, reason=None, json=True, cancel=True, explain=False, now=False
    )
    assert handle_agents_hijack(args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "cancelled"

    monkeypatch.setattr(
        "sase.agent.hijack.latch.cancel_latch",
        lambda _key: {
            "verdict": "applied",
            "code": "applied",
            "message": "already applied",
            "hijack_id": "h-1",
            "record": {"hijack_id": "h-1", "state": "held"},
        },
    )
    assert handle_agents_hijack(args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "held"


def test_cli_explain_no_target_is_read_only_exit_2(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    from sase.agents.cli_hijack import handle_agents_hijack

    subject = SimpleNamespace(
        occupant_name=None, occupant_reason="none", target=None, selected=None
    )
    decision = {"mode": "refused", "code": "not_found"}
    monkeypatch.setattr(
        "sase.agents.cli_hijack.resolve_and_decide", lambda name: (subject, decision)
    )
    monkeypatch.setattr(
        "sase.agents.cli_hijack.stop_agent_for_hijack",
        lambda *a, **k: pytest.fail("explain must not stop"),
    )
    args = argparse.Namespace(
        name="nobody", reason=None, json=True, cancel=False, explain=True, now=False
    )
    assert handle_agents_hijack(args) == 2


def test_monitor_followup_pending_decision_ignores_unknown_extra_keys() -> None:
    from sase.agent.hijack.core import agent_hijack_decide
    from sase.agent.hijack.core import agent_hijack_eligibility_wire_schema_version

    facts = {
        "schema_version": agent_hijack_eligibility_wire_schema_version(),
        "is_local": True,
        "occupying_kind": "monitor",
        "status": "DONE",
        "monitor_state": "completed",
        "workspace_num": _WS,
        "has_numbered_claim": True,
        "pid": None,
        "process_alive": False,
        "has_hijack_capability": False,
        "successor_attachable": True,
        "done_outcome": "succeeded",
        "monitor_followup_pending": True,
        "future_additive_field": "ignored",
    }
    decision = agent_hijack_decide(facts)
    assert decision["mode"] == "latched"
    assert decision["eligible"] is True
    assert decision["adapter"] is None
    assert decision["boundary"] == "monitor"
    assert decision["code"] == "monitor_followup_pending"

    delivered = dict(facts)
    delivered["monitor_followup_pending"] = False
    refused = agent_hijack_decide(delivered)
    assert refused["mode"] == "refused"
    assert refused["code"] == "already_completed"


def test_parser_hijack_flags_are_sorted_and_mutually_exclusive() -> None:
    from sase.main.parser import create_parser

    parser = create_parser()
    args = parser.parse_args(["agent", "hijack", "-c", _AGENT])
    assert args.cancel is True
    args = parser.parse_args(["agent", "hijack", "-n", _AGENT])
    assert args.now is True
    args = parser.parse_args(["agent", "hijack", "-e", _AGENT])
    assert args.explain is True
    import pytest as _pytest

    with _pytest.raises(SystemExit):
        parser.parse_args(["agent", "hijack", "-c", "-e", _AGENT])
    with _pytest.raises(SystemExit):
        parser.parse_args(["agent", "hijack", "-c", "-n", _AGENT])
