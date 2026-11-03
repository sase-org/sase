"""Stop-protocol tests for Agent Hijack (phase ``stop``).

The orchestrator and both ingress paths (``sase agent hijack`` and
``sase ops agent persist-hijack``) run against the real Rust eligibility
function and the real file ledger under an isolated ``SASE_HOME``; only the
process tree, snapshots, and project layout are faked.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack._stop_models import StopDeps
from sase.agent.hijack.stop import (
    HijackStopResult,
    stop_agent_for_hijack,
)
from sase.running_field import WorkspaceClaim
from tests._running_field_helpers import create_project_file_with_running

_AGENT = "sase-7f.2"
_TS = "20260712120000"
_PID = 424242
_WS = 4


@pytest.fixture
def hijack_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    monkeypatch.setattr(
        "sase.agent.hijack._stop_orchestrator._hijack_stop_enabled", lambda: True
    )
    return home


def _artifacts(tmp_path: Path, *, capabilities: list[str] | None = None) -> Path:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    meta: dict[str, Any] = {
        "name": _AGENT,
        "pid": _PID,
        "runner_capabilities": capabilities if capabilities is not None else ["hijack"],
        "agent_model": "claude-opus",
        "agent_llm_provider": "claude",
        "agent_effort": "high",
        "booted_at": 1000.0,
    }
    (artifacts / "agent_meta.json").write_text(json.dumps(meta))
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


def _deps(
    artifacts: Path,
    *,
    terminate: Any | None = None,
    snapshot_repo: Any | None = None,
) -> StopDeps:
    row = SimpleNamespace(
        name=_AGENT,
        artifacts_dir=str(artifacts),
        status="RUNNING",
        pid=_PID,
        is_monitor=False,
        agent_session=None,
        workspace_num=_WS,
    )
    if terminate is None:
        terminate = SimpleNamespace(success=True, survivors=(), error=None)

        def _ok(*args: Any, **kwargs: Any) -> Any:
            return terminate

        terminate_fn = _ok
    else:
        terminate_fn = terminate
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
        terminate=terminate_fn,
        snapshot_repo=snapshot_repo,
    )


def _hijack_ids(home: Path) -> list[str]:
    root = home / "agent_hijacks"
    if not root.exists():
        return []
    return sorted(
        path.name
        for path in root.glob("*.json")
        if path.name != "settled" and not path.name.endswith(".lock")
    )


def test_flag_disabled_refuses_without_changing_anything(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sase.agent.hijack._stop_orchestrator._hijack_stop_enabled", lambda: False
    )
    result = stop_agent_for_hijack(_AGENT, deps=_deps(tmp_path / "artifacts"))
    assert result.status == "refused"
    assert result.exit_code == 2
    assert result.reason == "flag_disabled"
    assert result.hijack_id is None
    assert _hijack_ids(hijack_home) == []


def test_unknown_agent_is_refused(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = stop_agent_for_hijack(
        "nobody",
        deps=StopDeps(
            find_agent=lambda name: None,
            list_running=lambda: [],
        ),
    )
    assert result.status == "refused"
    assert result.exit_code == 2
    assert result.reason == "not_found"
    assert _hijack_ids(hijack_home) == []
    assert list(tmp_path.glob("**/.sase_user_kill_pending")) == []


def test_completed_agent_is_refused(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = _artifacts(tmp_path)
    (artifacts / "done.json").write_text(
        json.dumps({"outcome": "succeeded", "recovery": None})
    )
    project_file = _project_file(tmp_path)
    _install_target(monkeypatch, artifacts, project_file)
    deps = _deps(artifacts)
    deps.find_agent = lambda name: SimpleNamespace(
        name=_AGENT,
        artifacts_dir=str(artifacts),
        is_done=True,
        outcome="succeeded",
    )
    result = stop_agent_for_hijack(_AGENT, deps=deps)
    assert result.status == "refused"
    assert result.exit_code == 2
    assert result.reason == "already_completed"
    assert _hijack_ids(hijack_home) == []


def test_old_runner_without_capability_is_refused(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = _artifacts(tmp_path, capabilities=[])
    project_file = _project_file(tmp_path)
    _install_target(monkeypatch, artifacts, project_file)
    result = stop_agent_for_hijack(_AGENT, deps=_deps(artifacts))
    assert result.status == "refused"
    assert result.exit_code == 2
    assert result.reason == "missing_capability"
    assert _hijack_ids(hijack_home) == []
    assert not (artifacts / ".sase_user_kill_pending").exists()


def test_happy_path_reaches_held(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.running_field import get_claimed_workspaces

    artifacts = _artifacts(tmp_path)
    project_file = _project_file(tmp_path)
    _install_target(monkeypatch, artifacts, project_file)
    calls: dict[str, Any] = {}

    def fake_terminate(pid: int, **kwargs: Any) -> Any:
        calls["pid"] = pid
        calls["kwargs"] = kwargs
        return SimpleNamespace(success=True, survivors=(), error=None)

    def fake_write(artifacts_dir: str, marker: dict[str, Any]) -> str:
        calls["marker"] = marker
        path = Path(artifacts_dir) / "done.json"
        path.write_text(json.dumps(marker))
        return str(path)

    monkeypatch.setattr(
        "sase.axe.run_agent_exec_markers.write_done_marker_and_update_index",
        fake_write,
    )
    result = stop_agent_for_hijack(
        _AGENT, deps=_deps(artifacts, terminate=fake_terminate)
    )
    assert result.status == "held"
    assert result.exit_code == 0
    assert result.hijack_id is not None
    assert result.record is not None
    assert result.record["state"] == "held"
    assert result.record["revision"] == 2
    assert result.record["prior_pin_state"] is False
    assert calls["pid"] == _PID
    intent = json.loads(
        (artifacts / ".sase_user_kill_pending").read_text(encoding="utf-8")
    )
    assert intent["mode"] == "hijack"
    assert intent["hijack_id"] == result.hijack_id
    done = json.loads((artifacts / "done.json").read_text(encoding="utf-8"))
    assert done["outcome"] == "hijacked"
    assert done["recovery"]["hijack_id"] == result.hijack_id
    claims = get_claimed_workspaces(project_file)
    assert [claim.pinned for claim in claims] == [True]
    assert f"ws #{_WS} held" in result.message


def test_lost_race_keeps_the_real_outcome(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.running_field import get_claimed_workspaces

    artifacts = _artifacts(tmp_path)
    project_file = _project_file(tmp_path)
    _install_target(monkeypatch, artifacts, project_file)
    import sase.agent.hijack._stop_orchestrator as orchestrator_module
    import sase.agent.hijack._stop_target as target_module

    calls = {"n": 0}

    def flaky(artifacts_dir: str) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            return None, None
        return "succeeded", {}

    monkeypatch.setattr(target_module, "read_done_marker", flaky)
    monkeypatch.setattr(orchestrator_module, "read_done_marker", flaky)
    result = stop_agent_for_hijack(_AGENT, deps=_deps(artifacts))
    assert result.status == "finished_first"
    assert result.exit_code == 2
    assert result.record is not None
    assert result.record["state"] == "finished_first"
    assert not (artifacts / ".sase_user_kill_pending").exists()
    claims = get_claimed_workspaces(project_file)
    assert [claim.pinned for claim in claims] == [False]
    assert "finished first" in result.message


def test_survivors_leave_the_agent_running(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.running_field import get_claimed_workspaces

    artifacts = _artifacts(tmp_path)
    project_file = _project_file(tmp_path)
    _install_target(monkeypatch, artifacts, project_file)

    def fake_terminate(pid: int, **kwargs: Any) -> Any:
        return SimpleNamespace(
            success=False, survivors=(111, 222), error="still running"
        )

    result = stop_agent_for_hijack(
        _AGENT, deps=_deps(artifacts, terminate=fake_terminate)
    )
    assert result.status == "stop_failed"
    assert result.exit_code == 1
    assert result.record is not None
    assert result.record["state"] == "stop_failed"
    assert not (artifacts / ".sase_user_kill_pending").exists()
    assert not (artifacts / "done.json").exists()
    claims = get_claimed_workspaces(project_file)
    assert [claim.pinned for claim in claims] == [False]


def test_snapshot_failure_still_reaches_held(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = _artifacts(tmp_path)
    project_file = _project_file(tmp_path)
    _install_target(monkeypatch, artifacts, project_file)

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("snapshot store offline")

    result = stop_agent_for_hijack(_AGENT, deps=_deps(artifacts, snapshot_repo=boom))
    assert result.status == "held"
    assert result.exit_code == 0
    assert result.record is not None
    assert result.record["state"] == "held"


def test_fallback_writes_done_json_and_reasserts_pin(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = _artifacts(tmp_path)
    project_file = _project_file(tmp_path)
    _install_target(monkeypatch, artifacts, project_file)
    pins = {"n": 0}
    import sase.agent.hijack._stop_claim as claim_module
    import sase.agent.hijack._stop_orchestrator as orchestrator_module

    original_claim_pin = claim_module.pin_claim
    original_orchestrator_pin = orchestrator_module.pin_claim

    def counting_claim_pin(target: Any) -> bool:
        pins["n"] += 1
        return original_claim_pin(target)

    def counting_orchestrator_pin(target: Any) -> bool:
        pins["n"] += 1
        return original_orchestrator_pin(target)

    monkeypatch.setattr(claim_module, "pin_claim", counting_claim_pin)
    monkeypatch.setattr(orchestrator_module, "pin_claim", counting_orchestrator_pin)

    def fake_write(artifacts_dir: str, marker: dict[str, Any]) -> str:
        path = Path(artifacts_dir) / "done.json"
        path.write_text(json.dumps(marker))
        return str(path)

    monkeypatch.setattr(
        "sase.axe.run_agent_exec_markers.write_done_marker_and_update_index",
        fake_write,
    )
    result = stop_agent_for_hijack(_AGENT, deps=_deps(artifacts))
    assert result.status == "held"
    done = json.loads((artifacts / "done.json").read_text(encoding="utf-8"))
    assert done["outcome"] == "hijacked"
    assert pins["n"] == 2


def test_cli_json_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    from sase.agents.cli_hijack import handle_agents_hijack

    expected = HijackStopResult(
        status="held",
        message="hijacked",
        exit_code=0,
        hijack_id="h-1",
        record={"workspace_num": 4},
    )
    monkeypatch.setattr(
        "sase.agents.cli_hijack.stop_agent_for_hijack", lambda *a, **k: expected
    )
    args = argparse.Namespace(name=_AGENT, reason=None, json=True)
    assert handle_agents_hijack(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["hijack_id"] == "h-1"
    assert payload["workspace_num"] == 4


def test_persist_hijack_uses_the_request_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main.parser import create_parser
    from sase.ops import (
        DurableOperationRequest,
        read_operation_result,
        write_operation_request,
    )
    from sase.ops.commands.agent import handle_agent_operation

    request_path = tmp_path / "req.json"
    result_path = tmp_path / "res.json"
    write_operation_request(
        request_path,
        DurableOperationRequest(
            operation="agent.persist-hijack",
            payload={"name": _AGENT, "reason": "stalled"},
        ),
    )
    captured: dict[str, Any] = {}

    def fake_stop(name: str, **kwargs: Any) -> HijackStopResult:
        captured["name"] = name
        captured["reason"] = kwargs.get("reason")
        return HijackStopResult(
            status="held",
            message="hijacked",
            exit_code=0,
            hijack_id="h-9",
            record={"workspace_num": 4, "artifacts_dir": "/tmp/a"},
        )

    monkeypatch.setattr(
        "sase.ops.commands._agent_persist_hijack.stop_agent_for_hijack",
        fake_stop,
    )
    args = create_parser().parse_args(
        ["agent", "persist-hijack", "-Q", str(request_path), "-R", str(result_path)]
    )
    monkeypatch.setenv("SASE_PROC_ID", "proc-hijack")
    assert handle_agent_operation(args) == 0
    assert captured == {"name": _AGENT, "reason": "stalled"}
    loaded = read_operation_result(
        result_path,
        expected_operation="agent.persist-hijack",
        expected_proc_id="proc-hijack",
    )
    assert loaded.success is True
