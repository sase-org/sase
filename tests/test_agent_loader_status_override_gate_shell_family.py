"""Guard tests pinning the post-gate-shell family projection contract.

Builds plan/question families from real gate-shell member metadata (a
plan-chain root, a concrete planner member, and a gate member) and asserts
the projection ``_apply_status_overrides`` produces today: the container row
mirrors the gate's status, the planner member stays ``DONE``, and a coder
follow-up after a settled gate still gets its semantic handoff label. See
``plan:202608/status_strip.md``'s ``gate-contract`` phase -- this module is
purely additive; nothing here should require a source change to pass.
"""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models._loaders._meta_enrichment_wire import (
    enrich_agent_from_meta_wire,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides
from sase.agent.status_buckets import agent_status_bucket
from sase.core.agent_scan_wire import (
    AgentMetaWire,
    FamilyShellGateWire,
    FamilyShellWire,
)

_FAMILY = "alpha"
_ROOT_SUFFIX = "20260812090000"
_ROOT_START = datetime(2026, 8, 12, 9, 0, 0)
_GATE_SUFFIX = "20260812090500"
_GATE_START = datetime(2026, 8, 12, 9, 5, 0)
_CODE_SUFFIX = "20260812091000"
_CODE_START = datetime(2026, 8, 12, 9, 10, 0)
_PLAN_TIME = datetime(2026, 8, 12, 9, 3, 0)


def _root(*, plan_action: str | None = None) -> Agent:
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name=_FAMILY,
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=_ROOT_START,
        run_start_time=_ROOT_START,
        raw_suffix=_ROOT_SUFFIX,
        role_suffix="-plan",
        agent_name=_FAMILY,
        agent_family=_FAMILY,
        agent_family_role="root",
        plan_chain_root=True,
        plan_action=plan_action,
    )


def _planner_step(
    *,
    plan_action: str | None = "tale",
    plan_times: list[datetime] | None = None,
    gate_id: str | None = "g123",
) -> Agent:
    """The concrete main workflow step that submitted the family's plan."""
    if plan_times is None:
        plan_times = [_PLAN_TIME]
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="main",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=_ROOT_START,
        run_start_time=_ROOT_START,
        parent_workflow="ace-run",
        parent_timestamp=_ROOT_SUFFIX,
        step_type="agent",
        role_suffix="-plan",
        agent_name=f"{_FAMILY}--0",
        agent_family=_FAMILY,
        agent_family_role="plan",
        plan_action=plan_action,
        plan_times=plan_times,
        gate_id=gate_id,
    )


def _gate_member(
    *,
    state: str,
    start_status: str,
    stop_status: str,
    gate_id: str = "g123",
    accent: str = "#FF87AF",
    kind: str = "approval",
) -> Agent:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"{_FAMILY}--gate",
        project_file="/tmp/test.sase",
        status="STARTING",
        start_time=_GATE_START,
        raw_suffix=_GATE_SUFFIX,
        parent_timestamp=_ROOT_SUFFIX,
        role_suffix="--gate",
    )
    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(
            name=f"{_FAMILY}--gate",
            family_shell=FamilyShellWire(
                kind="gate",
                id=gate_id,
                state=state,
                start_status=start_status,
                stop_status=stop_status,
                gate=FamilyShellGateWire(kind=kind, accent=accent),
            ),
            agent_family=_FAMILY,
            agent_family_role="gate",
            role_suffix="--gate",
        ),
        waiting=None,
    )
    return agent


def _coder(*, status: str) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"{_FAMILY}--code",
        project_file="/tmp/test.sase",
        status=status,
        start_time=_CODE_START,
        run_start_time=_CODE_START,
        raw_suffix=_CODE_SUFFIX,
        parent_timestamp=_ROOT_SUFFIX,
        role_suffix="--code",
        agent_name=f"{_FAMILY}--code",
        agent_family=_FAMILY,
        agent_family_role="code",
    )


def test_pending_tale_gate_projects_tale_and_mirrors_gate_pair_onto_container() -> None:
    root = _root()
    planner = _planner_step()
    gate = _gate_member(
        state="pending", start_status="TALE", stop_status="TALE APPROVED"
    )

    _apply_status_overrides([root, gate], [planner])

    assert root.status == "TALE"
    assert gate.status == "TALE"
    assert planner.status == "DONE"
    assert root.gate_start_status == gate.gate_start_status == "TALE"
    assert root.gate_stop_status == gate.gate_stop_status == "TALE APPROVED"
    assert root.gate_state == gate.gate_state == "pending"
    assert root.gate_accent == gate.gate_accent == "#FF87AF"


