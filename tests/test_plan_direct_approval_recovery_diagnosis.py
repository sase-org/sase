"""Diagnosis tests for gateless ``sase plan approve`` runs.

Split from ``tests.test_plan_direct_approval_recovery``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.main.plan_pending_diagnosis import PlanGateHistory
from sase.plan_approval_receipts import (
    DirectApprovalReceipt,
    read_direct_approval_receipt,
    write_direct_approval_receipt,
)
from tests._plan_direct_approval_recovery_helpers import (
    local_plan,
    no_color,  # noqa: F401 (registers the autouse fixture)
    recovery_home,  # noqa: F401 (registers the sase_home_dir fixture)
)

__all__ = [
    "test_handled_age_uses_handled_at",
    "test_inspect_hint_prefers_committed_ref",
    "test_receipt_round_trips_recovery_fields",
    "test_recovery_receipt_wording",
    "test_refusal_hint_prints_once",
    "test_response_refines_approve_commit_to_tale",
]


def test_handled_age_uses_handled_at(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time as time_module

    from sase.main.plan_pending_diagnosis import classify_plan_gate_history
    from sase.notifications import pending_actions
    from sase.notifications.models import Notification
    from sase.notifications.store import append_notification

    plan = local_plan(sase_home_dir)
    created = time_module.time() - 42 * 60
    handled = time_module.time() - 7 * 60
    with monkeypatch.context() as patcher:
        patcher.setattr(time_module, "time", lambda: created)
        append_notification(
            Notification(
                id="abcdef01-full",
                timestamp="2026-09-25T19:00:00+00:00",
                sender="test",
                notes=["note"],
                files=[str(plan)],
                action="PlanApproval",
                action_data={
                    "agent_name": "0sk",
                    "original_plan_file": str(plan),
                    "response_dir": str(sase_home_dir / "resp"),
                },
            )
        )
    pending_actions.mark_already_handled(
        "abcdef01-full", source="test", action="approve", now=handled
    )

    history = classify_plan_gate_history(plan)

    assert history.kind == "handled"
    assert history.age == " (7m ago)"


def test_response_refines_approve_commit_to_tale(tmp_path: Path) -> None:
    from sase.main.plan_pending_diagnosis import (
        _gate_approval_facts,
        refined_gate_history_action,
    )

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "request.json").write_text(
        json.dumps({"request_id": "g1", "kind": "tale"}), encoding="utf-8"
    )
    (bundle / "response.json").write_text(
        json.dumps(
            {
                "selected_option_ids": ["approve", "commit"],
                "option_results": [
                    {
                        "id": "approve",
                        "result": {"plan_archive_ref": "plan:202609/work.md"},
                    },
                    {"id": "commit", "result": {}},
                ],
            }
        ),
        encoding="utf-8",
    )

    action, ref = _gate_approval_facts(bundle)

    assert action == "tale"
    assert ref == "plan:202609/work.md"
    history = PlanGateHistory(kind="handled", action="approve", bundle_path=bundle)
    assert refined_gate_history_action(history) == "tale"


def test_inspect_hint_prefers_committed_ref(tmp_path: Path) -> None:
    from sase.main.plan_pending_diagnosis import inspect_command_for_located_plan

    history = PlanGateHistory(
        kind="handled", action="tale", bundle_path=tmp_path / "missing"
    )
    assert (
        inspect_command_for_located_plan(
            Path("/home/u/.sase/plans/202609/work.md"), history
        )
        == "sase plan show /home/u/.sase/plans/202609/work.md"
    )


def test_refusal_hint_prints_once(capsys: pytest.CaptureFixture[str]) -> None:
    from sase.main.plan_approve_render import render_direct_approval_refusal
    from sase.main.plan_direct_approval import DirectApprovalRefusal

    hint = "sase plan show plan:202609/work.md"
    render_direct_approval_refusal(
        DirectApprovalRefusal(
            code="conflict_already_handled",
            header="work is not awaiting approval",
            detail_lines=(f"Inspect it with: {hint}",),
            hints=(hint,),
        )
    )

    assert capsys.readouterr().err.count(hint) == 1


def test_recovery_receipt_wording(sase_home_dir: Path) -> None:
    from sase.main.plan_pending_diagnosis import direct_approval_via_text

    plan = local_plan(sase_home_dir)
    assert direct_approval_via_text(plan) == "via sase plan approve"
    write_direct_approval_receipt(
        DirectApprovalReceipt(
            plan_path=str(plan),
            action="tale",
            approved_at="2026-09-25T19:00:00+00:00",
            replaced_coders=("0sk--code",),
            recovered_gate_id="gate123",
        )
    )

    assert direct_approval_via_text(plan) == "coder relaunched via sase plan approve"


def test_receipt_round_trips_recovery_fields(sase_home_dir: Path) -> None:
    plan = local_plan(sase_home_dir)
    write_direct_approval_receipt(
        DirectApprovalReceipt(
            plan_path=str(plan),
            action="tale",
            approved_at="2026-09-25T19:00:00+00:00",
            replaced_coders=("0sk--code", "0sk--2"),
            recovered_gate_id="gate123",
        )
    )

    receipt = read_direct_approval_receipt(plan)

    assert receipt is not None
    assert receipt.replaced_coders == ("0sk--code", "0sk--2")
    assert receipt.recovered_gate_id == "gate123"
