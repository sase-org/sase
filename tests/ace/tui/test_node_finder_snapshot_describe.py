"""Row-describer snapshot tests for the Node Finder row model."""

from __future__ import annotations

from sase.ace.tui.models.agent import Agent, AgentType
from tests.ace.tui._member_jump_navigation_helpers import (
    make_agent,
    make_agent_session,
    make_clan,
)
from tests.ace.tui._node_finder_snapshot_shared import snapshot_started

__all__ = [
    "test_batched_description_matches_single_row",
    "test_plain_row_describer_matches_single_row",
]


def _describe_shapes() -> list[Agent]:
    """Return one agent per row shape the batched describer must match."""
    started = snapshot_started()
    clan_members, _container = make_clan(2)
    clan_row = next(agent for agent in clan_members if agent.is_clan_container)
    _sess_proj, sess_root, _sess_child = make_agent_session(in_clan=False)
    session_row = sess_root
    wf_root = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="wf",
        project_file="/p/p.sase",
        status="RUNNING",
        start_time=started,
        raw_suffix="ts-wf",
        agent_name="wf",
        workflow="myflow",
    )
    wf_step = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="x",
        project_file="/p/p.sase",
        status="DONE",
        start_time=started,
        raw_suffix="ts-wf-step",
        parent_workflow="myflow",
        parent_timestamp="ts-wf",
        step_name="build",
        step_type="bash",
        step_index=0,
        total_steps=1,
        role_suffix="--build",
    )
    hidden_step = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="hs",
        project_file="/p/p.sase",
        status="DONE",
        start_time=started,
        raw_suffix="ts-hidden-step",
        parent_workflow="hidden-flow",
        parent_timestamp="ts-hidden-root",
        step_name="setup",
        step_type="python",
        step_index=0,
        total_steps=1,
        is_hidden_step=True,
        role_suffix="--setup",
    )
    proc = Agent(
        agent_type=AgentType.NAMED_PROC,
        cl_name="proc",
        project_file="/p/p.sase",
        status="RUNNING",
        start_time=started,
        raw_suffix="ts-proc",
        agent_name="named-proc",
        proc_label="shell",
        proc_safe_preview="echo hi",
        proc_id="proc-1",
    )
    gate = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="fam--gate",
        project_file="/p/p.sase",
        status="RUNNING",
        start_time=started,
        raw_suffix="ts-gate",
        parent_timestamp="ts-root",
        agent_name="fam--gate",
        agent_session="fam",
        agent_session_role="gate",
        role_suffix="--gate",
        gate_id="g1",
    )
    monitor = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="fam--mon1",
        project_file="/p/p.sase",
        status="MONITORING",
        start_time=started,
        raw_suffix="ts-mon1",
        parent_timestamp="ts-root",
        agent_name="fam--mon1",
        agent_session="fam",
        agent_session_role="monitor",
        role_suffix="--mon1",
        monitor_id="mon-mon1",
    )
    solo = make_agent("solo")
    return [
        clan_row,
        session_row,
        wf_step,
        hidden_step,
        proc,
        gate,
        monitor,
        solo,
        wf_root,
    ]


def test_batched_description_matches_single_row() -> None:
    """The batched describer matches the single-row contract for every shape."""
    from sase.ace.tui.models._node_finder_describe import (
        _describe_node_finder_row_for_snapshot,
    )
    from sase.ace.tui.models.node_finder import (
        describe_node_finder_row,
        describe_node_finder_row_from_facts,
        kind_styles,
    )

    styles = kind_styles()
    for agent in _describe_shapes():
        expected = describe_node_finder_row(agent)
        from_facts = describe_node_finder_row_from_facts(
            is_clan=agent.is_clan_container,
            is_proc=agent.is_named_proc,
            is_wf_step=agent.is_workflow_step_child,
            step_type=agent.step_type,
            presented=agent.presented_agent_name,
            agent_name=agent.agent_name,
            display_name=agent.display_name,
            cl_name=agent.cl_name,
            is_session_container=agent.is_agent_session_container_row,
            is_monitor=agent.is_monitor,
            is_gate=agent.is_gate,
            is_agent_entry=agent.is_agent_entry,
            agent_clan=agent.agent_clan,
            proc_label=agent.proc_label,
            proc_safe_preview=agent.proc_safe_preview,
            step_name=agent.step_name,
            is_session_member_child=agent.is_agent_session_member_child,
            is_pre_prompt_step=agent.is_pre_prompt_step,
            agent_type=agent.agent_type,
            is_workflow_child=agent.is_workflow_child,
            appears_as_agent=agent.appears_as_agent,
            styles=styles,
        )
        assert from_facts == expected, agent.agent_name
        for_snapshot = _describe_node_finder_row_for_snapshot(
            agent,
            is_monitor=agent.is_monitor,
            is_gate=agent.is_gate,
            styles=styles,
        )
        assert for_snapshot == expected, agent.agent_name


def test_plain_row_describer_matches_single_row() -> None:
    """The plain-row fast path matches the single-row contract exactly."""
    from sase.ace.tui.actions.agents._node_finder_facets import _describe_plain_row
    from sase.ace.tui.models.node_finder import (
        describe_node_finder_row,
        kind_styles,
    )

    styles = kind_styles()
    started = snapshot_started()
    presented = make_agent("titled-agent", clan="titled")
    presented.presented_agent_name = "Shown Name"
    pre_prompt = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="preprompt",
        project_file="/p/p.sase",
        status="RUNNING",
        start_time=started,
        raw_suffix="ts-plain-pre",
        agent_name="pre.node",
        is_pre_prompt_step=True,
    )
    shapes = [
        make_agent("plain"),
        make_agent("presented", clan="c1"),
        presented,
        pre_prompt,
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="nameless",
            project_file="/p/p.sase",
            status="RUNNING",
            start_time=started,
            raw_suffix="ts-plain-noname",
            agent_name=None,
        ),
    ]
    for agent in shapes:
        assert not agent.is_clan_container
        assert not agent.is_named_proc
        assert not agent.is_workflow_step_child
        assert not agent.is_agent_session_container_row
        assert not agent.is_monitor
        assert not agent.is_gate
        assert not agent.is_agent_session_member_child
        assert agent.agent_type is AgentType.RUNNING
        expected = describe_node_finder_row(agent)
        fast = _describe_plain_row(
            agent.presented_agent_name,
            agent.agent_name,
            agent.display_name,
            agent.cl_name,
            agent.is_pre_prompt_step,
            styles,
        )
        assert fast == expected, agent.agent_name
