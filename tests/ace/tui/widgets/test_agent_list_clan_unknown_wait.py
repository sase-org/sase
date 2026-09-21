"""Tests for the clan aggregate unknown-wait indicator."""

from __future__ import annotations

import asyncio
from datetime import datetime

from rich.text import Text

from sase.ace.tui.actions.agents._loading_bead_warmup import (
    _AgentBeadWarmupResults,
)
from sase.ace.tui.agent_completion import (
    clan_unknown_wait_dependency_count,
    collect_agent_wait_status_maps,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_wait_beads import _WAIT_BEAD_STATUS_CACHE
from sase.ace.tui.util.nav_gate import NavigationGate
from sase.ace.tui.wait_status_presentation import WAIT_UNKNOWN_GLYPH_STYLE
from sase.ace.tui.widgets._agent_list_rendering import (
    agent_render_key,
    format_agent_option,
)
from sase.ace.tui.widgets._agent_list_render_cache import AgentRenderCache
from sase.ace.tui.widgets._agent_list_build_rows import (
    agent_row_context,
    build_row_inputs,
    format_agent_row,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_render_cache_helpers import agent as cache_agent


def _styles_covering(text: Text, substring: str) -> set[str]:
    start = text.plain.index(substring)
    end = start + len(substring)
    return {
        str(span.style) for span in text.spans if span.start < end and span.end > start
    }


def _container(*, clan: str = "research", generation: str = "gen-1") -> Agent:
    container = make_agent(
        agent_name=None,
        raw_suffix="clan-root",
        agent_clan=clan,
        agent_clan_generation=generation,
        is_clan_container=True,
        status="RUNNING",
    )
    container.runtime_children = []
    return container


def _member(
    *,
    name: str,
    status: str = "WAITING",
    clan: str = "research",
    generation: str = "gen-1",
    **overrides: object,
):
    kwargs: dict[str, object] = {
        "agent_name": name,
        "raw_suffix": f"{name}-suffix",
        "agent_clan": clan,
        "agent_clan_generation": generation,
        "status": status,
    }
    kwargs.update(overrides)
    return make_agent(**kwargs)  # type: ignore[arg-type]


def test_clan_row_renders_unknown_after_chip_with_style() -> None:
    container = _container()
    running = _member(name="research.a", status="RUNNING")
    done_a = _member(name="research.b", status="DONE")
    done_b = _member(name="research.c", status="DONE")
    done_c = _member(name="research.d", status="DONE")
    waiting = _member(name="research.land", waiting_for=["ghost"])
    container.runtime_children.extend([running, done_a, done_b, done_c, waiting])
    maps = collect_agent_wait_status_maps(
        [container, running, done_a, done_b, done_c, waiting]
    )

    count = clan_unknown_wait_dependency_count(container, maps)
    assert count == 1

    left, _, _ = format_agent_option(
        container, 0, is_selected=False, clan_unknown_wait_count=count
    )

    assert "[R1 W1 D3]" in left.plain
    assert "?1" in left.plain
    assert left.plain.index("[R1 W1 D3]") < left.plain.index("?1")
    assert WAIT_UNKNOWN_GLYPH_STYLE in _styles_covering(left, "?1")


def test_clan_row_without_unknowns_renders_no_marker() -> None:
    container = _container()
    running = _member(name="research.a", status="RUNNING")
    container.runtime_children.append(running)

    left, _, _ = format_agent_option(
        container, 0, is_selected=False, clan_unknown_wait_count=0
    )

    assert "?" not in left.plain


def test_clan_unknown_renders_even_when_chip_is_empty() -> None:
    container = _container()

    left, _, _ = format_agent_option(
        container, 0, is_selected=False, clan_unknown_wait_count=2
    )

    assert "?2" in left.plain
    assert WAIT_UNKNOWN_GLYPH_STYLE in _styles_covering(left, "?2")


def test_render_key_differs_when_only_clan_unknown_changes() -> None:
    agent = cache_agent(status="RUNNING")

    first = agent_render_key(
        agent,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
        clan_unknown_wait_count=0,
    )
    second = agent_render_key(
        agent,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
        clan_unknown_wait_count=1,
    )

    assert first != second


def test_row_context_carries_clan_unknown_and_format_uses_it() -> None:
    container = _container()
    waiting = _member(name="research.land", waiting_for=["ghost"])
    running = _member(name="research.a", status="RUNNING")
    container.runtime_children.extend([waiting, running])
    agents = [container, waiting, running]

    class _Widget:
        app = None
        _agents = agents

    inputs = build_row_inputs(
        _Widget(),  # type: ignore[arg-type]
        agents,
        0,
        marked_agents=set(),
        unread_agents=set(),
        fold_restore_marked_keys=(),
        fold_counts=None,
        jump_hints=None,
        current_group_key=None,
        tribe_labels=None,
        panel_tribe=None,
        parents_with_visible_children=set(),
        fully_expanded_parents=set(),
        now=None,
    )
    ctx = agent_row_context(inputs, container, 0)

    assert ctx["clan_unknown_wait_count"] == 1

    cache = AgentRenderCache()
    left, _, _ = format_agent_row(cache, inputs, container, 0, ctx, ())
    assert "?1" in left.plain


class _FakeApp:
    def __init__(self) -> None:
        self._agents_first_load_done = True
        self._bead_warmup_scan_scheduled = False
        self._bead_warmup_scan_running = False
        self._bead_warmup_scan_pending = False
        self._bead_warmup_scan_source = "unknown"
        self._bead_warmup_async_tasks: set[asyncio.Task[None]] = set()
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self._nav_gate = NavigationGate(window_s=0.25)
        self._patched: list[Agent] = []
        self._patch_kwargs: list[dict[str, object]] = []
        self._refresh_calls: list[dict[str, object]] = []
        self._patch_success = True

    def _try_patch_agent_row(self, agent: Agent, **kwargs: object) -> bool:
        # Import here so the test exercises the real warmup mixin body.
        from sase.ace.tui.actions.agents._loading_bead_warmup import (
            AgentBeadWarmupMixin,
        )

        assert isinstance(self, AgentBeadWarmupMixin) or True
        self._patched.append(agent)
        self._patch_kwargs.append(kwargs)
        return self._patch_success

    def _refresh_agents_display(self, **kwargs: object) -> None:
        self._refresh_calls.append(kwargs)


def _warmup_app(*, member: Agent, container: Agent) -> tuple[_FakeApp, object]:
    from sase.ace.tui.actions.agents._loading_bead_warmup import (
        AgentBeadWarmupMixin,
    )

    class _App(_FakeApp, AgentBeadWarmupMixin):
        pass

    app = _App()
    app._agents = [container, member]
    app._agents_with_children = [container, member]
    return app, AgentBeadWarmupMixin


def test_bead_warmup_patches_clan_container_for_unknown_bead() -> None:
    _WAIT_BEAD_STATUS_CACHE.clear()
    try:
        container = make_agent(
            agent_name=None,
            raw_suffix="g",
            agent_clan="clan",
            agent_clan_generation="g",
            is_clan_container=True,
            status="RUNNING",
            project_file="/tmp/proj/proj.sase",
        )
        container.runtime_children = []
        member = make_agent(
            agent_type=AgentType.RUNNING,
            cl_name="member",
            project_file="/tmp/proj/proj.sase",
            status="WAITING",
            start_time=datetime(2026, 6, 15, 19, 0, 0),
            raw_suffix="member",
            agent_name="clan.land",
            agent_clan="clan",
            agent_clan_generation="g",
            waiting_for_beads=["sase-1"],
        )
        container.runtime_children.append(member)

        app, _ = _warmup_app(member=member, container=container)
        _WAIT_BEAD_STATUS_CACHE.set(("proj", "sase-1"), "unsupported")

        app._apply_bead_warmup_results(  # type: ignore[attr-defined]
            _AgentBeadWarmupResults({}, {member.identity})
        )

        patched_identities = [a.identity for a in app._patched]
        assert member.identity in patched_identities
        assert container.identity in patched_identities
        assert app._refresh_calls == []

        maps = collect_agent_wait_status_maps([container, member])
        count = clan_unknown_wait_dependency_count(container, maps)
        assert count == 1
        left, _, _ = format_agent_option(
            container, 0, is_selected=False, clan_unknown_wait_count=count
        )
        assert "?1" in left.plain
    finally:
        _WAIT_BEAD_STATUS_CACHE.clear()
