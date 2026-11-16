"""Transactional stop hardening tests (phase ``stop_txn``).

Covers target-level dedup, verified intent persistence, pin restore on
pre-signal abort, bounded retry plus ``stop_blocked`` custody, stale-sweep
reconciliation, and sessionless promotion. pidfd signalling is covered by a
fallback test that never touches a live pid.
"""

from __future__ import annotations

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


@pytest.fixture
def hijack_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    return home


def _artifacts(tmp_path: Path, *, capabilities: list[str] | None = None) -> Path:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(exist_ok=True)
    meta: dict[str, Any] = {
        "name": _AGENT,
        "agent_session": "sase-7f",
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
        snapshot_repo=None,
        process_alive=lambda _meta, _path: True,
    )


def test_concurrent_requests_coalesce_onto_one_record(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.hijack import ledger

    artifacts = _artifacts(tmp_path)
    project_file = _project_file(tmp_path)
    _install_target(monkeypatch, artifacts, project_file)
    calls = {"n": 0}

    def fake_terminate(pid: int, **kwargs: Any) -> Any:
        calls["n"] += 1
        return SimpleNamespace(success=True, survivors=(), error=None)

    def fake_write(artifacts_dir: str, marker: dict[str, Any]) -> str:
        path = Path(artifacts_dir) / "done.json"
        path.write_text(json.dumps(marker))
        return str(path)

    monkeypatch.setattr(
        "sase.axe.run_agent_exec_markers.write_done_marker_and_update_index",
        fake_write,
    )
    first = stop_agent_for_hijack(
        _AGENT, deps=_deps(artifacts, terminate=fake_terminate)
    )
    assert first.status == "held"
    assert first.hijack_id is not None
    # A second request for the same target (TUI double-press, lost-response
    # retry) returns the active operation with the same hijack id and never
    # starts a second stop.
    second = stop_agent_for_hijack(
        _AGENT, deps=_deps(artifacts, terminate=fake_terminate)
    )
    assert second.hijack_id == first.hijack_id
    assert second.exit_code == 0
    assert calls["n"] == 1
    active = [p for p in (hijack_home / "agent_hijacks").glob("*.json") if p.is_file()]
    # One held record plus the target index entry.
    records = [p for p in active if p.parent.name == "agent_hijacks"]
    assert len(records) == 1
    stored = json.loads(records[0].read_text(encoding="utf-8"))
    assert stored["target_key"]
    assert stored["scope"] == "llm"


def test_intent_write_failure_aborts_before_signal(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = _artifacts(tmp_path)
    project_file = _project_file(tmp_path)
    _install_target(monkeypatch, artifacts, project_file)
    monkeypatch.setattr(
        "sase.agent._user_kill_intent.write_user_kill_intent",
        lambda *args, **kwargs: None,
    )
    signals: list[int] = []
    monkeypatch.setattr(
        "sase.agent.hijack._stop_orchestrator.terminate_tree",
        lambda target, deps: signals.append(1) or SimpleNamespace(success=True),
    )
    result = stop_agent_for_hijack(_AGENT, deps=_deps(artifacts))
    assert result.reason == "intent_write_failed"
    assert result.exit_code == 1
    assert signals == []
    assert not (artifacts / ".sase_user_kill_pending").exists()


def test_begin_stop_failure_restores_prior_pin(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.running_field import get_claimed_workspaces

    artifacts = _artifacts(tmp_path)
    project_file = _project_file(tmp_path)
    _install_target(monkeypatch, artifacts, project_file)

    import sase.agent.hijack.ledger as ledger_module

    real_cas = ledger_module.cas_advance_record
    seen = {"n": 0}

    def flaky_cas(record: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        if event.get("event") == "begin_stop" and seen["n"] == 0:
            seen["n"] += 1
            raise RuntimeError("lock lost")
        return real_cas(record, event)

    monkeypatch.setattr(ledger_module, "cas_advance_record", flaky_cas)
    result = stop_agent_for_hijack(_AGENT, deps=_deps(artifacts))
    assert result.reason == "record_advance_failed"
    claims = get_claimed_workspaces(project_file)
    assert [claim.pinned for claim in claims] == [False]


def test_stop_blocked_retry_succeeds_on_second_attempt(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = _artifacts(tmp_path)
    project_file = _project_file(tmp_path)
    _install_target(monkeypatch, artifacts, project_file)
    attempts = {"n": 0}

    def flaky_terminate(pid: int, **kwargs: Any) -> Any:
        attempts["n"] += 1
        if attempts["n"] <= 3:
            return SimpleNamespace(
                success=False, survivors=(999,), error="still running"
            )
        return SimpleNamespace(success=True, survivors=(), error=None)

    def fake_write(artifacts_dir: str, marker: dict[str, Any]) -> str:
        path = Path(artifacts_dir) / "done.json"
        path.write_text(json.dumps(marker))
        return str(path)

    monkeypatch.setattr(
        "sase.axe.run_agent_exec_markers.write_done_marker_and_update_index",
        fake_write,
    )
    first = stop_agent_for_hijack(
        _AGENT, deps=_deps(artifacts, terminate=flaky_terminate)
    )
    assert first.status == "stop_blocked"
    assert first.hijack_id is not None
    # `,k` again on a stop_blocked target retries the same operation.
    second = stop_agent_for_hijack(
        _AGENT, deps=_deps(artifacts, terminate=flaky_terminate)
    )
    assert second.hijack_id == first.hijack_id
    assert second.status == "held"
    assert second.exit_code == 0


def test_abandon_stop_blocked_unpins(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.hijack import ledger
    from sase.agent.hijack.custody import abandon_stop_blocked_for_workspace
    from sase.running_field import get_claimed_workspaces

    artifacts = _artifacts(tmp_path)
    project_file = _project_file(tmp_path)
    _install_target(monkeypatch, artifacts, project_file)

    def fake_terminate(pid: int, **kwargs: Any) -> Any:
        return SimpleNamespace(success=False, survivors=(111,), error="busy")

    first = stop_agent_for_hijack(
        _AGENT, deps=_deps(artifacts, terminate=fake_terminate)
    )
    assert first.status == "stop_blocked"
    claims = get_claimed_workspaces(project_file)
    assert [claim.pinned for claim in claims] == [True]
    terminal = abandon_stop_blocked_for_workspace(project_file, _WS)
    assert terminal is not None
    assert terminal["state"] == "stop_failed"
    claims = get_claimed_workspaces(project_file)
    assert [claim.pinned for claim in claims] == [False]
    assert (
        ledger.find_active_record_by_target_key(
            str(first.record.get("target_key") if first.record else "")
        )
        is None
    )


def test_pidfd_signal_falls_back_without_live_pid() -> None:
    from sase.agent import _user_kill_tree as tree

    # A recycled or missing pid never crashes; the caller falls back to kill.
    outcome = tree._pidfd_signal(2**31 - 1, 15)
    assert outcome in (False, None, "denied")


def test_stale_sweep_settles_dead_stop_as_held(
    hijack_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.hijack import ledger
    from sase.ace.scheduler._stale_running_hijack import (
        _reconcile_abandoned_stop_record,
    )

    artifacts = tmp_path / "sweep-artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(json.dumps({"name": _AGENT}))
    project_file = _project_file(tmp_path)
    _install_target(monkeypatch, artifacts, project_file)
    record = ledger.new_requested_record(
        hijack_id="hijack-sweep-dead",
        agent_name=_AGENT,
        artifacts_dir=str(artifacts),
        pid=999999,
        project_file=project_file,
        workspace_num=_WS,
        workspace_dir=str(tmp_path),
        expected_claim_owner_pid=999999,
        session="sase-7f",
        target_key=ledger.target_key_for(project_file, "sase-7f"),
        scope="llm",
        at="2020-01-01T00:00:00+00:00",
    )
    record["updated_at"] = "2020-01-01T00:00:00+00:00"
    ledger.create_record(record)
    ledger.cas_advance_record(record, {"event": "begin_stop"})
    ledger.merge_record_fields(
        "hijack-sweep-dead", {"updated_at": "2020-01-01T00:00:00+00:00"}
    )
    from sase.running_field import get_claimed_workspaces

    claims = get_claimed_workspaces(project_file)
    assert claims
    _reconcile_abandoned_stop_record(
        project_file, claims[0], ledger.load_record("hijack-sweep-dead") or record
    )
    settled = ledger.load_record("hijack-sweep-dead")
    assert settled is not None
    assert settled["state"] == "held"
    assert (artifacts / "done.json").exists()


def test_sessionless_predecessor_is_promotable() -> None:
    from sase.agent.hijack.facts import _promotion_preconditions_hold
    from types import SimpleNamespace as _NS

    member = _NS(
        meta={"name": "solo-agent"},
        artifacts_dir="/tmp/solo",
    )
    assert _promotion_preconditions_hold(member) is True
    assert _promotion_preconditions_hold(None) is False
    assert _promotion_preconditions_hold(_NS(meta={}, artifacts_dir="/tmp/x")) is False
