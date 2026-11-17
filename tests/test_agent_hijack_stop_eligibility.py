"""Eligibility, refusal, and redirect tests for Agent Hijack stop."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack._stop_models import StopDeps
from sase.agent.hijack.stop import stop_agent_for_hijack
from tests._agent_hijack_stop_support import (
    AGENT,
    PID,
    install_target,
    make_artifacts,
    make_project_file,
    shared_hijack_home,
    stop_deps,
)
from tests._running_field_helpers import create_project_file_with_running


def _hijack_ids(home: Path) -> list[str]:
    root = home / "agent_hijacks"
    if not root.exists():
        return []
    return sorted(
        path.name
        for path in root.glob("*.json")
        if path.name != "settled" and not path.name.endswith(".lock")
    )


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


@pytest.mark.parametrize(
    ("status", "phase"),
    [("WAITING", "waiting"), ("QUEUED", "waiting"), ("STARTING", "booting")],
)
@pytest.mark.parametrize("alive", [True, False])
def test_pre_provider_claim_is_held_with_or_without_runner(
    hijack_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    phase: str,
    alive: bool,
) -> None:
    from sase.running_field import get_claimed_workspaces

    artifacts = make_artifacts(tmp_path, capabilities=["hijack"] if alive else [])
    meta_path = artifacts / "agent_meta.json"
    meta = json.loads(meta_path.read_text())
    meta["lifecycle_phase"] = phase
    if not alive:
        meta.pop("pid")
    meta_path.write_text(json.dumps(meta))
    if status != "STARTING":
        waiting = {"waiting_for": ["dependency"]}
        if status == "QUEUED":
            waiting["slot_requested_at"] = 123.0
        (artifacts / "waiting.json").write_text(json.dumps(waiting))
    project_file = make_project_file(tmp_path)
    install_target(monkeypatch, artifacts, project_file)
    signalled: list[int] = []

    def terminate(pid: int, **kwargs: Any) -> Any:
        signalled.append(pid)
        if status != "STARTING":
            assert json.loads((artifacts / "waiting.json").read_text())[
                "cancelled_by_hijack"
            ]
        return SimpleNamespace(success=True, survivors=(), error=None)

    deps = stop_deps(artifacts, terminate=terminate)
    assert deps.list_running is not None
    rows = deps.list_running()
    rows[0].status = status
    deps.list_running = lambda: rows if alive else []
    deps.process_alive = lambda _meta, _path: alive

    result = stop_agent_for_hijack(AGENT, deps=deps)

    assert result.status == "held", result
    assert result.record is not None
    assert result.record["scope"] == ("llm" if alive else "processless")
    assert signalled == ([PID] if alive else [])
    assert get_claimed_workspaces(project_file)[0].pinned
    done = json.loads((artifacts / "done.json").read_text())
    assert done["outcome"] == "hijacked"
    assert done["recovery"]["hijack_id"] == result.hijack_id


def test_claimless_wait_redirects_without_stopping(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = make_artifacts(tmp_path)
    project_file = create_project_file_with_running(tmp_path, running_claims=[])
    install_target(monkeypatch, artifacts, project_file)

    def terminate(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("claimless redirect must not signal the runner")

    deps = stop_deps(artifacts, terminate=terminate)
    assert deps.list_running is not None
    rows = deps.list_running()
    rows[0].status = "WAITING"
    rows[0].workspace_num = 0
    deps.list_running = lambda: rows

    result = stop_agent_for_hijack(AGENT, deps=deps)

    assert result.decision is not None
    assert result.decision["mode"] == "redirect"
    assert result.decision["code"] == "nothing_to_keep"
    assert result.decision["redirect_op"] == "kill_and_edit"
    assert _hijack_ids(hijack_home) == []
    assert not (artifacts / ".sase_user_kill_pending").exists()


def test_completed_agent_is_refused(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = make_artifacts(tmp_path)
    (artifacts / "done.json").write_text(
        json.dumps({"outcome": "succeeded", "recovery": None})
    )
    project_file = make_project_file(tmp_path)
    install_target(monkeypatch, artifacts, project_file)
    deps = stop_deps(artifacts)
    deps.find_agent = lambda name: SimpleNamespace(
        name=AGENT,
        artifacts_dir=str(artifacts),
        is_done=True,
        outcome="succeeded",
    )
    result = stop_agent_for_hijack(AGENT, deps=deps)
    assert result.status == "refused"
    assert result.exit_code == 2
    assert result.reason == "already_completed"
    assert _hijack_ids(hijack_home) == []


def test_old_runner_without_capability_is_refused(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = make_artifacts(tmp_path, capabilities=[])
    project_file = make_project_file(tmp_path)
    install_target(monkeypatch, artifacts, project_file)
    result = stop_agent_for_hijack(AGENT, deps=stop_deps(artifacts))
    assert result.status == "refused"
    assert result.exit_code == 2
    assert result.reason == "missing_capability"
    assert "launched before hijack support" in result.message
    assert _hijack_ids(hijack_home) == []
    assert not (artifacts / ".sase_user_kill_pending").exists()


def test_re_resolution_refuses_changed_process_identity_before_pin(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.hijack.facts import resolve_and_decide as resolve_original

    artifacts = make_artifacts(tmp_path)
    project_file = make_project_file(tmp_path)
    install_target(monkeypatch, artifacts, project_file)
    deps = stop_deps(artifacts)
    original_subject, original_decision = resolve_original(AGENT, deps=deps)
    assert original_subject.target is not None
    assert original_decision["mode"] == "immediate"

    changed_subject = copy.copy(original_subject)
    changed_target = copy.copy(original_subject.target)
    changed_target.pid = PID + 1
    changed_subject.target = changed_target
    subjects = iter(
        (
            (original_subject, original_decision),
            (changed_subject, original_decision),
        )
    )
    monkeypatch.setattr(
        "sase.agent.hijack.facts.resolve_and_decide",
        lambda _name, *, deps=None: next(subjects),
    )
    pin_calls: list[int] = []
    monkeypatch.setattr(
        "sase.agent.hijack._stop_orchestrator_transaction.pin_claim",
        lambda target: pin_calls.append(target.pid or 0) or True,
    )

    result = stop_agent_for_hijack(AGENT, deps=deps)

    assert result.status == "refused"
    assert result.reason == "occupant_changed"
    assert pin_calls == []
    assert not (artifacts / ".sase_user_kill_pending").exists()
    assert _hijack_ids(hijack_home) == []


def test_re_resolution_refuses_changed_decision_before_pin(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.hijack.facts import resolve_and_decide as resolve_original

    artifacts = make_artifacts(tmp_path)
    project_file = make_project_file(tmp_path)
    install_target(monkeypatch, artifacts, project_file)
    deps = stop_deps(artifacts)
    subject, decision = resolve_original(AGENT, deps=deps)
    changed_decision = {**decision, "next_action": "decision changed during recheck"}
    subjects = iter(((subject, decision), (subject, changed_decision)))
    monkeypatch.setattr(
        "sase.agent.hijack.facts.resolve_and_decide",
        lambda _name, *, deps=None: next(subjects),
    )
    pin_calls: list[int] = []
    monkeypatch.setattr(
        "sase.agent.hijack._stop_orchestrator_transaction.pin_claim",
        lambda target: pin_calls.append(target.pid or 0) or True,
    )

    result = stop_agent_for_hijack(AGENT, deps=deps)

    assert result.status == "refused"
    assert result.reason == "decision_changed"
    assert pin_calls == []
    assert not (artifacts / ".sase_user_kill_pending").exists()
    assert _hijack_ids(hijack_home) == []
