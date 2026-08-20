"""Tests for clan-row render cache invalidation and tribe annotations."""

from __future__ import annotations

import pytest

from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models._agent_clan import ClanStatusCounts
from sase.ace.tui.widgets._agent_list_rendering import (
    AgentRenderCache,
    cached_format_agent_option,
    format_agent_option,
)

from ._agent_render_cache_helpers import agent as _agent
from ._agent_render_cache_helpers import style_at as _style_at


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
