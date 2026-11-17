"""Held, finished-first, and stop-blocked outcomes for Agent Hijack stop."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack.stop import stop_agent_for_hijack
from tests._agent_hijack_stop_support import (
    AGENT,
    PID,
    WS,
    install_target,
    make_artifacts,
    make_project_file,
    shared_hijack_home,
    stop_deps,
)


def test_happy_path_reaches_held(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.running_field import get_claimed_workspaces

    artifacts = make_artifacts(tmp_path)
    project_file = make_project_file(tmp_path)
    install_target(monkeypatch, artifacts, project_file)
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
        AGENT, deps=stop_deps(artifacts, terminate=fake_terminate)
    )
    assert result.status == "held"
    assert result.exit_code == 0
    assert result.hijack_id is not None
    assert result.record is not None
    assert result.record["state"] == "held"
    assert result.record["revision"] == 2
    assert result.record["prior_pin_state"] is False
    assert calls["pid"] == PID
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
    assert f"ws #{WS} held" in result.message


def test_lost_race_keeps_the_real_outcome(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.running_field import get_claimed_workspaces

    artifacts = make_artifacts(tmp_path)
    project_file = make_project_file(tmp_path)
    install_target(monkeypatch, artifacts, project_file)
    import sase.agent.hijack._stop_orchestrator_transaction as transaction_module
    import sase.agent.hijack._stop_target as target_module

    calls = {"n": 0}

    def flaky(artifacts_dir: str) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            return None, None
        return "succeeded", {}

    monkeypatch.setattr(target_module, "read_done_marker", flaky)
    monkeypatch.setattr(transaction_module, "read_done_marker", flaky)
    result = stop_agent_for_hijack(AGENT, deps=stop_deps(artifacts))
    assert result.status == "finished_first"
    assert result.exit_code == 2
    assert result.record is not None
    assert result.record["state"] == "finished_first"
    assert not (artifacts / ".sase_user_kill_pending").exists()
    claims = get_claimed_workspaces(project_file)
    assert [claim.pinned for claim in claims] == [False]
    assert "finished first" in result.message


def test_survivors_retain_custody_in_stop_blocked(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.running_field import get_claimed_workspaces

    artifacts = make_artifacts(tmp_path)
    project_file = make_project_file(tmp_path)
    install_target(monkeypatch, artifacts, project_file)
    calls = {"n": 0}

    def fake_terminate(pid: int, **kwargs: Any) -> Any:
        calls["n"] += 1
        return SimpleNamespace(
            success=False, survivors=(111, 222), error="still running"
        )

    result = stop_agent_for_hijack(
        AGENT, deps=stop_deps(artifacts, terminate=fake_terminate)
    )
    assert result.status == "stop_blocked"
    assert result.exit_code == 1
    assert result.record is not None
    assert result.record["state"] == "stop_blocked"
    assert result.record["survivor_pids"] == [111, 222]
    # Bounded retry: initial attempt plus two retries before custody.
    assert calls["n"] == 3
    # Custody stays: intent kept, pin kept, no done marker.
    assert (artifacts / ".sase_user_kill_pending").exists()
    assert not (artifacts / "done.json").exists()
    claims = get_claimed_workspaces(project_file)
    assert [claim.pinned for claim in claims] == [True]
    assert "workspace kept" in result.message
    assert "`,k` retries" in result.message


def test_snapshot_failure_still_reaches_held(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = make_artifacts(tmp_path)
    project_file = make_project_file(tmp_path)
    install_target(monkeypatch, artifacts, project_file)

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("snapshot store offline")

    result = stop_agent_for_hijack(AGENT, deps=stop_deps(artifacts, snapshot_repo=boom))
    assert result.status == "held"
    assert result.exit_code == 0
    assert result.record is not None
    assert result.record["state"] == "held"


def test_fallback_writes_done_json_and_reasserts_pin(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = make_artifacts(tmp_path)
    project_file = make_project_file(tmp_path)
    install_target(monkeypatch, artifacts, project_file)
    pins = {"n": 0}
    import sase.agent.hijack._stop_claim as claim_module
    import sase.agent.hijack._stop_orchestrator_transaction as transaction_module

    original_claim_pin = claim_module.pin_claim
    original_orchestrator_pin = transaction_module.pin_claim

    def counting_claim_pin(target: Any) -> bool:
        pins["n"] += 1
        return original_claim_pin(target)

    def counting_orchestrator_pin(target: Any) -> bool:
        pins["n"] += 1
        return original_orchestrator_pin(target)

    monkeypatch.setattr(claim_module, "pin_claim", counting_claim_pin)
    monkeypatch.setattr(transaction_module, "pin_claim", counting_orchestrator_pin)

    def fake_write(artifacts_dir: str, marker: dict[str, Any]) -> str:
        path = Path(artifacts_dir) / "done.json"
        path.write_text(json.dumps(marker))
        return str(path)

    monkeypatch.setattr(
        "sase.axe.run_agent_exec_markers.write_done_marker_and_update_index",
        fake_write,
    )
    result = stop_agent_for_hijack(AGENT, deps=stop_deps(artifacts))
    assert result.status == "held"
    done = json.loads((artifacts / "done.json").read_text(encoding="utf-8"))
    assert done["outcome"] == "hijacked"
    assert pins["n"] == 2
