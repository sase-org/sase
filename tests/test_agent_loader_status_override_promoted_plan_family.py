"""Tests for status projection onto promoted (rename-on-attach) plan families.

Covers the ``pv`` family bug: a root promoted to ``--0`` before any plan
existed (``plan_chain_root=False``) whose plan chain only started later in a
family-member continuation. The root's durable metadata stays accurate but
stale; the plan-family projection must be derived from the member instead.
"""

from datetime import datetime

from sase.ace.tui.models._agent_status_family import is_root_plan_workflow
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides

_ROOT_SUFFIX = "20260731065155"
_ROOT_START = datetime(2026, 7, 31, 6, 51, 55)
_QUESTION_TIME = datetime(2026, 7, 31, 6, 54, 20)
_MEMBER_SUFFIX = "20260731065616"
_MEMBER_START = datetime(2026, 7, 31, 6, 56, 16)
_PLAN_TIME = datetime(2026, 7, 31, 7, 0, 39)
_CODE_SUFFIX = "20260731070200"
_CODE_START = datetime(2026, 7, 31, 7, 2, 0)


def _promoted_family(
    *,
    plan_action: str | None = None,
    plan_path: str | None = None,
    coder_status: str | None = None,
) -> tuple[Agent, Agent, Agent, Agent | None]:
    """Build the promoted ``pv`` family shape from the bug reproduction.

    ``root`` was launched as a plain agent, asked a question, and was
    promoted to ``--0`` (``plan_chain_root=False``) before ever planning.
    ``main_step`` is its own concrete workflow step. ``member`` is the
    continuation that later submitted a plan under the rewritten ``--plan``
    role suffix while its stored family role did not change.
    """
    root = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="pv",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=_ROOT_START,
        run_start_time=_ROOT_START,
        raw_suffix=_ROOT_SUFFIX,
        role_suffix="--0",
        agent_name="pv",
        agent_family="pv",
        agent_family_role="root",
        plan_chain_root=False,
        questions_times=[_QUESTION_TIME],
        question_response_path="/tmp/question_response.json",
    )
    main_step = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="main",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=_ROOT_START,
        run_start_time=_ROOT_START,
        raw_suffix=_ROOT_SUFFIX,
        parent_workflow="ace-run",
        parent_timestamp=_ROOT_SUFFIX,
        step_type="agent",
        role_suffix="--0",
        agent_name="pv--0",
        agent_family="pv",
        questions_times=[_QUESTION_TIME],
        question_response_path="/tmp/question_response.json",
    )
    member = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="pv",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=_MEMBER_START,
        run_start_time=_MEMBER_START,
        raw_suffix=_MEMBER_SUFFIX,
        parent_timestamp=_ROOT_SUFFIX,
        role_suffix="--plan",
        agent_name="pv--1",
        agent_family="pv",
        agent_family_role="agent",
        questions_times=[_QUESTION_TIME],
        plan_times=[_PLAN_TIME],
        plan_action=plan_action,
        plan_path=plan_path,
    )
    coder = None
    if coder_status is not None:
        coder = Agent(
            agent_type=AgentType.RUNNING,
            cl_name="pv",
            project_file="/tmp/test.sase",
            status=coder_status,
            start_time=_CODE_START,
            run_start_time=_CODE_START,
            raw_suffix=_CODE_SUFFIX,
            parent_timestamp=_ROOT_SUFFIX,
            role_suffix="--code",
            agent_name="pv--code",
            agent_family="pv",
            agent_family_role="code",
        )
    return root, main_step, member, coder


def test_promoted_family_unreviewed_member_without_gate_stays_done() -> None:
    """A promoted root whose member submitted a plan no longer reconstructs TALE.

    Also covers plan_times isolation: the root must not borrow the member's
    plan_times. ``main_step`` (the root's own concrete workflow step) keeps
    its raw DONE status rather than mirroring ANSWERED, since that mirror was
    owned by the retired synthetic planner path.
    """
    root, main_step, member, _ = _promoted_family()

    _apply_status_overrides([root, member], [main_step])

    assert root.status == "DONE"
    assert main_step.status == "DONE"
    assert member.status == "DONE"
    assert root.plan_times == []


