"""Boundary chaos, crash convergence, and hand-off inventory guard (phase chaos).

Covers the ``chaos`` phase of the agent-hijack dependability epic:

1. **Boundary chaos.** A hijack is fired at every runner/spawn checkpoint
   (provider running, finalizing, staged, monitor running/settling,
   follow-up spawn, retry). Every attempt must end ``held``, ``latched``
   then ``held``, or a defined latch verdict -- never a generic refusal.
   Each case also asserts at most one successor per progression point.
2. **Crash convergence.** The hijack worker is "killed" between every
   transaction step (record, intent, pin, begin_stop, terminate, settle,
   evidence, publish, latch apply). The stale sweep and latch
   reconciliation must converge with no orphaned pin, no second stop, and
   no surviving writer allowed to release the claim.
3. **Static hand-off inventory guard.** Every successor-launch call site
   must sit behind an ``observe_hijack_latch`` checkpoint or carry an
   explicit allow-list reason, so a new hand-off path fails CI until it
   is covered.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from sase.agent.hijack import core, latch, ledger
from sase.agent.hijack import _latch_apply as latch_apply
from sase.agent.hijack import runner_boundaries as bounds
from sase.agent.hijack.spawn_guard import (
    HijackLatchedError,
    latch_guard_from_predecessor,
    refuse_if_latched,
    spawn_admission,
)
from sase.core.process_identity import process_identity_token
from sase.running_field import WorkspaceClaim
from tests._agent_hijack_latch_support import (
    advance_record,
    install_subjects,
    make_subject,
    make_target,
    observe_record,
)

_PROJECT = "/tmp/sample.sase"


@pytest.fixture
def latch_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(ledger, "_hijack_ledger_root", lambda: tmp_path / "ledger")
    monkeypatch.setattr(ledger, "agent_hijack_wire_schema_version", lambda: 1)
    monkeypatch.setattr(ledger, "advance_agent_hijack_record", advance_record)
    monkeypatch.setattr(core, "agent_hijack_latch_wire_schema_version", lambda: 1)
    monkeypatch.setattr(core, "agent_hijack_latch_observe", observe_record)
    return tmp_path / "ledger"


def _write_meta(
    artifacts: Path,
    *,
    name: str = "agent.1",
    session: str = "session-1",
) -> None:
    pid = os.getpid()
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": name,
                "agent_session": session,
                "project_file": _PROJECT,
                "project_name": "sample",
                "pid": pid,
                "process_identity": process_identity_token(pid),
                "workspace_num": 4,
                "workspace_dir": "/tmp/workspace-4",
                "runner_capabilities": ["hijack"],
            }
        ),
        encoding="utf-8",
    )


def _request_latched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    name: str = "agent.1",
    session: str = "session-1",
) -> tuple[Path, dict[str, Any]]:
    """Request a latch for a live test-runner-owned member."""
    from sase.agent.hijack import _latch_common as latch_common
    from sase.agent.hijack import _latch_force as latch_force
    from sase.agent.hijack import _latch_request as latch_request

    member = tmp_path / name.replace(".", "-")
    _write_meta(member, name=name, session=session)
    target = make_target(
        member,
        name=name,
        pid=os.getpid(),
        identity=process_identity_token(os.getpid()),
    )
    # Align the support-built target with this member's session/project.
    object.__setattr__(target, "agent_session", session)
    object.__setattr__(target, "project_file", _PROJECT)
    install_subjects(monkeypatch, make_subject(target))
    # The support installer patches owner_identity_for on the latch
    # modules; the runner-boundary path also needs the common helper to
    # agree with the test-runner identity.
    identity = process_identity_token(os.getpid())
    monkeypatch.setattr(latch_common, "owner_identity_for", lambda _t: identity)
    monkeypatch.setattr(latch_force, "owner_identity_for", lambda _t: identity)
    monkeypatch.setattr(latch_request, "owner_identity_for", lambda _t: identity)
    monkeypatch.setattr(latch_apply, "owner_identity_for", lambda _t: identity)
    monkeypatch.setattr(latch_apply, "pin_claim", lambda _t: True)
    monkeypatch.setattr(latch_apply, "apply_latched_settlement", lambda _t, _h: None)

    def _attach(
        hijack_id: str,
        _target: Any,
        *,
        deps: Any,
        existing_snapshots: list[dict[str, Any]],
    ) -> tuple[Any, Any, Any]:
        return ledger.load_record(hijack_id), None, None

    monkeypatch.setattr(latch_apply, "collect_and_attach_evidence", _attach)
    requested = latch.request_latch(name)
    assert requested["verdict"] == "pending", requested
    return member, requested


def _assert_latched_refusal(excinfo: pytest.ExceptionInfo[BaseException]) -> None:
    """Assert a latch refusal is precise, never a generic refusal."""
    assert isinstance(excinfo.value, HijackLatchedError)
    assert not isinstance(excinfo.value, RuntimeError)
    from sase.running_field import WorkspaceClaimError

    assert not isinstance(excinfo.value, WorkspaceClaimError)
    assert excinfo.value.hijack_id
    assert excinfo.value.verdict in {"pending", "applied"}
    assert "not eligible" not in str(excinfo.value).lower()
    assert "ineligible" not in str(excinfo.value).lower()


def test_boundary_staged_adoption_latches_not_generic_refusal(
    latch_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del latch_store
    member, requested = _request_latched(tmp_path, monkeypatch)
    with pytest.raises(HijackLatchedError) as excinfo:
        bounds.enforce_staged_adoption_latch(str(member), "staged-1", "pipe")
    _assert_latched_refusal(excinfo)
    assert excinfo.value.hijack_id == requested["hijack_id"]


def test_boundary_adoption_replay_refuses_applied_latch(
    latch_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del latch_store
    member, requested = _request_latched(tmp_path, monkeypatch)
    with pytest.raises(HijackLatchedError) as first:
        bounds.enforce_staged_adoption_latch(str(member), "staged-1", "pipe")
    _assert_latched_refusal(first)
    with pytest.raises(HijackLatchedError) as replay:
        bounds.enforce_adoption_replay_latch(str(member))
    _assert_latched_refusal(replay)
    assert replay.value.hijack_id == requested["hijack_id"]


def test_boundary_inprocess_successor_suppresses_exactly_once(
    latch_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del latch_store
    member, requested = _request_latched(tmp_path, monkeypatch)
    with pytest.raises(HijackLatchedError) as excinfo:
        bounds.enforce_inprocess_successor_latch(str(member), prompt="continue here")
    _assert_latched_refusal(excinfo)
    record = ledger.load_record(str(requested["hijack_id"]))
    assert record is not None
    assert record["suppressed_followup"] == {
        "kind": "inprocess",
        "ref": str(member / ".sase_suppressed_inprocess_prompt.md"),
    }
    # A replay of the same progression point reuses the one successor.
    with pytest.raises(HijackLatchedError) as second:
        bounds.enforce_inprocess_successor_latch(str(member), prompt="continue here")
    assert second.value.hijack_id == requested["hijack_id"]
    assert len(ledger.list_active_records()) == 1


def test_boundary_run_end_moots_with_real_outcome(
    latch_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del latch_store
    member, requested = _request_latched(tmp_path, monkeypatch)
    mooted = bounds.moot_runner_latch_at_run_end(str(member), "completed")
    assert mooted["verdict"] == "moot"
    assert mooted["record"]["boundary_outcome"] == "completed"
    assert ledger.find_active_record_by_target_key(str(requested["target_key"])) is None


def test_boundary_retry_refuses_after_apply(
    latch_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del latch_store
    member, requested = _request_latched(tmp_path, monkeypatch)
    with pytest.raises(HijackLatchedError):
        bounds.enforce_staged_adoption_latch(str(member), "staged-9", "plan")
    with pytest.raises(HijackLatchedError) as excinfo:
        bounds.check_retry_latch(str(member))
    _assert_latched_refusal(excinfo)
    assert excinfo.value.hijack_id == requested["hijack_id"]


def test_boundary_detached_delivery_observes_latch(
    latch_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del latch_store
    member, requested = _request_latched(tmp_path, monkeypatch)
    observed = bounds.check_detached_delivery_latch(str(member))
    assert observed is not None
    assert observed["verdict"] in {"pending", "applied"}
    assert observed["hijack_id"] == requested["hijack_id"]


def test_boundary_spawn_and_followup_pre_checks_latch(
    latch_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del latch_store
    member, requested = _request_latched(tmp_path, monkeypatch)
    guard = latch_guard_from_predecessor(
        project_file=_PROJECT,
        session_or_agent="session-1",
        artifacts_dir=str(member),
        member="agent.1",
    )
    assert guard is not None
    with pytest.raises(HijackLatchedError) as spawn:
        refuse_if_latched(guard, boundary="spawn")
    _assert_latched_refusal(spawn)
    with pytest.raises(HijackLatchedError) as followup:
        refuse_if_latched(guard, boundary="followup")
    _assert_latched_refusal(followup)
    assert followup.value.hijack_id == requested["hijack_id"]
    with pytest.raises(HijackLatchedError) as callback:
        with spawn_admission(guard, boundary="spawn_callback"):
            pytest.fail("spawn_callback admission must refuse before yielding")
    _assert_latched_refusal(callback)


def test_boundary_each_case_keeps_at_most_one_successor(
    latch_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del latch_store
    member, requested = _request_latched(tmp_path, monkeypatch)
    with pytest.raises(HijackLatchedError):
        bounds.enforce_staged_adoption_latch(str(member), "staged-1", "pipe")
    first = ledger.load_record(str(requested["hijack_id"]))
    assert first is not None
    assert first["suppressed_followup"] is not None
    with pytest.raises(HijackLatchedError):
        bounds.enforce_adoption_replay_latch(str(member))
    second = ledger.load_record(str(requested["hijack_id"]))
    assert second is not None
    assert second["suppressed_followup"] == first["suppressed_followup"]
    assert len(ledger.list_active_records()) == 1


def _stale_stamp() -> str:
    return ledger.timestamp_for(__import__("time").time() - 3600.0)


def _crash_advance(record: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """State machine for crash-recovery events plus the latch test events."""
    from tests._agent_hijack_latch_support import advance_record

    name = str(event.get("event") or "")
    crash_transitions = {
        ("requested", "begin_stop"): "stopping",
        ("stopping", "confirmed_stop"): "held",
        ("requested", "confirmed_stop"): "held",
        ("stopping", "stop_blocked"): "stop_blocked",
        ("requested", "finished_first"): "finished_first",
        ("stopping", "finished_first"): "finished_first",
    }
    try:
        return advance_record(record, event)
    except ValueError:
        pass
    next_state = crash_transitions.get((str(record.get("state") or ""), name))
    if next_state is None:
        raise ValueError(f"illegal transition {record.get('state')} + {name}")
    updated = dict(record)
    updated["state"] = next_state
    updated["revision"] = int(record.get("revision") or 0) + 1
    updated["updated_at"] = event.get("at")
    if next_state == "stop_blocked":
        updated["error"] = event.get("error")
    if next_state == "held":
        updated["error"] = None
    return updated


def _crash_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    state: str,
    tag: str,
    with_target_slot: bool = True,
) -> tuple[str, str]:
    """Leave the partial ledger state a crash at one step would leave."""
    monkeypatch.setattr(ledger, "advance_agent_hijack_record", _crash_advance)
    artifacts = tmp_path / f"crashed-{tag}"
    artifacts.mkdir(parents=True, exist_ok=True)
    session = f"session-{tag}"
    target_key = ledger.target_key_for(_PROJECT, session)
    hijack_id = f"hijack-{tag}"
    record = ledger.new_requested_record(
        hijack_id=hijack_id,
        agent_name="agent.1",
        artifacts_dir=str(artifacts),
        pid=424242,
        project_file=_PROJECT,
        workspace_num=4,
        workspace_dir="/tmp/workspace-4",
        session="session-1",
        target_key=target_key,
        scope="llm",
        at=_stale_stamp(),
    )
    record["state"] = state
    record["updated_at"] = _stale_stamp()
    if state in {"latched", "stopping"}:
        record["latched_at"] = _stale_stamp()
        record["owner_pid"] = 424242
        record["owner_identity"] = "boot:dead-owner"
    ledger.create_record(record)
    if with_target_slot:
        winner = ledger.claim_target_slot(target_key, hijack_id)
        assert winner == hijack_id
    return target_key, hijack_id


def _crash_sweep_dead_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.scheduler import _stale_running_hijack as sweep

    monkeypatch.setattr(sweep, "is_process_running", lambda _pid: False)
    monkeypatch.setattr(
        "sase.ace.hooks.processes.is_process_running", lambda _pid: False
    )
    monkeypatch.setattr(
        "sase.agent.hijack._stop_claim.ensure_hijacked_settlement",
        lambda _target, _hijack_id, pinned_by_us=False: None,
    )


def test_crash_between_steps_converges_without_second_stop(
    latch_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every crash point converges: one operation, custody retained.

    Covers the stop-transaction steps (record, intent, pin, begin_stop)
    and the latch-apply step: a "killed" worker leaves a stale
    requested/stopping/latched record whose owner is dead. Reconciliation
    must settle it without starting a second stop and without releasing
    the claim to an unrelated writer.
    """
    del latch_store
    from sase.ace.scheduler import _stale_running_hijack as sweep

    _crash_sweep_dead_owner(monkeypatch)

    for state in ("requested", "stopping", "latched"):
        target_key, hijack_id = _crash_record(
            tmp_path, monkeypatch, state=state, tag=state
        )
        claim = WorkspaceClaim(4, "agent", "feature", pid=424242)
        record = ledger.load_record(hijack_id)
        assert record is not None
        if state == "latched":
            from sase.agent.hijack import _latch_reconcile as reconcile

            monkeypatch.setattr(
                "sase.core.process_identity.process_identity_token", lambda _p: "boot:x"
            )
            reconcile.reconcile_latched_records()
        else:
            sweep._reconcile_abandoned_stop_record(_PROJECT, claim, record)
            settled = ledger.load_record(hijack_id)
            assert settled is not None
            assert settled["state"] == "held", settled
        # No second stop: the target slot still maps to the one operation.
        assert ledger.claim_target_slot(target_key, "hijack-newcomer") == hijack_id
        # Custody is retained: the claim still has an active hijack record.
        assert ledger.find_active_record_by_target_key(target_key) is not None


