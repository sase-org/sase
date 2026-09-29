"""Resolver tests for gateless ``sase plan approve`` runs.

Split from ``tests.test_plan_direct_approval_recovery``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.agent.agent_session_attach import AgentSessionAttachLaunchPlan
from sase.main.plan_direct_approval import (
    DirectApprovalRefusal,
    DirectApprovalRequest,
)
from sase.main.plan_direct_approval_recovery import (
    CoderRecovery,
    PriorCoder,
)
from tests._plan_direct_approval_recovery_helpers import (
    failed_prior,
    handled_history,
    local_plan,
    no_color,  # noqa: F401 (registers the autouse fixture)
    recovery_home,  # noqa: F401 (registers the sase_home_dir fixture)
)

__all__ = [
    "test_resolver_explicit_commit_keeps_handled_refusal",
    "test_resolver_live_verdict_refuses_coder_running",
    "test_resolver_returns_recovery_plan",
]


def _attach_plan(*, running: bool = False) -> AgentSessionAttachLaunchPlan:
    return AgentSessionAttachLaunchPlan(
        parent_arg="0sk",
        suffix_arg="code",
        parent_name="0sk",
        parent_base="0sk",
        parent_timestamp="20260925000000",
        parent_artifacts_dir="/tmp/planner",
        role_suffix="--code",
        agent_name="0sk--code",
        agent_session_role="code",
        parent_agent_session_member_name="0sk",
        parent_agent_session_role_suffix="--0",
        parent_needs_rename=False,
        parent_project_name="demo",
        parent_is_running=running,
    )


def test_resolver_returns_recovery_plan(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main.plan_direct_approval import resolve_direct_approval

    plan = local_plan(sase_home_dir)
    monkeypatch.setattr(
        "sase.main.plan_pending_diagnosis.classify_plan_gate_history",
        lambda local: handled_history(),
    )
    recovery = CoderRecovery(
        verdict="recover",
        prior_coders=(failed_prior(),),
        approved_action="tale",
        approved_age="7m ago",
        gate_id="gate123",
        plan_argument="plan:202609/work.md",
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery.evaluate_approval_recovery",
        lambda **kwargs: recovery,
    )
    monkeypatch.setattr(
        "sase.agent.agent_session_attach.resolve_agent_session_attach_plan",
        lambda directive, project_name=None: _attach_plan(),
    )

    outcome = resolve_direct_approval(
        DirectApprovalRequest(selector=str(plan), project="demo")
    )

    assert not isinstance(outcome, (DirectApprovalRefusal, type(None)))
    assert outcome.recovery is recovery
    assert outcome.predicted_plan_ref == "plan:202609/work.md"
    assert "#coder(plan:202609/work.md)" in outcome.coder_prompt_preview
    assert "archive_approved_plan" not in outcome.coder_prompt_preview


def test_resolver_live_verdict_refuses_coder_running(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main.plan_direct_approval import resolve_direct_approval

    plan = local_plan(sase_home_dir)
    monkeypatch.setattr(
        "sase.main.plan_pending_diagnosis.classify_plan_gate_history",
        lambda local: handled_history(),
    )
    recovery = CoderRecovery(
        verdict="live",
        prior_coders=(PriorCoder(name="0sk--code", state="live", outcome="running"),),
        approved_action="tale",
        approved_age="7m ago",
        gate_id="gate123",
        plan_argument="plan:202609/work.md",
        refusal_code="coder_running",
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery.evaluate_approval_recovery",
        lambda **kwargs: recovery,
    )

    outcome = resolve_direct_approval(
        DirectApprovalRequest(selector=str(plan), project="demo")
    )

    assert isinstance(outcome, DirectApprovalRefusal)
    assert outcome.code == "coder_running"
    assert "already approved and its coder is running" in outcome.header
    assert outcome.detail_lines[2] == "coder   0sk--code · running"
    assert outcome.hints == ("sase agent show 0sk--code",)


def test_resolver_explicit_commit_keeps_handled_refusal(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main.plan_direct_approval import resolve_direct_approval

    plan = local_plan(sase_home_dir)
    history = handled_history()
    monkeypatch.setattr(
        "sase.main.plan_pending_diagnosis.classify_plan_gate_history",
        lambda local: history,
    )
    evaluate = MagicMock(return_value=None)
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery.evaluate_approval_recovery",
        evaluate,
    )

    outcome = resolve_direct_approval(
        DirectApprovalRequest(
            selector=str(plan), kind="commit", kind_explicit=True, project="demo"
        )
    )

    assert isinstance(outcome, DirectApprovalRefusal)
    assert outcome.code == "conflict_already_handled"
    evaluate.assert_not_called()
