"""Executor tests for gateless ``sase plan approve`` runs.

Split from ``tests.test_plan_direct_approval_recovery``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.launch_types import AgentLaunchResult
from sase.main.plan_direct_approval import (
    CoderPlacement,
    DirectApprovalPlan,
    DirectApprovalRefused,
    DirectApprovalRequest,
)
from sase.main.plan_direct_approval_recovery import (
    CoderRecovery,
    PriorCoder,
)
from sase.plan_approval_receipts import read_direct_approval_receipt
from tests._plan_direct_approval_recovery_helpers import (
    failed_prior,
    handled_history,
    local_plan,
    no_color,  # noqa: F401 (registers the autouse fixture)
    recovery_home,  # noqa: F401 (registers the sase_home_dir fixture)
)

__all__ = [
    "test_executor_agent_guard",
    "test_executor_launch_failure_records_error",
    "test_executor_launches_one_coder_and_writes_receipt",
    "test_executor_lock_recheck_refuses_without_launching",
]


def _recovery_plan(home: Path, **overrides: object) -> DirectApprovalPlan:
    source = local_plan(home)
    recovery = CoderRecovery(
        verdict="recover",
        prior_coders=(failed_prior(),),
        approved_action="tale",
        approved_age="7m ago",
        gate_id="gate123",
        plan_argument="plan:202609/work.md",
    )
    fields: dict[str, object] = {
        "request": DirectApprovalRequest(selector=str(source), project="demo"),
        "kind": "tale",
        "source_path": source,
        "location": "proposal",
        "name": "work",
        "title": "Work",
        "size": "small",
        "project": "demo",
        "project_tag": "+demo",
        "planner": "0sk",
        "gate": None,
        "placement": CoderPlacement(
            mode="session",
            parent="0sk",
            member_name="0sk--2",
            agent_session="0sk",
        ),
        "model_directive": "@small",
        "bead": None,
        "predicted_plan_ref": "plan:202609/work.md",
        "coder_prompt_preview": "+demo %model:@small #coder(plan:202609/work.md)",
        "recovery": recovery,
    }
    fields.update(overrides)
    return DirectApprovalPlan(**fields)  # type: ignore[arg-type]


def _launch_result(home: Path) -> AgentLaunchResult:
    return AgentLaunchResult(
        pid=4242,
        workspace_num=1,
        workspace_dir=str(home),
        output_path=str(home / "out.log"),
        agent_name="0sk--2",
    )


def test_executor_launches_one_coder_and_writes_receipt(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main.plan_direct_approval_run import execute_coder_recovery

    monkeypatch.setattr(
        "sase.config._owner.require_agent_owner_identity", lambda: object()
    )
    plan = _recovery_plan(sase_home_dir)
    launched = _launch_result(sase_home_dir)
    seen_env: dict[str, str] = {}
    with (
        patch(
            "sase.agent.launch_cwd.launch_agents_from_cwd",
            side_effect=lambda prompt, extra_env=None, **kwargs: (
                seen_env.update(extra_env or {}),
                [launched],
            )[1],
        ) as launch,
        patch(
            "sase._plan_archive_approval.archive_approved_plan",
            side_effect=AssertionError("recovery never archives"),
        ),
        patch(
            "sase.notification_gates.executor_cancellation.cancel_gate",
            side_effect=AssertionError("recovery never retires gates"),
        ),
        patch(
            "sase.plan_approval_actions.record_plan_approval_metadata",
            side_effect=AssertionError("recovery never records metadata"),
        ),
    ):
        outcome = execute_coder_recovery(plan)

    assert launch.call_count == 1
    assert outcome.coder is launched
    assert seen_env.get("SASE_PLAN") == str(plan.source_path)
    assert "SASE_PLAN" in launch.call_args[1].get("extra_env", {})
    receipt = read_direct_approval_receipt(plan.source_path)
    assert receipt is not None
    assert receipt.replaced_coders == ("0sk--code",)
    assert receipt.coder_agent == "0sk--2"
    assert receipt.coder_pid == 4242
    assert receipt.recovered_gate_id == "gate123"
    assert receipt.plan_archive_ref == "plan:202609/work.md"


def test_executor_launch_failure_records_error(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent._agent_session_attach_types import AgentSessionAttachLaunchPlan
    from sase.main.plan_direct_approval_run import execute_coder_recovery

    monkeypatch.setattr(
        "sase.config._owner.require_agent_owner_identity", lambda: object()
    )
    plan = _recovery_plan(sase_home_dir)

    def resolve_attach(directive, *, project_name: str, **_kwargs):
        return AgentSessionAttachLaunchPlan(
            parent_arg=directive.parent,
            suffix_arg=directive.suffix,
            parent_name="0sk",
            parent_base="0sk",
            parent_timestamp="20260901120000",
            parent_artifacts_dir=str(sase_home_dir / "parent"),
            role_suffix="--2",
            agent_name="0sk--2",
            agent_session_role="coder",
            parent_agent_session_member_name="0sk",
            parent_agent_session_role_suffix="--0",
            parent_needs_rename=False,
            parent_project_name=project_name,
        )

    with (
        patch(
            "sase.agent._agent_session_attach_resolution.resolve_agent_session_attach_plan",
            side_effect=resolve_attach,
        ),
        patch(
            "sase.agent.launch_cwd.launch_agents_from_cwd",
            side_effect=RuntimeError("boom"),
        ) as launch,
    ):
        outcome = execute_coder_recovery(plan)

    assert outcome.coder is None
    assert outcome.coder_error == "boom"
    # A session placement now tries session then standalone.
    assert launch.call_count == 2
    receipt = read_direct_approval_receipt(plan.source_path)
    assert receipt is not None
    assert receipt.coder_error == "boom"
    assert receipt.replaced_coders == ("0sk--code",)


def test_executor_lock_recheck_refuses_without_launching(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main.plan_direct_approval_run import execute_coder_recovery

    plan = _recovery_plan(sase_home_dir)
    live = CoderRecovery(
        verdict="live",
        prior_coders=(PriorCoder(name="0sk--2", state="live", outcome="running"),),
        approved_action="tale",
        approved_age="",
        gate_id="gate123",
        plan_argument="plan:202609/work.md",
        refusal_code="coder_running",
    )
    monkeypatch.setattr(
        "sase.main.plan_pending_diagnosis.classify_plan_gate_history",
        lambda local: handled_history(),
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery.evaluate_approval_recovery",
        lambda **kwargs: live,
    )
    launch = MagicMock(side_effect=AssertionError("must not launch"))
    monkeypatch.setattr("sase.agent.launch_cwd.launch_agents_from_cwd", launch)

    with pytest.raises(DirectApprovalRefused) as exc_info:
        execute_coder_recovery(plan)

    assert exc_info.value.refusal.code == "coder_running"
    launch.assert_not_called()


def test_executor_agent_guard(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main.plan_direct_approval_run import execute_coder_recovery
    from sase.plan_approval_actions import PlanApprovalActionError

    monkeypatch.setenv("SASE_AGENT", "1")
    with pytest.raises(PlanApprovalActionError) as exc_info:
        execute_coder_recovery(_recovery_plan(sase_home_dir))
    assert exc_info.value.code == "agent_launch_denied"


def test_recovery_lock_timeout_raises_approval_in_progress(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main.plan_direct_approval_run import execute_coder_recovery
    from sase.plan_approval_actions import PlanApprovalActionError

    plan = _recovery_plan(sase_home_dir)
    monkeypatch.setattr(
        "sase.notification_gates.durability.file_lock",
        lambda *a, **k: (_ for _ in ()).throw(
            __import__(
                "sase.notification_gates.model_validation", fromlist=["GateError"]
            ).GateError("lock_timeout", "lock", "busy")
        ),
    )
    with pytest.raises(PlanApprovalActionError) as exc_info:
        execute_coder_recovery(plan)
    assert exc_info.value.code == "approval_in_progress"