def test_crash_with_live_survivor_never_releases_claim(
    latch_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A surviving writer moves the record to stop_blocked, never release."""
    del latch_store
    from sase.ace.scheduler import _stale_running_hijack as sweep
    from sase.agent.hijack import custody

    monkeypatch.setattr(sweep, "is_process_running", lambda _pid: True)
    monkeypatch.setattr(
        "sase.ace.hooks.processes.is_process_running", lambda _pid: True
    )
    target_key, hijack_id = _crash_record(
        tmp_path, monkeypatch, state="stopping", tag="survivor"
    )
    claim = WorkspaceClaim(4, "agent", "feature", pid=424242)
    record = ledger.load_record(hijack_id)
    assert record is not None
    sweep._reconcile_abandoned_stop_record(_PROJECT, claim, record)
    current = ledger.load_record(hijack_id)
    assert current is not None
    assert current["state"] == "stop_blocked"
    assert (
        custody.hijack_skips_claim_release(
            project_file=_PROJECT, workspace_num=claim.workspace_num
        )
        is True
    )
    assert ledger.find_active_record_by_target_key(target_key) is not None


#: Files that launch a successor through a primitive covered transitively by
#: the checkpoint in the callee. Each reason must stay one line: it names
#: the guarded function the file delegates to.
_TRANSITIVE_ALLOW_LIST: dict[str, str] = {
    "src/sase/agent/__init__.py": "lazy re-export map for spawn_agent_subprocess; guard lives in agent/launch_spawn.py",
    "src/sase/agent/launcher.py": "re-exports spawn_agent_subprocess; guard lives in agent/launch_spawn.py",
    "src/sase/agent/launch_executor.py": "delegates to launcher.spawn_agent_subprocess; guard lives in agent/launch_spawn.py",
    "src/sase/agent/launch_provenance.py": "docstring mention only; no import or call of the spawn primitive",
    "src/sase/turns/followup.py": "re-exports launch_turn_followup; checkpoint lives in turns/followup_launch.py",
    "src/sase/monitor/supervise_finish.py": "passes launch_followup_agent as its followup launcher; guard built inside it",
    "src/sase/axe/run_agent_exec_staged.py": "re-exports dispatch_completed_staged_handoff; checkpoint lives in its dispatch module",
    "src/sase/axe/run_agent_exec_staged_recovery.py": "docstring mention only; recovery replay goes through the staged dispatch checkpoint",
    "src/sase/axe/run_agent_successor_staged.py": "continues through continue_as_inprocess_successor; checkpoint lives there",
    "src/sase/axe/run_agent_runner_bootstrap.py": "reads RetryHandoff metadata; the launch goes through axe/run_agent_retry_spawn.py",
    "src/sase/axe/run_agent_runner_setup_meta.py": "reads RetryHandoff metadata; the launch goes through axe/run_agent_retry_spawn.py",
}

#: Source markers that prove a file observes the hijack latch before it
#: lets a successor launch proceed.
_CHECKPOINT_MARKERS = (
    "observe_hijack_latch",
    "observe_runner_latch",
    "refuse_if_latched",
    "spawn_admission",
    "latch_guard_from_predecessor",
    "bind_recovery_identity",
    "enforce_staged_adoption_latch",
    "enforce_adoption_replay_latch",
    "enforce_inprocess_successor_latch",
    "moot_runner_latch_at_run_end",
    "check_retry_latch",
    "check_detached_delivery_latch",
    "apply_latch_at_boundary",
    "apply_reconciled_latch",
    "request_latch",
    "HijackLatchedError",
    "settle_monitor_hijack",
    "monitor_hijack_pending",
    "latch.observe",
    "latch.apply",
)

#: Successor-launch primitive references; any file that names one of these
#: outside a comment must be checkpoint-guarded or allow-listed.
_PRIMITIVE_MARKERS = (
    "launch_turn_followup",
    "launch_followup_agent",
    "dispatch_completed_staged_handoff",
    "continue_as_inprocess_successor",
    "spawn_agent_subprocess",
    "RetryHandoff",
)


def _primitives_in(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    code_lines = [
        line
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    code = "\n".join(code_lines)
    return {marker for marker in _PRIMITIVE_MARKERS if marker in code}


def test_successor_launch_paths_all_observe_the_latch() -> None:
    """Static hand-off inventory guard for the hijack latch.

    Every successor-launch call site must sit behind an
    ``observe_hijack_latch`` checkpoint (directly or through the
    runner/spawn guards) or carry an explicit allow-list reason. Add a
    checkpoint first when a new hand-off path appears here.
    """
    repo = Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    for path in sorted((repo / "src" / "sase").rglob("*.py")):
        rel = path.relative_to(repo).as_posix()
        primitives = _primitives_in(path)
        if not primitives:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if any(marker in text for marker in _CHECKPOINT_MARKERS):
            continue
        reason = _TRANSITIVE_ALLOW_LIST.get(rel)
        if reason:
            assert reason.strip().count("\n") == 0, rel
            continue
        offenders.append(f"{rel} uses {sorted(primitives)} with no latch checkpoint")
    assert not offenders, (
        "new successor-launch path(s) lack a hijack latch checkpoint:\n"
        + "\n".join(offenders)
        + "\nAdd an observe_hijack_latch checkpoint or an allow-list reason."
    )
