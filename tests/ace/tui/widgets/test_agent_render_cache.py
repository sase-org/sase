"""Tests for per-row render cache hits and invalidation."""

from __future__ import annotations

import pytest

from sase.ace.tui.models._agent_parallel_family import ParallelFamilyStatusCounts
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.widgets._agent_list_rendering import (
    AgentRenderCache,
    cached_format_agent_option,
)

from ._agent_render_cache_helpers import agent as _agent


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


def test_cached_clan_row_invalidates_on_projection_and_tag_changes() -> None:
    cache = AgentRenderCache()
    clan = _agent(status="RUNNING")
    clan.is_clan_container = True
    clan.agent_clan = "research"
    clan.agent_clan_generation = "generation"
    clan.clan_tags = ("epic",)

    before = cached_format_agent_option(cache, clan, 0, is_selected=False, now=None)
    clan.clan_tags = ("epic", "review")
    after_tag = cached_format_agent_option(cache, clan, 0, is_selected=False, now=None)
    clan.tree_depth = 1
    after_depth = cached_format_agent_option(
        cache, clan, 0, is_selected=False, now=None
    )

    assert before[0] is not after_tag[0]
    assert after_tag[0] is not after_depth[0]
    assert "@review" not in before[0].plain
    assert "@review" in after_tag[0].plain


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
