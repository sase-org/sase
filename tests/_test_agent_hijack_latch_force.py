"""Force and reconciliation contracts for agent hijack latches."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack import core, ledger, latch
from sase.agent.hijack import _latch_apply as latch_apply
from sase.agent.hijack import _latch_common as latch_common
from sase.agent.hijack import _latch_force as latch_force
from sase.agent.hijack._stop_models import HijackTarget
from sase.running_field import WorkspaceClaim
from tests._agent_hijack_latch_support import (
    install_subjects,
    make_subject,
    make_target,
    shared_latch_store,
)

__all__ = ["shared_latch_store"]


def _acquired_lock():
    from contextlib import contextmanager

    @contextmanager
    def _lock():
        yield True

    return _lock()


def test_force_refuses_before_timeout_without_signalling(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    target = make_target(tmp_path / "member")
    install_subjects(monkeypatch, make_subject(target))
    requested = latch.request_latch(target.name)
    monkeypatch.setattr(
        core,
        "hijack_latch_force_eligibility",
        lambda record, now: {
            "eligible": False,
            "code": "force_too_early",
            "message": "the pending latch is younger than 120 seconds",
            "age_seconds": 119,
            "threshold_seconds": 120,
        },
    )
    monkeypatch.setattr(
        "sase.agent.staged_handoff.acquire_adoption_lock",
        lambda *_args, **_kwargs: _acquired_lock(),
    )
    monkeypatch.setattr(
        "sase.agent.hijack._stop_orchestrator_common.terminate_with_retry",
        lambda *_args, **_kwargs: pytest.fail("young latch must not signal"),
    )

    result = latch_force.force_hijack_latch(str(requested["target_key"]))

    assert result["verdict"] == "refused"
    assert result["code"] == "force_too_early"
    assert result["next_action"].startswith("wait 1 more seconds")
    assert ledger.load_record(str(requested["hijack_id"]))["state"] == "latched"


def test_eligible_force_reuses_latch_id_and_persists_interruption_custody(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent._user_kill_intent import hijack_intent_id, has_user_kill_intent

    target = make_target(tmp_path / "member")
    install_subjects(monkeypatch, make_subject(target))
    requested = latch.request_latch(target.name)
    target.claim_pinned = False
    termination_targets: list[HijackTarget] = []
    monkeypatch.setattr(
        core,
        "hijack_latch_force_eligibility",
        lambda record, now: {
            "eligible": True,
            "age_seconds": 120,
            "threshold_seconds": 120,
        },
    )
    monkeypatch.setattr(
        "sase.agent.staged_handoff.acquire_adoption_lock",
        lambda *_args, **_kwargs: _acquired_lock(),
    )
    monkeypatch.setattr(latch_force, "pin_claim", lambda _target: True)
    monkeypatch.setattr(
        "sase.agent.hijack._stop_orchestrator_common.terminate_with_retry",
        lambda value, **_kwargs: (
            termination_targets.append(value) or SimpleNamespace(success=True)
        ),
    )
    monkeypatch.setattr(
        latch,
        "complete_latch_application",
        lambda current, _target, **_kwargs: {
            "verdict": "applied",
            "record": current,
            "ready": True,
        },
    )

    result = latch_force.force_hijack_latch(str(requested["target_key"]))

    record = ledger.load_record(str(requested["hijack_id"]))
    assert result["verdict"] == "applied"
    assert result["forced"] is True
    assert result["hijack_id"] == requested["hijack_id"]
    assert result["next_action"].startswith("inspect the recovery snapshot")
    assert record["state"] == "stopping"
    assert record["forced"] is True
    assert record["boundary"] == "forced_stop"
    assert record["boundary_outcome"] == "interrupted"
    assert len(termination_targets) == 1
    assert has_user_kill_intent(target.artifacts_dir)
    assert hijack_intent_id(target.artifacts_dir) == requested["hijack_id"]


def test_force_preserves_custody_when_transition_commit_result_is_uncertain(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent._user_kill_intent import has_user_kill_intent

    target = make_target(tmp_path / "member")
    install_subjects(monkeypatch, make_subject(target))
    requested = latch.request_latch(target.name)
    monkeypatch.setattr(
        core,
        "hijack_latch_force_eligibility",
        lambda *_args: {"eligible": True, "age_seconds": 120},
    )
    monkeypatch.setattr(
        "sase.agent.staged_handoff.acquire_adoption_lock",
        lambda *_args, **_kwargs: _acquired_lock(),
    )
    pin_calls: list[bool] = []
    monkeypatch.setattr(latch_force, "pin_claim", lambda _target: True)
    monkeypatch.setattr(
        latch_force, "unpin_claim", lambda _target: pin_calls.append(True)
    )
    actual_advance = ledger.cas_advance_record

    def commit_then_raise(
        record: dict[str, Any], event: dict[str, Any]
    ) -> dict[str, Any]:
        actual_advance(record, event)
        raise OSError("simulated lost CAS response")

    monkeypatch.setattr(ledger, "cas_advance_record", commit_then_raise)
    monkeypatch.setattr(
        "sase.agent.hijack._stop_orchestrator_common.terminate_with_retry",
        lambda *_args, **_kwargs: pytest.fail("uncertain CAS must not signal"),
    )

    result = latch_force.force_hijack_latch(str(requested["target_key"]))

    record = ledger.load_record(str(requested["hijack_id"]))
    assert result["code"] == "latch_transition_uncertain"
    assert record["state"] == "stopping"
    assert record["forced"] is True
    assert has_user_kill_intent(target.artifacts_dir)
    assert pin_calls == []


def test_force_rejects_a_stale_selected_id_and_cancelled_latch(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    target = make_target(tmp_path / "member")
    install_subjects(monkeypatch, make_subject(target))
    requested = latch.request_latch(target.name)
    stale = latch_force.force_hijack_latch(
        str(requested["target_key"]), hijack_id="hijack-old"
    )
    assert stale["code"] == "hijack_id_mismatch"

    cancelled = latch.cancel_latch(str(requested["target_key"]))
    assert cancelled["verdict"] == "cancelled"
    rejected = latch_force.force_hijack_latch(
        str(requested["target_key"]), hijack_id=str(requested["hijack_id"])
    )
    assert rejected["code"] == "latch_cancelled"


def test_adopted_successor_moots_latch_after_claim_transfer(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.hijack import _latch_reconcile as latch_reconcile
    from sase.agent.hijack import _latch_reconcile_evidence as evidence

    target = make_target(tmp_path / "member")
    install_subjects(monkeypatch, make_subject(target))
    requested = latch.request_latch(target.name)
    hijack_id = str(requested["hijack_id"])
    monkeypatch.setattr(
        latch_reconcile,
        "owner_observation",
        lambda _record: ({"lookup_succeeded": True, "pid": None}, "dead"),
    )
    monkeypatch.setattr(
        latch_reconcile,
        "successor_observation",
        lambda *_args: ({"kind": "launched", "name": "agent.2"}, None),
    )
    monkeypatch.setattr(
        latch_reconcile, "read_real_outcome", lambda _artifacts: "completed"
    )
    monkeypatch.setattr(
        core,
        "hijack_latch_reconcile",
        lambda *_args: {"outcome": "moot_latch"},
    )
    monkeypatch.setattr(
        evidence,
        "get_claimed_workspaces",
        lambda *_args: pytest.fail("mooting must not require the transferred claim"),
    )

    latch_reconcile._reconcile_under_adoption_lock(
        hijack_id,
        str(requested["target_key"]),
        target.artifacts_dir,
        log_fn=None,
    )

    record = ledger.load_record(hijack_id)
    assert record["state"] == "finished_first"
    assert record["boundary_outcome"] == "completed"
    assert ledger.find_active_record_by_target_key(str(requested["target_key"])) is None


def test_stale_reconciliation_applies_dead_owner_once_and_finishes_evidence(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.hijack import _latch_reconcile as latch_reconcile
    from sase.agent.hijack import _latch_reconcile_evidence as evidence
    from sase.agent import _user_kill_intent as user_kill_intent

    target = make_target(tmp_path / "member")
    install_subjects(monkeypatch, make_subject(target))
    requested = latch.request_latch(target.name)
    hijack_id = str(requested["hijack_id"])
    claim = WorkspaceClaim(
        workspace_num=4,
        workflow="agent",
        cl_name="sample-patch",
        pid=42,
        artifacts_timestamp=Path(target.artifacts_dir).name,
        pinned=True,
    )
    termination_calls: list[int] = []
    settlement_calls: list[str] = []
    monkeypatch.setattr(
        latch_reconcile,
        "owner_observation",
        lambda _record: ({"lookup_succeeded": True, "pid": None}, "dead"),
    )
    monkeypatch.setattr(
        latch_reconcile,
        "successor_observation",
        lambda *_args: ({"kind": "absent"}, None),
    )
    monkeypatch.setattr(latch_reconcile, "read_real_outcome", lambda _artifacts: None)
    monkeypatch.setattr(
        core,
        "hijack_latch_reconcile",
        lambda *_args: {"outcome": "apply_latch"},
    )
    monkeypatch.setattr(
        evidence,
        "get_claimed_workspaces",
        lambda _project: [claim],
    )
    monkeypatch.setattr(latch_apply, "pin_claim", lambda _target: True)
    monkeypatch.setattr(
        user_kill_intent,
        "has_user_kill_intent",
        lambda _artifacts: False,
    )
    monkeypatch.setattr(
        user_kill_intent,
        "write_user_kill_intent",
        lambda *_args, **_kwargs: Path(target.artifacts_dir) / "intent",
    )
    monkeypatch.setattr(
        "sase.agent.hijack._stop_orchestrator_common.terminate_with_retry",
        lambda value, **_kwargs: (
            termination_calls.append(value.pid or 0) or SimpleNamespace(success=True)
        ),
    )
    monkeypatch.setattr(
        latch_apply,
        "apply_latched_settlement",
        lambda _target, operation_id: settlement_calls.append(operation_id),
    )
    monkeypatch.setattr(
        latch_apply,
        "collect_and_attach_evidence",
        lambda operation_id, _target, **_kwargs: (
            ledger.load_record(operation_id),
            None,
            None,
        ),
    )

    for _ in range(2):
        latch_reconcile._reconcile_under_adoption_lock(
            hijack_id,
            str(requested["target_key"]),
            target.artifacts_dir,
            log_fn=None,
        )

    record = ledger.load_record(hijack_id)
    assert record["state"] == "held"
    assert record["boundary"] == "owner_recovery"
    assert record["boundary_outcome"] == "interrupted"
    assert termination_calls == [42]
    assert settlement_calls == [hijack_id]
