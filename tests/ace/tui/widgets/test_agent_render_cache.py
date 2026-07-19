"""Tests for per-row render cache hits and invalidation."""

from __future__ import annotations

import pytest
from rich.text import Text

from sase.ace.tui.models._agent_parallel_family import ParallelFamilyStatusCounts
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.widgets._agent_list_rendering import (
    AgentRenderCache,
    cached_format_agent_option,
    format_agent_option,
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


def test_cached_family_root_recolors_when_member_status_changes() -> None:
    cache = AgentRenderCache()
    root = _agent(status="RUNNING")
    member = _agent(
        cl_name="demo.phase",
        status="RUNNING",
        raw_suffix="20260425143100",
    )
    member.agent_family_parallel = True
    root.runtime_children.append(member)

    running_parts = cached_format_agent_option(
        cache, root, 0, is_selected=False, now=None
    )
    member.status = "DONE"
    done_parts = cached_format_agent_option(cache, root, 0, is_selected=False, now=None)

    assert running_parts[0] is not done_parts[0]
    assert "[R1]" in running_parts[0].plain
    assert "[D1]" in done_parts[0].plain
    assert "[R1]" not in done_parts[0].plain


def test_cached_family_root_aggregates_members_once_per_render_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.widgets import _agent_list_render_agent as render_agent

    cache = AgentRenderCache()
    root = _agent(status="RUNNING")
    member = _agent(
        cl_name="demo.phase",
        status="RUNNING",
        raw_suffix="20260425143100",
    )
    member.agent_family_parallel = True
    root.runtime_children.append(member)
    original = render_agent.parallel_family_member_counts
    calls = 0

    def counting_counts(agent: Agent) -> ParallelFamilyStatusCounts:
        nonlocal calls
        calls += 1
        return original(agent)

    monkeypatch.setattr(render_agent, "parallel_family_member_counts", counting_counts)

    cached_format_agent_option(cache, root, 0, is_selected=False, now=None)

    assert calls == 1


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
