"""Unit tests for the pure Node Finder row model."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.node_finder import (
    NODE_FINDER_HINT_CAPACITY,
    NodeFinderReason,
    NodeFinderRole,
    NodeFinderRow,
    NodeFinderSnapshot,
    filter_node_finder,
    next_jumpable_index,
    node_finder_action_text,
    node_finder_glyph,
    node_finder_jumpable,
    node_finder_kind,
    node_finder_name,
    node_finder_reason_text,
    node_finder_title,
)
from sase.ace.tui.widgets.prompt_panel._identity_header import (
    identity_kind_for_agent,
)
from tests.ace.tui._member_jump_navigation_helpers import make_agent, make_agent_session


def _started() -> datetime:
    return datetime(2026, 7, 18, 12, 0, 0)


def _node(
    name: str,
    *,
    title: str = "",
    pos: int = 0,
    parent: int | None = None,
    jumpable: bool = True,
    identity: object = None,
) -> NodeFinderRow:
    return NodeFinderRow(
        role=NodeFinderRole.NODE,
        identity=identity if identity is not None else ("test", name, None),
        name=name,
        title=title,
        kind_label="AGENT",
        kind_accent="#87AFFF",
        depth=1,
        panel_key=None,
        parent_row=parent,
        jumpable=jumpable,
    )


def _snapshot(*rows: NodeFinderRow, here: int | None = None) -> NodeFinderSnapshot:
    fixed = tuple(
        NodeFinderRow(
            role=row.role,
            identity=row.identity,
            agent=row.agent,
            name=row.name,
            title=row.title,
            kind_label=row.kind_label,
            kind_accent=row.kind_accent,
            depth=row.depth,
            panel_key=row.panel_key,
            parent_row=row.parent_row,
            jumpable=row.jumpable,
            reasons=row.reasons,
            unmet_fold_count=row.unmet_fold_count,
            nearest_collapsed=row.nearest_collapsed,
            group_label=row.group_label,
            is_here=(pos == here),
        )
        for pos, row in enumerate(rows)
    )
    jumpable_count = sum(1 for row in fixed if row.jumpable)
    return NodeFinderSnapshot(
        rows=fixed,
        here_row=here,
        node_count=jumpable_count,
        hint_overflow=jumpable_count > NODE_FINDER_HINT_CAPACITY,
    )


def _workflow_step(
    step_type: str, *, pre_prompt: bool = False, hidden: bool = False
) -> Agent:
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="wf-step",
        project_file="/repos/demo/project.sase",
        status="DONE",
        start_time=_started(),
        raw_suffix="ts-wf-step",
        parent_workflow="myflow",
        parent_timestamp="ts-wf",
        step_name=f"the-{step_type}-step",
        step_type=step_type,
        step_index=0,
        total_steps=1,
        is_pre_prompt_step=pre_prompt,
        is_hidden_step=hidden,
    )


def test_name_mirrors_agents_row_across_kinds() -> None:
    clan_member = make_agent("member-0", clan="research")
    (container,) = project_clan_tree([clan_member])[:1]
    assert container.is_clan_container
    assert node_finder_name(container) == "research"

    session = make_agent("alpha--plan", session="alpha", role="plan")
    # Presented session base name wins per the naming formula.
    assert node_finder_name(session) == session.presented_agent_name == "alpha"

    shell = make_agent("sess--code", session="sess", role="code")
    assert node_finder_name(shell) == "sess--code"

    monitor = make_agent("sess--mon-1", session="sess", role="monitor")
    assert node_finder_name(monitor) == "sess--mon-1"

    gate = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="g",
        project_file="/p/p.sase",
        status="RUNNING",
        start_time=_started(),
        raw_suffix="ts-g",
        agent_name="g",
        agent_session_role="gate",
        gate_id="g1",
        role_suffix="--gate",
    )
    assert gate.is_gate
    assert node_finder_name(gate) == "g"

    proc = Agent(
        agent_type=AgentType.PROC_SHELL,
        cl_name="p",
        project_file="/p/p.sase",
        status="RUNNING",
        start_time=_started(),
        raw_suffix="ts-proc",
        proc_label="my proc",
    )
    assert node_finder_name(proc) == "my proc"

    assert node_finder_name(make_agent("plain")) == "plain"


def test_title_returned_only_when_it_differs() -> None:
    plain = make_agent("plain")
    # display_name ("jump-test") differs from the name, so it is kept.
    assert node_finder_title(plain) == "jump-test"
    _, _, session_child = make_agent_session(in_clan=False)
    assert session_child.is_agent_session_member_child
    assert node_finder_title(session_child) is None
    step = _workflow_step("bash")
    assert node_finder_title(step) == "the-bash-step"


def test_kind_delegates_with_clan_special_case() -> None:
    clan_member = make_agent("member-0", clan="research")
    (container,) = project_clan_tree([clan_member])[:1]
    assert node_finder_kind(container) == ("CLAN", "#D75FFF")

    _, session_root, _ = make_agent_session(in_clan=False)
    assert session_root.is_agent_session_container_row
    assert node_finder_kind(session_root)[0] == "SESSION"
    monitor = make_agent("sess--mon-1", session="sess", role="monitor")
    assert node_finder_kind(monitor) == identity_kind_for_agent(monitor)
    assert node_finder_kind(monitor)[0] == "MONITOR"
    agent_step = _workflow_step("agent")
    assert node_finder_kind(agent_step)[0] == "AGENT SHELL"
    bash_step = _workflow_step("bash")
    assert node_finder_kind(bash_step) == identity_kind_for_agent(bash_step)
    assert node_finder_kind(bash_step)[0] == "STEP"
    assert node_finder_kind(make_agent("plain")) == identity_kind_for_agent(
        make_agent("plain")
    )


def test_jumpability_excludes_non_agent_steps() -> None:
    assert node_finder_jumpable(make_agent("plain"))
    assert node_finder_jumpable(_workflow_step("agent"))
    assert not node_finder_jumpable(_workflow_step("bash"))
    assert not node_finder_jumpable(_workflow_step("python"))
    assert not node_finder_jumpable(_workflow_step("parallel"))
    assert not node_finder_jumpable(_workflow_step("quantum"))
    assert not node_finder_jumpable(_workflow_step("agent", pre_prompt=True))
    assert not node_finder_jumpable(_workflow_step("python", pre_prompt=True))


def test_glyph_precedence_query_over_fold() -> None:
    row = _node("x")
    assert node_finder_glyph(row) == ""
    folded = NodeFinderRow(
        role=row.role,
        identity=row.identity,
        name=row.name,
        jumpable=True,
        reasons=frozenset({NodeFinderReason.FOLDED}),
    )
    assert node_finder_glyph(folded) == "▸"
    both = NodeFinderRow(
        role=row.role,
        identity=row.identity,
        name=row.name,
        jumpable=True,
        reasons=frozenset({NodeFinderReason.FOLDED, NodeFinderReason.QUERY}),
    )
    assert node_finder_glyph(both) == "⊘"
    here = NodeFinderRow(
        role=row.role,
        identity=row.identity,
        name=row.name,
        jumpable=True,
        reasons=frozenset({NodeFinderReason.FOLDED}),
        is_here=True,
    )
    assert node_finder_glyph(here) == "◆"


def test_filter_token_and_and_empty_query() -> None:
    snap = _snapshot(
        _node("sase", pos=0),
        _node("bob-cli", pos=1),
        _node("research.8.cdx", pos=2),
        _node("research.8.cld", pos=3),
    )
    view = filter_node_finder(snap, "")
    assert [row.name for row in view.rows] == [
        "sase",
        "bob-cli",
        "research.8.cdx",
        "research.8.cld",
    ]
    assert not view.relaxed
    assert view.best_index == 0
    assert len(view.hint_to_identity) == 4

    view = filter_node_finder(snap, "cdx")
    assert [row.name for row in view.rows] == ["research.8.cdx"]
    assert not view.relaxed
    assert view.rows[view.best_index or 0].name == "research.8.cdx"

    view = filter_node_finder(snap, "research cdx")
    assert [row.name for row in view.rows] == ["research.8.cdx"]

    view = filter_node_finder(snap, "zzz")
    assert view.rows == ()
    assert view.best_index is None


def test_filter_relaxed_fallback_and_ranking() -> None:
    snap = _snapshot(
        _node("research.8.cdx", pos=0),
        _node("research.8.cld", pos=1),
        _node("bob-cli", pos=2),
    )
    view = filter_node_finder(snap, "r8c")
    assert view.relaxed
    assert [row.name for row in view.rows] == [
        "research.8.cdx",
        "research.8.cld",
    ]
    # Deterministic ranking: same tier, higher score, then display order.
    assert view.best_index == 0

    contiguous = filter_node_finder(snap, "research")
    assert not contiguous.relaxed
    assert len(contiguous.rows) == 2


def test_filter_prefers_name_over_title() -> None:
    snap = _snapshot(
        _node("xyz", title="research notes", pos=0),
        _node("researcher", pos=1),
    )
    view = filter_node_finder(snap, "research")
    assert [row.name for row in view.rows] == ["xyz", "researcher"]
    assert view.best_index == 1


def test_filter_keeps_ancestors_and_headers_as_context() -> None:
    panel = NodeFinderRow(role=NodeFinderRole.PANEL, depth=0)
    group = NodeFinderRow(
        role=NodeFinderRole.GROUP,
        depth=1,
        parent_row=0,
        group_label="demo",
    )
    snap = _snapshot(
        panel,
        group,
        _node("research.8.cdx", pos=2, parent=1),
        _node("bob-cli", pos=3, parent=1),
        here=None,
    )
    view = filter_node_finder(snap, "cdx")
    assert [row.name for row in view.rows] == ["", "", "research.8.cdx"]
    assert view.context == {0, 1}
    assert view.best_index == 2
    assert list(view.hint_to_identity.values()) == [("test", "research.8.cdx", None)]


def test_filter_incremental_narrowing_equals_full_eval() -> None:
    snap = _snapshot(
        _node("research.8.cdx", pos=0),
        _node("research.8.cld", pos=1),
        _node("bob-cli", pos=2),
    )
    first = filter_node_finder(snap, "researc")
    narrowed = filter_node_finder(snap, "research", previous=first)
    full = filter_node_finder(snap, "research")
    assert [row.name for row in narrowed.rows] == [row.name for row in full.rows]
    assert narrowed.best_index == full.best_index
    assert narrowed.relaxed == full.relaxed

    appended = filter_node_finder(snap, "research cdx", previous=full)
    appended_full = filter_node_finder(snap, "research cdx")
    assert [row.name for row in appended.rows] == [
        row.name for row in appended_full.rows
    ]


def _hint_snapshot(count: int) -> NodeFinderSnapshot:
    return _snapshot(*(_node(f"node-{index:04d}", pos=index) for index in range(count)))


@pytest.mark.parametrize("count", [61, 62, 63])
def test_hint_prefix_free_boundaries(count: int) -> None:
    view = filter_node_finder(_hint_snapshot(count), "")
    assert len(view.hint_to_identity) == count
    assert not view.overflow
    hints = list(view.hint_to_identity)
    assert len(set(hints)) == count
    # Prefix-free: no hint is a proper prefix of another.
    assert not any(
        first != second and second.startswith(first)
        for first in hints
        for second in hints
    )
    if count <= 62:
        assert all(len(hint) == 1 for hint in hints)
    else:
        assert sum(1 for hint in hints if len(hint) == 1) == 61
        assert sum(1 for hint in hints if len(hint) == 2) == 2
        assert "Z" not in hints


def test_hint_overflow_past_capacity() -> None:
    view = filter_node_finder(_hint_snapshot(NODE_FINDER_HINT_CAPACITY), "")
    assert len(view.hint_to_identity) == NODE_FINDER_HINT_CAPACITY
    assert not view.overflow

    over = filter_node_finder(_hint_snapshot(NODE_FINDER_HINT_CAPACITY + 10), "")
    assert len(over.hint_to_identity) == NODE_FINDER_HINT_CAPACITY
    assert over.overflow
    hinted = set(over.hint_to_identity.values())
    assert ("test", f"node-{NODE_FINDER_HINT_CAPACITY:04d}", None) not in hinted
    assert ("test", "node-0000", None) in hinted


def test_cursor_wraps_and_skips_context() -> None:
    panel = NodeFinderRow(role=NodeFinderRole.PANEL, depth=0)
    snap = _snapshot(
        panel, _node("aaa", pos=1, parent=0), _node("zzz", pos=2, parent=0)
    )
    view = filter_node_finder(snap, "aaa")
    # Rows: [panel(context), aaa]; zzz filtered out.
    assert next_jumpable_index(view, 1, 1) == 1
    assert next_jumpable_index(view, 1, -1) == 1

    full = filter_node_finder(snap, "")
    assert next_jumpable_index(full, 1, 1) == 2
    assert next_jumpable_index(full, 2, 1) == 1
    assert next_jumpable_index(full, 1, -1) == 2
    assert next_jumpable_index(full, 0, 1) == 1


def test_reason_and_action_wording() -> None:
    base = _node("research.8.cdx")
    assert node_finder_reason_text(base, "q") == ""
    assert node_finder_action_text(base, "q") == "⏎ selects it"

    here = NodeFinderRow(
        role=base.role,
        identity=base.identity,
        name=base.name,
        jumpable=True,
        is_here=True,
    )
    assert node_finder_reason_text(here, "q") == "◆ You are here"

    folded = NodeFinderRow(
        role=base.role,
        identity=base.identity,
        name=base.name,
        jumpable=True,
        reasons=frozenset({NodeFinderReason.FOLDED}),
        unmet_fold_count=2,
        nearest_collapsed="clan research.8",
    )
    assert node_finder_reason_text(folded, "q") == "▸ Inside collapsed clan research.8"
    assert node_finder_action_text(folded, "q") == "⏎ expands 2 folds, then selects it"

    banner = NodeFinderRow(
        role=base.role,
        identity=base.identity,
        name=base.name,
        jumpable=True,
        reasons=frozenset({NodeFinderReason.BANNER}),
        group_label="demo",
    )
    assert node_finder_reason_text(banner, "q") == "≡ Inside collapsed group demo"
    assert node_finder_action_text(banner, "q") == "⏎ opens its group, then selects it"

    panel_row = NodeFinderRow(
        role=base.role,
        identity=base.identity,
        name=base.name,
        jumpable=True,
        reasons=frozenset({NodeFinderReason.PANEL}),
        panel_key="research",
    )
    assert node_finder_reason_text(panel_row, "q") == "▭ Inside hidden panel @research"
    assert (
        node_finder_action_text(panel_row, "q") == "⏎ opens @research, then selects it"
    )

    queried = NodeFinderRow(
        role=base.role,
        identity=base.identity,
        name=base.name,
        jumpable=True,
        reasons=frozenset({NodeFinderReason.QUERY}),
    )
    assert (
        node_finder_reason_text(queried, "my query")
        == "⊘ Hidden by the Agents query ‹my query›"
    )
    assert (
        node_finder_action_text(queried, "my query")
        == "⏎ clears the Agents query, then selects it"
    )

    combined = NodeFinderRow(
        role=base.role,
        identity=base.identity,
        name=base.name,
        jumpable=True,
        reasons=frozenset({NodeFinderReason.QUERY, NodeFinderReason.FOLDED}),
        unmet_fold_count=1,
        nearest_collapsed="clan research.8",
    )
    assert (
        node_finder_action_text(combined, "q")
        == "⏎ clears the Agents query, expands 1 fold, then selects it"
    )
    reason = node_finder_reason_text(combined, "q")
    assert "⊘ Hidden by the Agents query ‹q›" in reason
    assert "▸ Inside collapsed clan research.8" in reason
