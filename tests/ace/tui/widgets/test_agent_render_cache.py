"""Tests for per-row render cache hits and invalidation."""

from __future__ import annotations

from sase.ace.tui.models._agent_tree import agent_fold_key
from sase.ace.tui.agent_completion import (
    WaitAgentStatusCounts,
    WaitBeadStatusCounts,
    WaitDependencyStatusCounts,
)
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_status import RUNNING_COLOR
from sase.ace.tui.widgets.agent_list import _compute_fold_annotation
from sase.ace.tui.widgets._agent_list_rendering import (
    AgentRenderCache,
    cached_format_agent_option,
    format_agent_option,
)
from sase.ace.tui.widgets._agent_list_styling import _FOLD_RESTORE_GLYPH_STYLE

from ._agent_render_cache_helpers import agent as _agent
from ._agent_render_cache_helpers import style_at as _style_at


def test_cached_format_agent_option_reuses_result_on_repeat_call() -> None:
    cache = AgentRenderCache()
    a = _agent()
    parts1 = cached_format_agent_option(cache, a, 0, is_selected=False, now=None)
    parts2 = cached_format_agent_option(cache, a, 0, is_selected=False, now=None)
    # Same identity returned: cache hit reuses the Text triple.
    assert parts1[0] is parts2[0]
    assert parts1[1] is parts2[1]
    assert parts1[2] == parts2[2]


def test_cached_format_agent_option_invalidates_on_field_change() -> None:
    cache = AgentRenderCache()
    a = _agent(approve=False)
    parts_before = cached_format_agent_option(cache, a, 0, is_selected=False, now=None)
    a.approve = True
    parts_after = cached_format_agent_option(cache, a, 0, is_selected=False, now=None)
    # Different cache key -> different cached entry -> different Text instance.
    assert parts_before[0] is not parts_after[0]


def test_running_status_uses_shared_running_color() -> None:
    rendered, _, _ = format_agent_option(
        _agent(status="RUNNING"),
        0,
        is_selected=False,
    )

    assert _style_at(rendered, rendered.plain.index("RUNNING")) == (
        f"bold {RUNNING_COLOR}"
    )


def test_format_agent_option_appends_fold_restore_marker_with_shared_gold() -> None:
    rendered, _, _ = format_agent_option(
        _agent(status="RUNNING"),
        0,
        is_selected=False,
        fold_annotation=" ×3",
        fold_restore_marked=True,
    )
    unmarked, _, _ = format_agent_option(
        _agent(status="RUNNING"),
        0,
        is_selected=False,
        fold_annotation=" ×3",
        fold_restore_marked=False,
    )

    assert "×3 ▿" in rendered.plain
    marker_start = rendered.plain.index("▿")
    assert _style_at(rendered, marker_start) == _FOLD_RESTORE_GLYPH_STYLE
    assert "▿" not in unmarked.plain


def test_format_agent_option_marks_anonymous_single_child_lane_without_annotation() -> (
    None
):
    agent = _agent(status="RUNNING")
    agent.agent_type = AgentType.WORKFLOW
    agent.is_anonymous = True
    agent.appears_as_agent = True
    fold_key = agent_fold_key(agent)
    assert fold_key is not None
    annotation = _compute_fold_annotation(agent, {fold_key: (1, 0)}, set(), set())
    assert annotation == ""

    rendered, _, _ = format_agent_option(
        agent,
        0,
        is_selected=False,
        fold_annotation=annotation,
        fold_restore_marked=True,
    )

    assert "×" not in rendered.plain
    assert " ▿" in rendered.plain


def test_cached_format_agent_option_invalidates_on_unread_change() -> None:
    cache = AgentRenderCache()
    a = _agent()
    parts_before = cached_format_agent_option(
        cache, a, 0, is_selected=False, is_unread=False, now=None
    )
    parts_after = cached_format_agent_option(
        cache, a, 0, is_selected=False, is_unread=True, now=None
    )
    assert parts_before[0] is not parts_after[0]
    assert parts_before[1] is not parts_after[1]
    assert "✦" not in parts_before[0].plain
    assert "✦" not in parts_after[0].plain
    assert parts_before[1].plain == ""
    assert parts_after[1].plain == "✅"


def test_cached_format_agent_option_invalidates_on_missing_wait_target_change() -> None:
    cache = AgentRenderCache()
    agent = _agent(status="WAITING")
    agent.waiting_for = ["ghost_deploy"]

    known = cached_format_agent_option(
        cache,
        agent,
        0,
        is_selected=False,
        wait_dependency_counts=WaitDependencyStatusCounts(),
    )
    missing = cached_format_agent_option(
        cache,
        agent,
        0,
        is_selected=False,
        wait_dependency_counts=WaitDependencyStatusCounts(
            agents=WaitAgentStatusCounts(unknown=1)
        ),
    )

    assert known[0] is not missing[0]
    assert known[0].plain.endswith("(WAITING)")
    assert missing[0].plain.endswith("(WAITING ?1)")