def test_promoted_family_tale_approved_coder_running_is_working_tale() -> None:
    """An approved tale with an active coder mirrors WORKING TALE onto the root."""
    root, main_step, member, coder = _promoted_family(
        plan_action="tale", coder_status="RUNNING"
    )
    assert coder is not None

    _apply_status_overrides([root, member, coder], [main_step])

    assert root.status == "WORKING TALE"
    assert coder.status == "WORKING TALE"
    assert member.status == "TALE APPROVED"


def test_promoted_family_tale_approved_coder_done_is_tale_done() -> None:
    """A finished coder mirrors TALE DONE onto the root, not plain DONE."""
    root, main_step, member, coder = _promoted_family(
        plan_action="tale", coder_status="DONE"
    )
    assert coder is not None

    _apply_status_overrides([root, member, coder], [main_step])

    assert root.status == "TALE DONE"
    assert coder.status == "TALE DONE"
    assert member.status == "TALE APPROVED"


def test_promoted_family_approved_plan_action_is_not_hardcoded_tale() -> None:
    """A generic approval still yields plan-specific handoff labels."""
    root, main_step, member, coder = _promoted_family(
        plan_action="approve", coder_status="RUNNING"
    )
    assert coder is not None
    _apply_status_overrides([root, member, coder], [main_step])
    assert member.status == "PLAN APPROVED"
    assert coder.status == "WORKING PLAN"
    assert root.status == "WORKING PLAN"

    root, main_step, member, coder = _promoted_family(
        plan_action="approve", coder_status="DONE"
    )
    assert coder is not None
    _apply_status_overrides([root, member, coder], [main_step])
    assert member.status == "PLAN APPROVED"
    assert coder.status == "PLAN DONE"
    assert root.status == "PLAN DONE"


def test_promoted_family_plain_question_continuation_is_unaffected() -> None:
    """A promoted root with only a plain question continuation is untouched.

    No ``--plan``/``--code`` suffix and no submitted plan means the family
    never entered a plan chain, so today's plain-question-family behavior
    (root keeps its own terminal status, no synthetic planner) must hold.
    """
    root = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="pv",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=_ROOT_START,
        run_start_time=_ROOT_START,
        raw_suffix=_ROOT_SUFFIX,
        role_suffix="--0",
        agent_name="pv",
        agent_family="pv",
        agent_family_role="root",
        plan_chain_root=False,
        questions_times=[_QUESTION_TIME],
        question_response_path="/tmp/question_response.json",
    )
    main_step = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="main",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=_ROOT_START,
        run_start_time=_ROOT_START,
        raw_suffix=_ROOT_SUFFIX,
        parent_workflow="ace-run",
        parent_timestamp=_ROOT_SUFFIX,
        step_type="agent",
        role_suffix="--0",
        agent_name="pv--0",
        agent_family="pv",
        questions_times=[_QUESTION_TIME],
        question_response_path="/tmp/question_response.json",
    )
    continuation = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="pv",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=_MEMBER_START,
        run_start_time=_MEMBER_START,
        raw_suffix=_MEMBER_SUFFIX,
        parent_timestamp=_ROOT_SUFFIX,
        role_suffix="--1",
        agent_name="pv--1",
        agent_family="pv",
        agent_family_role="agent",
        questions_times=[_QUESTION_TIME],
        question_response_path="/tmp/question_response.json",
    )
    agents = [root, continuation]

    _apply_status_overrides(agents, [main_step])

    assert root.status == "DONE"
    assert not is_root_plan_workflow(root)


def test_promoted_family_derived_marker_survives_partial_reload() -> None:
    """A later pass over just the root must not un-recognize it as a plan family."""
    root, main_step, member, _ = _promoted_family()

    _apply_status_overrides([root, member], [main_step])
    assert root.derived_plan_family_root is True

    _apply_status_overrides([root])

    assert root.derived_plan_family_root is True
    assert is_root_plan_workflow(root)
