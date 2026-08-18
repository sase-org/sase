"""Tests for per-row render cache hits and invalidation."""

from __future__ import annotations

from datetime import datetime

import pytest
from rich.text import Text

from sase.ace.tui.models._agent_tree import agent_fold_key
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_status import RUNNING_COLOR
from sase.ace.tui.models._agent_clan import ClanStatusCounts
from sase.ace.tui.widgets.agent_list import _compute_fold_annotation
from sase.ace.tui.widgets._agent_list_rendering import (
    AgentRenderCache,
    cached_format_agent_option,
    format_agent_option,
)
from sase.ace.tui.widgets._agent_list_styling import (
    _FOLD_RESTORE_GLYPH_STYLE,
    _MONITOR_COUNT_GLYPH_STYLE,
    _MONITOR_SETTLED_COUNT_GLYPH_STYLE,
)

from ._agent_render_cache_helpers import agent as _agent


def _style_at(text: Text, position: int) -> str | None:
    for span in reversed(text.spans):
        if span.start <= position < span.end:
            return str(span.style)
    return str(text.style) if text.style else None


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
        has_missing_wait_target=False,
    )
    missing = cached_format_agent_option(
        cache,
        agent,
        0,
        is_selected=False,
        has_missing_wait_target=True,
    )

    assert known[0] is not missing[0]
    assert known[0].plain.endswith("(WAITING)")
    assert missing[0].plain.endswith("(WAITING ?)")


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


def _clan_with_member(*, member_status: str = "RUNNING") -> tuple[Agent, Agent]:
    clan = _agent(cl_name="research", status=member_status, raw_suffix=None)
    clan.agent_name = "research"
    clan.is_clan_container = True
    clan.agent_clan = "research"
    clan.agent_clan_generation = "generation"
    member = _agent(
        cl_name="research.phase",
        status=member_status,
        raw_suffix="20260425143100",
    )
    member.agent_name = "research.phase"
    member.agent_clan = "research"
    member.agent_clan_generation = "generation"
    clan.runtime_children.append(member)
    return clan, member


def test_cached_clan_row_recolors_when_member_status_changes() -> None:
    cache = AgentRenderCache()
    root, member = _clan_with_member(member_status="RUNNING")

    running_parts = cached_format_agent_option(
        cache, root, 0, is_selected=False, now=None
    )
    member.status = "DONE"
    done_parts = cached_format_agent_option(cache, root, 0, is_selected=False, now=None)

    assert running_parts[0] is not done_parts[0]
    assert "[R1]" in running_parts[0].plain
    assert "[D1]" in done_parts[0].plain
    assert "[R1]" not in done_parts[0].plain


def test_cached_clan_row_invalidates_when_member_joins_global_queue() -> None:
    cache = AgentRenderCache()
    root, member = _clan_with_member(member_status="WAITING")
    member.pid = 100
    member.waiting_for = ["dependency"]

    dependency_wait = cached_format_agent_option(
        cache,
        root,
        0,
        is_selected=False,
        now=None,
    )
    member.waiting_for = []
    member.wait_runners = 9
    member.slot_requested_at = "2026-04-25T14:31:00Z"
    member.status = "QUEUED"
    global_wait = cached_format_agent_option(
        cache,
        root,
        0,
        is_selected=False,
        now=None,
    )

    assert dependency_wait[0] is not global_wait[0]
    assert "[W1]" in dependency_wait[0].plain
    assert "[Q1]" in global_wait[0].plain


def test_cached_clan_row_aggregates_members_once_per_render_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.widgets import _agent_list_render_agent as render_agent

    cache = AgentRenderCache()
    root, _member = _clan_with_member(member_status="RUNNING")
    original = render_agent.clan_member_counts
    calls = 0

    def counting_counts(agent: Agent) -> ClanStatusCounts:
        nonlocal calls
        calls += 1
        return original(agent)

    monkeypatch.setattr(render_agent, "clan_member_counts", counting_counts)

    cached_format_agent_option(cache, root, 0, is_selected=False, now=None)

    assert calls == 1


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