def test_cached_format_agent_option_invalidates_on_bead_wait_count_change() -> None:
    cache = AgentRenderCache()
    agent = _agent(status="WAITING")
    agent.waiting_for_beads = ["run-bead"]

    open_counts = cached_format_agent_option(
        cache,
        agent,
        0,
        is_selected=False,
        wait_dependency_counts=WaitDependencyStatusCounts(
            beads=WaitBeadStatusCounts(open=1)
        ),
    )
    closed_counts = cached_format_agent_option(
        cache,
        agent,
        0,
        is_selected=False,
        wait_dependency_counts=WaitDependencyStatusCounts(
            beads=WaitBeadStatusCounts(closed=1)
        ),
    )

    assert open_counts[0] is not closed_counts[0]
    assert open_counts[0].plain.endswith("(WAITING ◆○1)")
    assert closed_counts[0].plain.endswith("(WAITING ◆●1)")


def test_format_agent_option_marks_unresolvable_wait_target_distinctly() -> None:
    agent = _agent(status="WAITING")
    agent.waiting_for = ["@default"]

    rendered, _, _ = format_agent_option(
        agent,
        0,
        is_selected=False,
        has_unresolvable_wait_target=True,
    )

    assert rendered.plain.endswith("(WAITING !)")
    assert "(WAITING ?)" not in rendered.plain


def test_cached_format_agent_option_invalidates_on_unresolvable_wait_flag() -> None:
    cache = AgentRenderCache()
    agent = _agent(status="WAITING")
    agent.waiting_for = ["@default"]

    pending = cached_format_agent_option(
        cache,
        agent,
        0,
        is_selected=False,
        has_unresolvable_wait_target=False,
    )
    unresolvable = cached_format_agent_option(
        cache,
        agent,
        0,
        is_selected=False,
        has_unresolvable_wait_target=True,
    )

    assert pending[0] is not unresolvable[0]
    assert pending[0].plain.endswith("(WAITING)")
    assert unresolvable[0].plain.endswith("(WAITING !)")


def test_cached_family_root_invalidates_when_first_real_member_is_added() -> None:
    cache = AgentRenderCache()
    root = _agent(agent_name="demo")
    root.agent_family = "demo"
    root.agent_family_role = "root"
    synthetic = _agent(
        cl_name="demo--plan",
        agent_name="demo--plan",
        raw_suffix="20260425143001",
    )
    synthetic.is_synthetic_planner = True
    root.followup_agents = [synthetic]

    before = cached_format_agent_option(cache, root, 0, is_selected=False, now=None)
    member = _agent(
        cl_name="demo--code",
        agent_name="demo--code",
        raw_suffix="20260425143002",
    )
    root.followup_agents.append(member)
    after = cached_format_agent_option(cache, root, 0, is_selected=False, now=None)

    assert before[0] is not after[0]
    assert _style_at(before[0], before[0].plain.rindex("demo")) == "#FFD700"
    assert _style_at(after[0], after[0].plain.rindex("demo")) == "#00AFFF"
    assert "[agent]" not in after[0].plain


def test_cached_family_root_ignores_member_unread_count_changes() -> None:
    cache = AgentRenderCache()
    root = _agent(cl_name="build", agent_name="build", raw_suffix="family")
    root.agent_family = "build"
    root.agent_family_role = "root"
    member = _agent(
        cl_name="build--code",
        agent_name="build--code",
        raw_suffix="code",
    )
    member.parent_timestamp = root.raw_suffix
    member.agent_family = "build"
    member.agent_family_role = "code"
    root.followup_agents = [member]
    root.runtime_children = [member]

    read = cached_format_agent_option(
        cache,
        root,
        0,
        is_selected=False,
        unread_agent_ids=(),
    )
    stale_shell_unread = cached_format_agent_option(
        cache,
        root,
        0,
        is_selected=False,
        unread_agent_ids={member.identity},
    )

    assert read[0] is stale_shell_unread[0]
    assert read[1] is stale_shell_unread[1]
    assert "[U1]" not in stale_shell_unread[0].plain


def test_invalidate_agent_drops_only_that_identity() -> None:
    cache = AgentRenderCache()
    a = _agent(cl_name="alpha")
    b = _agent(cl_name="beta", raw_suffix="20260425143001")
    cached_format_agent_option(cache, a, 0, is_selected=False, now=None)
    cached_format_agent_option(cache, b, 1, is_selected=False, now=None)
    assert len(cache._agent) == 2
    cache.invalidate_agent(a.identity)
    assert len(cache._agent) == 1
    # Surviving entry belongs to ``b``.
    surviving_key = next(iter(cache._agent))
    assert surviving_key[0] == b.identity
