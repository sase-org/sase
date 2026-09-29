"""Recovery-verdict tests for gateless ``sase plan approve`` runs.

Split from ``tests.test_plan_direct_approval_recovery``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.main.plan_direct_approval_recovery import (
    PriorCoder,
    evaluate_approval_recovery,
)
from sase.main.plan_pending_diagnosis import PlanGateHistory
from sase.plan_approval_receipts import (
    DirectApprovalReceipt,
    write_direct_approval_receipt,
)
from tests._plan_direct_approval_recovery_helpers import (
    failed_prior,
    handled_history,
    local_plan,
    no_color,  # noqa: F401 (registers the autouse fixture)
    recovery_home,  # noqa: F401 (registers the sase_home_dir fixture)
)

__all__ = [
    "test_committed_done_with_unknown_coder_refuses",
    "test_commit_receipt_with_launch_error_recovers",
    "test_crash_receipt_recovers_again",
    "test_direct_non_coder_receipt_keeps_refusal",
    "test_fresh_histories_keep_refusal",
    "test_gate_coder_used_when_receipt_lost_race",
    "test_handled_tale_failed_coder_recovers",
    "test_live_coder_refuses",
    "test_missing_gate_turn_and_no_code_recovers",
    "test_non_coder_histories_keep_refusal",
    "test_second_run_with_live_replacement_refuses",
    "test_succeeded_coder_refuses",
]


def _patch_facts(monkeypatch: pytest.MonkeyPatch, action: str, ref: str | None) -> None:
    monkeypatch.setattr(
        "sase.main.plan_pending_diagnosis._gate_approval_facts",
        lambda bundle_path: (action, ref),
    )


def test_handled_tale_failed_coder_recovers(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = local_plan(sase_home_dir)
    history = handled_history()
    _patch_facts(monkeypatch, "tale", "plan:202609/work.md")
    monkeypatch.setattr(
        "sase.main.plan_pending_diagnosis.gate_history_for_plan",
        lambda local: [{"state": "already_handled", "notification_id": "gate123"}],
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._gate_followup_coder",
        lambda entry, project: "0sk--code",
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._classify_prior_coder",
        lambda name: failed_prior(name),
    )

    recovery = evaluate_approval_recovery(
        local_plan=plan, history=history, project="demo"
    )

    assert recovery is not None
    assert recovery.verdict == "recover"
    assert recovery.plan_argument == "plan:202609/work.md"
    assert recovery.approved_action == "tale"
    assert recovery.approved_age == "7m ago"
    assert recovery.gate_id == "gate123"
    assert [prior.name for prior in recovery.prior_coders] == ["0sk--code"]


def test_live_coder_refuses(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = local_plan(sase_home_dir)
    _patch_facts(monkeypatch, "tale", "plan:202609/work.md")
    monkeypatch.setattr(
        "sase.main.plan_pending_diagnosis.gate_history_for_plan",
        lambda local: [{"state": "already_handled"}],
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._gate_followup_coder",
        lambda entry, project: "0sk--code",
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._classify_prior_coder",
        lambda name: PriorCoder(name=name, state="live", outcome="running"),
    )

    recovery = evaluate_approval_recovery(
        local_plan=plan, history=handled_history(), project="demo"
    )

    assert recovery is not None
    assert recovery.verdict == "live"
    assert recovery.refusal_code == "coder_running"


def test_succeeded_coder_refuses(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = local_plan(sase_home_dir)
    _patch_facts(monkeypatch, "approve", None)
    monkeypatch.setattr(
        "sase.main.plan_pending_diagnosis.gate_history_for_plan",
        lambda local: [{"state": "already_handled"}],
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._gate_followup_coder",
        lambda entry, project: "0sk--code",
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._classify_prior_coder",
        lambda name: PriorCoder(
            name=name, state="succeeded", outcome="completed", age="2h ago"
        ),
    )

    recovery = evaluate_approval_recovery(
        local_plan=plan, history=handled_history(), project="demo"
    )

    assert recovery is not None
    assert recovery.verdict == "succeeded"
    assert recovery.refusal_code == "already_implemented"
    assert recovery.plan_argument == str(plan)


def test_committed_done_with_unknown_coder_refuses(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = local_plan(sase_home_dir)
    _patch_facts(monkeypatch, "tale", "plan:202609/work.md")
    monkeypatch.setattr(
        "sase.main.plan_pending_diagnosis.gate_history_for_plan",
        lambda local: [{"state": "already_handled"}],
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._gate_followup_coder",
        lambda entry, project: None,
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._committed_plan_is_done",
        lambda ref, cwd: True,
    )

    recovery = evaluate_approval_recovery(
        local_plan=plan, history=handled_history(), project="demo"
    )

    assert recovery is not None
    assert recovery.verdict == "succeeded"
    assert recovery.prior_coders == ()


def test_missing_gate_turn_and_no_code_recovers(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = local_plan(sase_home_dir)
    _patch_facts(monkeypatch, "tale", "plan:202609/work.md")
    monkeypatch.setattr(
        "sase.main.plan_pending_diagnosis.gate_history_for_plan",
        lambda local: [{"state": "already_handled"}],
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._gate_followup_coder",
        lambda entry, project: None,
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._committed_plan_is_done",
        lambda ref, cwd: False,
    )

    recovery = evaluate_approval_recovery(
        local_plan=plan, history=handled_history(), project="demo"
    )

    assert recovery is not None
    assert recovery.verdict == "recover"
    assert recovery.prior_coders == ()


def test_commit_receipt_with_launch_error_recovers(sase_home_dir: Path) -> None:
    plan = local_plan(sase_home_dir)
    write_direct_approval_receipt(
        DirectApprovalReceipt(
            plan_path=str(plan),
            action="commit",
            approved_at="2026-09-25T19:00:00+00:00",
            plan_archive_ref="plan:202609/work.md",
            coder_error="boom",
        )
    )
    history = PlanGateHistory(kind="direct", action="commit", age=" (5m ago)")

    recovery = evaluate_approval_recovery(
        local_plan=plan, history=history, project="demo"
    )

    assert recovery is not None
    assert recovery.verdict == "recover"
    assert recovery.approved_action == "commit"


def test_gate_coder_used_when_receipt_lost_race(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = local_plan(sase_home_dir)
    write_direct_approval_receipt(
        DirectApprovalReceipt(
            plan_path=str(plan),
            action="tale",
            approved_at="2026-09-25T19:00:00+00:00",
            route="none",
            plan_archive_ref="plan:202609/work.md",
            coder_error="gate race-gate was answered concurrently; no coder launched",
        )
    )
    history = PlanGateHistory(kind="direct", action="tale", age=" (5m ago)")
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._gate_entry_for_plan",
        lambda local, gate_id: {"state": "already_handled"},
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._gate_followup_coder",
        lambda entry, project: "0sk--code",
    )
    states = {"mode": "failed"}
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._classify_prior_coder",
        lambda name: (
            failed_prior(name)
            if states["mode"] == "failed"
            else PriorCoder(name=name, state="live", outcome="running")
        ),
    )

    failed = evaluate_approval_recovery(
        local_plan=plan, history=history, project="demo"
    )
    assert failed is not None
    assert failed.verdict == "recover"

    states["mode"] = "live"
    running = evaluate_approval_recovery(
        local_plan=plan, history=history, project="demo"
    )
    assert running is not None
    assert running.verdict == "live"


def test_second_run_with_live_replacement_refuses(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = local_plan(sase_home_dir)
    write_direct_approval_receipt(
        DirectApprovalReceipt(
            plan_path=str(plan),
            action="tale",
            approved_at="2026-09-25T19:00:00+00:00",
            route="session",
            plan_archive_ref="plan:202609/work.md",
            coder_agent="0sk--2",
            coder_pid=4242,
            replaced_coders=("0sk--code",),
            recovered_gate_id="gate123",
        )
    )
    history = PlanGateHistory(kind="direct", action="tale", age="")
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._classify_prior_coder",
        lambda name: (
            PriorCoder(name=name, state="live", outcome="running")
            if name == "0sk--2"
            else PriorCoder(name=name, state="missing")
        ),
    )

    recovery = evaluate_approval_recovery(
        local_plan=plan, history=history, project="demo"
    )

    assert recovery is not None
    assert recovery.verdict == "live"
    assert [prior.name for prior in recovery.prior_coders] == [
        "0sk--2",
        "0sk--code",
    ]


def test_crash_receipt_recovers_again(sase_home_dir: Path) -> None:
    plan = local_plan(sase_home_dir)
    write_direct_approval_receipt(
        DirectApprovalReceipt(
            plan_path=str(plan),
            action="tale",
            approved_at="2026-09-25T19:00:00+00:00",
            route="session",
            plan_archive_ref="plan:202609/work.md",
            replaced_coders=("0sk--code",),
            recovered_gate_id="gate123",
        )
    )
    history = PlanGateHistory(kind="direct", action="tale", age="")

    recovery = evaluate_approval_recovery(
        local_plan=plan, history=history, project="demo"
    )

    assert recovery is not None
    assert recovery.verdict == "recover"


@pytest.mark.parametrize("action", ["epic", "reject", "feedback", "cancel"])
def test_non_coder_histories_keep_refusal(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    plan = local_plan(sase_home_dir)
    _patch_facts(monkeypatch, action, None)
    monkeypatch.setattr(
        "sase.main.plan_pending_diagnosis.gate_history_for_plan",
        lambda local: [{"state": "already_handled"}],
    )

    recovery = evaluate_approval_recovery(
        local_plan=plan, history=handled_history(action=action), project="demo"
    )

    assert recovery is None


def test_direct_non_coder_receipt_keeps_refusal(sase_home_dir: Path) -> None:
    plan = local_plan(sase_home_dir)
    write_direct_approval_receipt(
        DirectApprovalReceipt(
            plan_path=str(plan),
            action="reject",
            approved_at="2026-09-25T19:00:00+00:00",
        )
    )
    history = PlanGateHistory(kind="direct", action="reject", age="")

    assert (
        evaluate_approval_recovery(local_plan=plan, history=history, project="demo")
        is None
    )


def test_fresh_histories_keep_refusal(sase_home_dir: Path) -> None:
    plan = local_plan(sase_home_dir)
    for kind in ("none", "orphaned", "expired"):
        history = PlanGateHistory(kind=kind)  # type: ignore[arg-type]
        assert (
            evaluate_approval_recovery(local_plan=plan, history=history, project="demo")
            is None
        )