def test_cached_clan_row_invalidates_on_projection_and_tribe_changes() -> None:
    cache = AgentRenderCache()
    clan = _agent(status="RUNNING")
    clan.is_clan_container = True
    clan.agent_clan = "research"
    clan.agent_clan_generation = "generation"
    clan.clan_tribes = ("epic",)

    before = cached_format_agent_option(cache, clan, 0, is_selected=False, now=None)
    clan.clan_tribes = ("epic", "review")
    after_tribe = cached_format_agent_option(
        cache, clan, 0, is_selected=False, now=None
    )
    clan.tree_depth = 1
    after_depth = cached_format_agent_option(
        cache, clan, 0, is_selected=False, now=None
    )

    assert before[0] is not after_tribe[0]
    assert after_tribe[0] is not after_depth[0]
    assert "@review" not in before[0].plain
    assert "@review" in after_tribe[0].plain


def test_cached_clan_row_invalidates_across_done_unread_done_transition() -> None:
    cache = AgentRenderCache()
    clan = _agent(cl_name="research", status="DONE", raw_suffix=None)
    clan.is_clan_container = True
    clan.agent_clan = "research"
    clan.agent_clan_generation = "generation"
    member = _agent(cl_name="research.done", status="DONE", raw_suffix="done")
    member.agent_clan = "research"
    member.agent_clan_generation = "generation"
    clan.runtime_children = [member]

    read_before = cached_format_agent_option(
        cache,
        clan,
        0,
        is_selected=False,
    )
    unread = cached_format_agent_option(
        cache,
        clan,
        0,
        is_selected=False,
        unread_agent_ids={member.identity},
    )
    read_after = cached_format_agent_option(
        cache,
        clan,
        0,
        is_selected=False,
    )

    assert "[D1]" in read_before[0].plain
    assert "[U1]" in unread[0].plain
    assert "D1" not in unread[0].plain
    assert "[D1]" in read_after[0].plain
    assert unread[0] is not read_after[0]


def test_clan_row_omits_only_the_matching_split_panel_tribe() -> None:
    clan = _agent(cl_name="research", status="RUNNING")
    clan.is_clan_container = True
    clan.agent_clan = "research"
    clan.clan_tribes = ("epic",)

    split, _, _ = format_agent_option(
        clan,
        0,
        is_selected=False,
        panel_tribe="epic",
    )
    merged, _, _ = format_agent_option(
        clan,
        0,
        is_selected=False,
        tribe_label="epic",
    )

    assert "@epic" not in split.plain
    assert merged.plain.count("@epic") == 1


def test_agent_and_clan_tribe_annotations_use_independent_identity_colors() -> None:
    standalone, _, _ = format_agent_option(
        _agent(),
        0,
        is_selected=False,
        tribe_label="epic",
        tribe_colors={"epic": "#123456"},
    )
    clan = _agent(cl_name="research", status="RUNNING")
    clan.is_clan_container = True
    clan.agent_clan = "research"
    clan.clan_tribes = ("epic", "review")
    clan_text, _, _ = format_agent_option(
        clan,
        0,
        is_selected=False,
        tribe_colors={
            "epic": "#123456",
            "review": "#654321",
        },
    )

    assert _style_at(standalone, standalone.plain.index("@epic")) == "bold #123456"
    assert _style_at(clan_text, clan_text.plain.index("@epic")) == "bold #123456"
    assert _style_at(clan_text, clan_text.plain.index("@review")) == "bold #654321"


def test_cached_row_separates_resolved_tribe_color_fingerprints() -> None:
    cache = AgentRenderCache()
    agent = _agent()

    first = cached_format_agent_option(
        cache,
        agent,
        0,
        is_selected=False,
        tribe_label="epic",
        tribe_colors={"epic": "#123456"},
    )
    second = cached_format_agent_option(
        cache,
        agent,
        0,
        is_selected=False,
        tribe_label="epic",
        tribe_colors={"epic": "#654321"},
    )

    assert first[0] is not second[0]
    assert _style_at(first[0], first[0].plain.index("@epic")) == "bold #123456"
    assert _style_at(second[0], second[0].plain.index("@epic")) == "bold #654321"


def test_multitribe_clan_in_no_tribe_panel_keeps_distinct_ordered_tribes() -> None:
    clan = _agent(cl_name="research", status="RUNNING")
    clan.is_clan_container = True
    clan.agent_clan = "research"
    clan.clan_tribes = ("epic", "review", "epic")

    rendered, _, _ = format_agent_option(
        clan,
        0,
        is_selected=False,
        panel_tribe=None,
    )

    assert rendered.plain == "(RUNNING) research @epic @review"
    assert rendered.plain.count("@epic") == 1