def test_pending_epic_gate_projects_epic_onto_container() -> None:
    root = _root()
    planner = _planner_step()
    gate = _gate_member(
        state="pending",
        start_status="EPIC",
        stop_status="EPIC APPROVED",
        accent="#D787FF",
    )

    _apply_status_overrides([root, gate], [planner])

    assert root.status == "EPIC"
    assert gate.status == "EPIC"
    assert planner.status == "DONE"


def test_pending_question_gate_projects_question_onto_container() -> None:
    root = _root()
    planner = _planner_step()
    gate = _gate_member(
        state="pending",
        start_status="QUESTION",
        stop_status="ANSWERED",
        accent="#5FD7FF",
        kind="question",
    )

    _apply_status_overrides([root, gate], [planner])

    assert root.status == "QUESTION"
    assert gate.status == "QUESTION"
    assert planner.status == "DONE"


def test_settled_approve_and_commit_gate_projects_tale_approved() -> None:
    root = _root()
    planner = _planner_step()
    gate = _gate_member(
        state="answered", start_status="TALE", stop_status="TALE APPROVED"
    )

    _apply_status_overrides([root, gate], [planner])

    assert root.status == "TALE APPROVED"
    assert gate.status == "TALE APPROVED"
    assert planner.status == "DONE"
    assert root.gate_start_status == gate.gate_start_status == "TALE"
    assert root.gate_stop_status == gate.gate_stop_status == "TALE APPROVED"
    assert root.gate_state == gate.gate_state == "answered"
    assert root.gate_accent == gate.gate_accent
    assert agent_status_bucket(root) == "Running"


def test_settled_approve_gate_projects_plan_approved() -> None:
    root = _root()
    planner = _planner_step(plan_action="approve")
    gate = _gate_member(
        state="answered", start_status="PLAN", stop_status="PLAN APPROVED"
    )

    _apply_status_overrides([root, gate], [planner])

    assert root.status == "PLAN APPROVED"
    assert gate.status == "PLAN APPROVED"
    assert planner.status == "DONE"


def test_pending_tale_gate_with_early_approval_metadata_keeps_planner_done() -> None:
    root = _root()
    planner = _planner_step(plan_action="tale")
    gate = _gate_member(
        state="pending", start_status="TALE", stop_status="TALE APPROVED"
    )

    _apply_status_overrides([root, gate], [planner])

    assert root.status == "TALE"
    assert gate.status == "TALE"
    assert planner.status == "DONE"


def test_legacy_planner_without_gate_id_keeps_sticky_tale_approval() -> None:
    root = _root()
    planner = _planner_step(plan_action="tale", gate_id=None)

    _apply_status_overrides([root], [planner])

    assert planner.status == "TALE APPROVED"


def test_settled_reject_gate_projects_plan_rejected() -> None:
    root = _root()
    planner = _planner_step()
    gate = _gate_member(
        state="answered", start_status="TALE", stop_status="PLAN REJECTED"
    )

    _apply_status_overrides([root, gate], [planner])

    assert root.status == "PLAN REJECTED"
    assert gate.status == "PLAN REJECTED"
    assert planner.status == "DONE"


def test_settled_feedback_gate_projects_feedback() -> None:
    root = _root()
    planner = _planner_step()
    gate = _gate_member(state="answered", start_status="TALE", stop_status="FEEDBACK")

    _apply_status_overrides([root, gate], [planner])

    assert root.status == "FEEDBACK"
    assert gate.status == "FEEDBACK"
    assert planner.status == "DONE"


def test_settled_question_gate_projects_answered() -> None:
    root = _root()
    planner = _planner_step()
    gate = _gate_member(
        state="answered",
        start_status="QUESTION",
        stop_status="ANSWERED",
        kind="question",
    )

    _apply_status_overrides([root, gate], [planner])

    assert root.status == "ANSWERED"
    assert gate.status == "ANSWERED"
    assert planner.status == "DONE"


def test_settled_gate_with_running_coder_is_working_tale() -> None:
    """R-1's guard: deleting active_approved_plan_handoff_status regresses this."""
    root = _root(plan_action="tale")
    planner = _planner_step()
    gate = _gate_member(
        state="answered", start_status="TALE", stop_status="TALE APPROVED"
    )
    coder = _coder(status="RUNNING")

    _apply_status_overrides([root, gate, coder], [planner])

    assert root.status == "WORKING TALE"
    assert coder.status == "WORKING TALE"


def test_settled_gate_with_completed_coder_is_tale_done() -> None:
    """Guard for is_completed_plan_handoff_child / done_handoff_status."""
    root = _root(plan_action="tale")
    planner = _planner_step()
    gate = _gate_member(
        state="answered", start_status="TALE", stop_status="TALE APPROVED"
    )
    coder = _coder(status="DONE")

    _apply_status_overrides([root, gate, coder], [planner])

    assert root.status == "TALE DONE"
    assert coder.status == "TALE DONE"