def test_default_panel_suppresses_explicit_default_clan_annotation() -> None:
    clan = _agent(cl_name="research", status="RUNNING")
    clan.is_clan_container = True
    clan.agent_clan = "research"
    clan.clan_tribes = ("default", "review", "default")

    rendered, _, _ = format_agent_option(
        clan,
        0,
        is_selected=False,
        panel_tribe=None,
    )

    assert "@default" not in rendered.plain
    assert rendered.plain.endswith("@review")


def test_cached_clan_row_distinguishes_split_and_unsuppressed_contexts() -> None:
    cache = AgentRenderCache()
    clan = _agent(status="RUNNING")
    clan.is_clan_container = True
    clan.agent_clan = "research"
    clan.clan_tribes = ("epic",)

    split = cached_format_agent_option(
        cache,
        clan,
        0,
        is_selected=False,
        panel_tribe="epic",
    )
    unsuppressed = cached_format_agent_option(
        cache,
        clan,
        0,
        is_selected=False,
        panel_tribe=None,
    )

    assert split[0] is not unsuppressed[0]
    assert "@epic" not in split[0].plain
    assert "@epic" in unsuppressed[0].plain


def _family_container_with_running_monitor() -> tuple[Agent, Agent]:
    started = datetime(2026, 4, 25, 14, 30, 0)
    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha-root",
        project_file="/tmp/monitor.sase",
        status="RUNNING",
        start_time=started,
        raw_suffix="20260425143000",
        agent_name="alpha--0",
        agent_family="alpha",
        agent_family_role="root",
        role_suffix="--0",
    )
    monitor = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha-mon",
        project_file="/tmp/monitor.sase",
        status="MONITORING",
        start_time=started,
        raw_suffix="20260425143001",
        parent_timestamp=root.raw_suffix,
        agent_name="alpha--mon",
        agent_family="alpha",
        agent_family_role="monitor",
        role_suffix="--mon",
        monitor_id="m1",
        monitor_state="running",
        monitor_label="just check",
    )
    root.followup_agents = [monitor]
    return root, monitor


def test_cached_container_row_invalidates_when_monitor_settles() -> None:
    cache = AgentRenderCache()
    root, monitor = _family_container_with_running_monitor()

    running_parts = cached_format_agent_option(
        cache, root, 0, is_selected=False, now=None
    )
    monitor.monitor_state = "completed"
    monitor.stop_time = datetime(2026, 4, 25, 14, 33, 0)
    settled_parts = cached_format_agent_option(
        cache, root, 0, is_selected=False, now=None
    )

    assert running_parts[0] is not settled_parts[0]
    running_index = running_parts[0].plain.index("⚙1")
    assert _style_at(running_parts[0], running_index) == _MONITOR_COUNT_GLYPH_STYLE
    settled_index = settled_parts[0].plain.index("⚙1")
    assert (
        _style_at(settled_parts[0], settled_index) == _MONITOR_SETTLED_COUNT_GLYPH_STYLE
    )


def test_cached_container_row_invalidates_when_settled_monitor_arrives() -> None:
    """The settled lane must be a cache-key input on its own.

    A second monitor arriving already settled leaves the running lane
    unchanged (still 1) while the settled lane moves 0 -> 1. If the settled
    count were left out of ``agent_render_key``, this render would
    incorrectly reuse the stale cached entry.
    """
    cache = AgentRenderCache()
    root, running_monitor = _family_container_with_running_monitor()

    before = cached_format_agent_option(cache, root, 0, is_selected=False, now=None)
    assert before[0].plain.count("⚙1") == 1

    arrived_settled = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha-mon-2",
        project_file="/tmp/monitor.sase",
        status="MONITORED",
        start_time=datetime(2026, 4, 25, 14, 30, 0),
        stop_time=datetime(2026, 4, 25, 14, 33, 0),
        raw_suffix="20260425143002",
        parent_timestamp=root.raw_suffix,
        agent_name="alpha--mon-2",
        agent_family="alpha",
        agent_family_role="monitor",
        role_suffix="--mon-2",
        monitor_id="m2",
        monitor_state="completed",
        monitor_label="just check",
    )
    root.followup_agents = [running_monitor, arrived_settled]
    after = cached_format_agent_option(cache, root, 0, is_selected=False, now=None)

    assert before[0] is not after[0]
    assert "⚙1 ⚙1" in after[0].plain


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
