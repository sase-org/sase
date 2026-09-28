"""Tribe panel flicker regression coverage (plan 202609/tribe_panel_flicker)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from textual.worker import Worker, WorkerState

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.actions.agents._display_helpers import panel_widget_id_for_key
from sase.ace.tui.actions.agents._selection import AgentSelectionMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_tribe_summary import build_agent_tribe_summary_snapshot
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.nav_gate import NavigationGate
from sase.ace.tui.widgets.agent_detail import AgentDetail


def _make_agent(cl_name: str) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="crs",
    )


@dataclass
class _Timer:
    stopped: bool = False

    def stop(self) -> None:
        self.stopped = True


class _ListWidget:
    def __init__(self, wid: str = "agent-list-panel") -> None:
        self.id = wid
        self._classes: set[str] = set()

    def update_list(self, *args: Any, **kwargs: Any) -> None:
        return

    def update_highlight(self, *args: Any, **kwargs: Any) -> None:
        return

    def add_class(self, name: str) -> None:
        self._classes.add(name)

    def remove_class(self, name: str) -> None:
        self._classes.discard(name)

    def focus(self) -> None:
        return

    def clear_highlight(self) -> None:
        return


class _FakeAgentDetail:
    """Stand-in for AgentDetail with a complete-document predicate."""

    def __init__(self, complete_identity: object | None = None) -> None:
        self.immediate_calls: list[tuple[str | None, int | None]] = []
        self.full_calls: list[tuple[str | None, int | None]] = []
        self._agent_detail_generation: int = 0
        self.llm_calls_detail_level = 0
        self.tribe_calls: list[tuple[object, bool]] = []
        self._complete_identity = complete_identity

    def shows_complete_tribe_document(self, identity: object | None) -> bool:
        return identity is not None and identity == self._complete_identity

    def update_display(
        self,
        agent: Agent,
        *,
        stale_threshold_seconds: int = 10,
        attempt_number: int | None = None,
    ) -> None:
        self._agent_detail_generation += 1
        self.full_calls.append((agent.cl_name, attempt_number))

    def update_display_immediate(
        self, agent: Agent, attempt_number: int | None = None
    ) -> None:
        self._agent_detail_generation += 1
        self.immediate_calls.append((agent.cl_name, attempt_number))

    def show_empty(self) -> None:
        return

    def show_tribe_summary(self, snapshot: object, *, cheap: bool = False) -> None:
        self._agent_detail_generation += 1
        self.tribe_calls.append((snapshot, cheap))

    def is_file_visible(self) -> bool:
        return False

    def is_llm_calls_visible(self) -> bool:
        return False


class _FooterWidget:
    def update_agent_bindings(self, *args: Any, **kwargs: Any) -> None:
        return


class _Container:
    def __init__(self, children: list[_ListWidget]) -> None:
        self.children = list(children)


class _QueryResult:
    def __init__(self, items: list[_ListWidget]) -> None:
        self._items = items

    def results(self, _type: Any = None) -> Any:
        return iter(self._items)


class _FakeApp(AgentDisplayMixin):
    def __init__(self, *, agents: list[Agent]) -> None:
        self._agents = agents
        self._fold_counts: dict[str, tuple[int, int]] = {}
        self._agent_search_query = ""
        self._agent_detail_debouncer = DetailPanelDebouncer(self)  # type: ignore[arg-type]
        self.current_idx = 0
        self.current_attempt_number = None
        self.refresh_interval = 10
        self.current_tab = "agents"
        self._marked_agents: set[Any] = set()
        self._entry_jump_mode_active = False
        self._entry_jump_index_to_hint: dict[int, str] = {}
        self._countdown_remaining = 0

        from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
        from sase.ace.tui.models.agent_panels import AgentPanelGroup

        self._group_fold_registry = AgentGroupFoldRegistry()
        self._current_group_key = None
        self._panel_group = AgentPanelGroup.from_agents(self._agents)
        self._pending_callback = None

        list_widget = _ListWidget()
        self._container = _Container([list_widget])
        self.detail_widget = _FakeAgentDetail()
        self._widgets = {
            "#agent-list-panel": list_widget,
            "#agent-list-container": self._container,
            "#agent-detail-panel": self.detail_widget,
            "#keybinding-footer": _FooterWidget(),
        }

    def query_one(self, selector: str, _type: Any = None) -> Any:
        return self._widgets[selector]

    def query(self, selector: str) -> Any:
        return _QueryResult(self._container.children)

    def set_timer(self, _delay: float, callback: Any) -> Any:
        self._pending_callback = callback
        return _Timer()

    def _update_agents_info_panel(self) -> None:
        return

    def _resolve_agent_cl_name(self, _agent: Agent) -> str | None:
        return None

    def _get_selected_agent(self) -> Agent:
        return self._agents[self.current_idx]


class _SummaryApp(AgentSelectionMixin, _FakeApp):
    def __init__(self, *, agents: list[Agent]) -> None:
        super().__init__(agents=agents)
        from sase.ace.tui.models.agent_panels import AgentPanelGroup

        self._collapsed_panel_keys = {"collapsed"}
        for agent in self._agents:
            agent.tribe = "collapsed"
        self._panel_group = AgentPanelGroup.from_agents(
            self._agents,
            focused_key="collapsed",
            collapsed_panel_keys=self._collapsed_panel_keys,
        )
        wid = panel_widget_id_for_key("collapsed")
        list_widget = _ListWidget(wid)
        self._container = _Container([list_widget])
        self._widgets["#agent-list-container"] = self._container
        self._widgets[f"#{wid}"] = list_widget


def test_same_tribe_refresh_skips_cheap_placeholder() -> None:
    agents = [_make_agent("agent_0"), _make_agent("agent_1")]
    app = _SummaryApp(agents=agents)
    focus = app._resolve_focused_panel()
    assert focus is not None
    app.detail_widget._complete_identity = focus.container_identity

    app._refresh_agents_display_debounced()

    assert app.detail_widget.tribe_calls == []
    assert app.detail_widget.immediate_calls == []
    assert app.detail_widget.full_calls == []
    assert app._agent_detail_debouncer.is_pending


def test_different_tribe_still_gets_cheap_placeholder() -> None:
    agents = [_make_agent("agent_0"), _make_agent("agent_1")]
    app = _SummaryApp(agents=agents)
    app.detail_widget._complete_identity = ("panel", "other-tribe")

    app._refresh_agents_display_debounced()

    assert len(app.detail_widget.tribe_calls) == 1
    assert app.detail_widget.tribe_calls[0][1] is True
    assert app._agent_detail_debouncer.is_pending


def test_fire_debounced_defers_while_prompt_input_active() -> None:
    agents = [_make_agent("agent_0"), _make_agent("agent_1")]
    app = _SummaryApp(agents=agents)
    app._prompt_input_active = lambda: True  # type: ignore[attr-defined]

    app._fire_debounced_detail_update()

    assert app.detail_widget.tribe_calls == []
    assert app._agent_detail_debouncer.is_pending

    app._prompt_input_active = lambda: False  # type: ignore[attr-defined]
    app._fire_debounced_detail_update()

    assert len(app.detail_widget.tribe_calls) == 1
    assert app.detail_widget.tribe_calls[0][1] is False


def test_refresh_tribe_summary_only_defers_while_prompt_input_active() -> None:
    agents = [_make_agent("agent_0"), _make_agent("agent_1")]
    app = _SummaryApp(agents=agents)
    app._prompt_input_active = lambda: True  # type: ignore[attr-defined]

    assert app._refresh_tribe_summary_only() is True
    assert app.detail_widget.tribe_calls == []
    assert app._agent_detail_debouncer.is_pending


async def test_shows_complete_tribe_document_lifecycle() -> None:
    from textual.app import App, ComposeResult

    from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel

    class _LifecycleApp(App[None]):
        def compose(self) -> ComposeResult:
            yield AgentDetail(id="agent-detail-panel")

    agent = _make_agent("agent_0")
    snapshot = build_agent_tribe_summary_snapshot(
        "collapsed", [agent], panel_collapsed=True
    )
    app = _LifecycleApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        assert (
            detail.shows_complete_tribe_document(snapshot.container_identity) is False
        )

        detail.show_tribe_summary(snapshot, cheap=True)
        await pilot.pause()
        assert (
            detail.shows_complete_tribe_document(snapshot.container_identity) is False
        )

        detail.show_tribe_summary(snapshot, cheap=False)
        await pilot.pause()
        assert detail.shows_complete_tribe_document(snapshot.container_identity) is True
        assert detail.shows_complete_tribe_document(("panel", "other")) is False

        detail.show_empty()
        await pilot.pause()
        assert (
            detail.shows_complete_tribe_document(snapshot.container_identity) is False
        )

        detail.show_tribe_summary(snapshot, cheap=False)
        await pilot.pause()
        assert detail.shows_complete_tribe_document(snapshot.container_identity) is True
        detail.update_display(agent)
        await pilot.pause()
        assert (
            detail.shows_complete_tribe_document(snapshot.container_identity) is False
        )
        prompt = detail.query_one("#agent-prompt-panel", AgentPromptPanel)
        assert prompt is not None


_NOW = datetime(2026, 7, 18, 16, 0, 0)


def _tribe_agent(name: str, suffix: str, **overrides: object) -> Agent:
    values: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": name,
        "project_file": "/tmp/demo.sase",
        "status": "DONE",
        "start_time": _NOW,
        "stop_time": _NOW,
        "raw_suffix": suffix,
        "agent_name": name,
        "tribe": "epic",
    }
    values.update(overrides)
    return Agent(**values)  # type: ignore[arg-type]


def test_signature_change_retains_disk_and_requests_refresh() -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_tribe_aggregation import (
        _TribeDiskSnapshot,
        cache_tribe_enrichment,
        get_cached_tribe_section_snapshot,
        prepare_tribe_section_snapshot,
        tribe_sections_to_refresh,
        TribeEnrichmentResult,
    )

    first = _tribe_agent("first", "first")
    summary = build_agent_tribe_summary_snapshot(
        "epic", [first], panel_collapsed=True, now=_NOW
    )
    widget = SimpleNamespace()
    prepare_tribe_section_snapshot(widget, summary, [first])
    sources_before = cast(
        Any,
        __import__(
            "sase.ace.tui.widgets.prompt_panel._agent_tribe_aggregation",
            fromlist=["get_cached_tribe_sources"],
        ).get_cached_tribe_sources(widget, summary.container_identity),
    )
    disk = _TribeDiskSnapshot(
        loaded_sections=frozenset({"replies", "prompts", "slow-tool-calls"}),
        replies=(),
        slow_tool_calls=(),
    )
    result = TribeEnrichmentResult(
        panel_identity=summary.container_identity,
        source_signature=tuple(
            cast(Any, source).signature for source in sources_before
        ),
        disk=disk,
        runtime_statistics_refreshed=False,
        runtime_statistics=None,
    )
    assert cache_tribe_enrichment(widget, result) is not None

    second = _tribe_agent("second", "second")
    changed_summary = build_agent_tribe_summary_snapshot(
        "epic", [first, second], panel_collapsed=True, now=_NOW
    )
    assert changed_summary.container_identity == summary.container_identity
    retained = prepare_tribe_section_snapshot(widget, changed_summary, [first, second])
    assert retained.disk is disk
    assert retained.loading_sections == frozenset()
    refresh = tribe_sections_to_refresh(
        widget, summary.container_identity, {"replies", "prompts", "slow-tool-calls"}
    )
    assert refresh == frozenset({"replies", "prompts", "slow-tool-calls"})
    cached = get_cached_tribe_section_snapshot(widget, summary.container_identity)
    assert cached is not None and cached.disk is disk


def test_departed_units_are_filtered_from_disk_sections() -> None:
    from rich.text import Text

    from sase.ace.tui.models._agent_clan_sections import (
        ClanDiskMemberSnapshot,
        ClanTextEntry,
    )
    from sase.ace.tui.widgets.prompt_panel._agent_display_tribe_prompts import (
        append_prompts,
    )
    from sase.ace.tui.widgets.prompt_panel._agent_display_tribe_sections import (
        append_replies,
        append_slow_tool_calls,
    )
    from sase.ace.tui.widgets.prompt_panel._agent_tribe_aggregation import (
        _TribeDiskSnapshot,
        TribeSectionSnapshot,
        TribeSlowToolEntry,
        TribeTextEntry,
    )
    from sase.ace.tui.widgets.prompt_panel._agent_tribe_prompts import (
        TribePromptGroup,
        TribePromptMember,
        TribePromptsSnapshot,
    )
    from sase.ace.tui.models.fold_state import FoldLevel

    present: set[Any] = {("running", "keep", None)}
    departed: Any = ("running", "departed", None)
    reply_entry = TribeTextEntry(
        unit_identity=departed,
        unit_label="departed",
        entry=ClanTextEntry(
            member_identity=departed,
            member_label="departed",
            kind="REPLY",
            preview="hi",
            body="hi",
        ),
    )
    kept_reply = TribeTextEntry(
        unit_identity=("running", "keep", None),
        unit_label="keep",
        entry=ClanTextEntry(
            member_identity=("running", "keep", None),
            member_label="keep",
            kind="REPLY",
            preview="kept",
            body="kept",
        ),
    )
    snapshot = TribeSectionSnapshot(
        panel_identity=("panel", "epic"),
        source_signature=(),
        disk=_TribeDiskSnapshot(
            loaded_sections=frozenset({"replies", "slow-tool-calls", "prompts"}),
            replies=(reply_entry, kept_reply),
            slow_tool_calls=(
                TribeSlowToolEntry(
                    unit_identity=departed,
                    unit_label="departed",
                    entry=cast(
                        Any,
                        SimpleNamespace(
                            member_label="departed",
                            call=SimpleNamespace(
                                entry=SimpleNamespace(
                                    display_tool_name="tool",
                                    compact_target="",
                                    detail="",
                                ),
                                effective_duration_ms=1000,
                                is_running=False,
                                did_not_complete=False,
                            ),
                        ),
                    ),
                ),
            ),
            prompts=TribePromptsSnapshot(
                groups=(
                    TribePromptGroup(
                        digest=cast(
                            Any,
                            SimpleNamespace(
                                group_key="g1",
                                headline="departed headline",
                                headline_spans=(),
                                body="departed body",
                                body_spans=(),
                                body_line_count=1,
                                launch="",
                                launch_spans=(),
                                xprompts=(),
                                project=None,
                            ),
                        ),
                        members=(
                            TribePromptMember(
                                unit_identity=departed,
                                unit_label="departed",
                                member_identity=departed,
                                member_label="departed",
                            ),
                        ),
                    ),
                    TribePromptGroup(
                        digest=cast(
                            Any,
                            SimpleNamespace(
                                group_key="g2",
                                headline="kept headline",
                                headline_spans=(),
                                body="kept body",
                                body_spans=(),
                                body_line_count=1,
                                launch="",
                                launch_spans=(),
                                xprompts=(),
                                project=None,
                            ),
                        ),
                        members=(
                            TribePromptMember(
                                unit_identity=("running", "keep", None),
                                unit_label="keep",
                                member_identity=("running", "keep", None),
                                member_label="keep",
                            ),
                        ),
                    ),
                ),
                agent_count=2,
                multi_project=False,
            ),
        ),
    )
    text = Text()
    append_replies(text, snapshot, level=FoldLevel.EXHAUSTIVE, present_units=present)
    assert "departed" not in text.plain
    assert "kept" in text.plain

    slow_text = Text()
    append_slow_tool_calls(
        slow_text, snapshot, level=FoldLevel.EXHAUSTIVE, present_units=present
    )
    assert slow_text.plain == ""

    prompt_text = Text()
    append_prompts(
        prompt_text,
        snapshot,
        level=FoldLevel.COLLAPSED,
        overrides={},
        unit_numbers={},
        present_units=present,
    )
    assert "departed headline" not in prompt_text.plain
    assert "kept headline" in prompt_text.plain


def test_identical_enrichment_result_posts_no_message() -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_display_async_groups import (
        AgentDisplayGroupWorkerMixin,
    )
    from sase.ace.tui.widgets.prompt_panel._agent_tribe_aggregation import (
        _TribeDiskSnapshot,
        cache_tribe_enrichment,
        prepare_tribe_section_snapshot,
        TribeEnrichmentResult,
    )
    from sase.ace.tui.widgets.prompt_panel._agent_tribe_clan_summaries import (
        TribeClanSummariesSnapshot,
    )

    first = _tribe_agent("first", "first")
    summary = build_agent_tribe_summary_snapshot(
        "epic", [first], panel_collapsed=True, now=_NOW
    )

    class _Panel(AgentDisplayGroupWorkerMixin):
        def __init__(self) -> None:
            self.messages: list[Any] = []
            self._tribe_section_pending_request = None

        def post_message(self, message: Any) -> None:
            self.messages.append(message)

    panel = _Panel()
    prepare_tribe_section_snapshot(panel, summary, [first])
    from sase.ace.tui.widgets.prompt_panel._agent_tribe_aggregation import (
        get_cached_tribe_sources,
    )

    sources = get_cached_tribe_sources(panel, summary.container_identity)
    signature = tuple(cast(Any, source).signature for source in sources)
    disk = _TribeDiskSnapshot(
        loaded_sections=frozenset({"replies"}),
        replies=(),
        slow_tool_calls=(),
    )
    clan_summaries = TribeClanSummariesSnapshot(entries=(), signature=())
    first_result = TribeEnrichmentResult(
        panel_identity=summary.container_identity,
        source_signature=signature,
        disk=disk,
        runtime_statistics_refreshed=True,
        runtime_statistics=None,
        clan_summaries=clan_summaries,
    )
    assert cache_tribe_enrichment(panel, first_result) is not None

    worker = SimpleNamespace(
        result=TribeEnrichmentResult(
            panel_identity=summary.container_identity,
            source_signature=signature,
            disk=disk,
            runtime_statistics_refreshed=False,
            runtime_statistics=None,
            clan_summaries=clan_summaries,
        )
    )
    panel._tribe_section_worker = worker  # type: ignore[attr-defined]
    panel._tribe_section_request = SimpleNamespace(  # type: ignore[attr-defined]
        panel_identity=summary.container_identity, sections=frozenset()
    )
    panel._apply_tribe_section_enrichment_result(worker, WorkerState.SUCCESS)  # type: ignore[arg-type]
    assert panel.messages == []

    changed_disk = _TribeDiskSnapshot(
        loaded_sections=frozenset({"replies", "prompts"}),
        replies=(),
        slow_tool_calls=(),
    )
    worker2 = SimpleNamespace(
        result=TribeEnrichmentResult(
            panel_identity=summary.container_identity,
            source_signature=signature,
            disk=changed_disk,
            runtime_statistics_refreshed=False,
            runtime_statistics=None,
            clan_summaries=clan_summaries,
        )
    )
    panel._tribe_section_worker = worker2  # type: ignore[attr-defined]
    panel._tribe_section_request = SimpleNamespace(  # type: ignore[attr-defined]
        panel_identity=summary.container_identity, sections=frozenset()
    )
    panel._apply_tribe_section_enrichment_result(worker2, WorkerState.SUCCESS)  # type: ignore[arg-type]
    assert len(panel.messages) == 1


def test_update_tribe_display_memo_skips_identical_rebuild(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from textual.app import App, ComposeResult

    from sase.ace.tui.models.fold_state import FoldLevel
    from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel

    agent = _tribe_agent("memo", "memo")
    snapshot = build_agent_tribe_summary_snapshot(
        "epic", [agent], panel_collapsed=True, now=_NOW
    )

    builds: list[str] = []
    real_builder: Any = None
    try:
        from sase.ace.tui.widgets.prompt_panel import _agent_display_tribe as tribe_mod

        real_builder = tribe_mod.build_tribe_detail_text

        def counting_builder(*args: Any, **kwargs: Any) -> Any:
            builds.append("built")
            return real_builder(*args, **kwargs)

        monkeypatch.setattr(tribe_mod, "build_tribe_detail_text", counting_builder)
    except Exception:
        pass

    class _MemoApp(App[None]):
        def compose(self) -> ComposeResult:
            yield AgentPromptPanel(id="agent-prompt-panel")

    app = _MemoApp()
    import asyncio

    async def _run() -> None:
        async with app.run_test(size=(80, 24)) as pilot:
            panel = app.query_one("#agent-prompt-panel", AgentPromptPanel)
            panel.update_tribe_display(snapshot, cheap=False)
            await pilot.pause()
            first_builds = len(builds)
            assert first_builds == 1

            panel.update_tribe_display(snapshot, cheap=False)
            await pilot.pause()
            assert len(builds) == first_builds

            panel.update_display(agent)
            await pilot.pause()
            panel.update_tribe_display(snapshot, cheap=False)
            await pilot.pause()
            assert len(builds) == first_builds + 1

    asyncio.run(_run())


async def test_selected_tribe_noop_refresh_keeps_main_deck_stable() -> None:
    """Pilot regression: idle finalize refresh must not repaint a placeholder."""
    from sase.ace.tui.app import AceApp
    from sase.ace.tui.models.fold_state import FoldLevel
    from sase.ace.tui.widgets.agent_detail import AgentDetail as _Detail
    from sase.ace.tui.widgets.agent_jump_panel import AgentJumpPanel
    from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
    from sase.ace.tui.widgets.renderable_text import renderable_to_text
    from tests.ace.tui._bench_tui_jk_helpers import (
        _install_agents_fixture,
        _wait_for_startup,
    )

    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test(size=(120, 40)) as pilot:
        await _wait_for_startup(app, pilot)
        await pilot.press("ctrl+l")
        await pilot.pause()
        _install_agents_fixture(app, count=48)
        app._refresh_agents_display(list_changed=True, defer_detail=True)
        await pilot.pause(0.2)
        assert app._activate_focused_panel() is True
        assert app._resolve_focused_panel() is not None
        await pilot.press("z", "z")
        await pilot.pause(0.3)
        app._fire_debounced_detail_update()
        await pilot.pause(0.4)
        detail = app.query_one("#agent-detail-panel", _Detail)
        detail.query_one("#agent-prompt-panel", AgentPromptPanel)
        jump = detail.query_one("#agent-jump-panel", AgentJumpPanel)
        assert jump.has_targets
        assert not jump.has_class("hidden")

        try:
            scroll = detail.deck_area.focused_panel().active_scroll()
        except Exception:
            scroll = None
        if scroll is not None:
            try:
                scroll.scroll_to(y=40, animate=False)
            except Exception:
                pass
            await pilot.pause(0.2)
            before_y = int(scroll.scroll_y)
        else:
            before_y = 0
        before_targets = len(jump._jump_map.targets) if jump._jump_map else 0
        assert before_targets > 0

        paints: list[str] = []
        real_update = AgentPromptPanel.update

        def recording_update(self: Any, content: Any = "", **kwargs: Any) -> None:
            try:
                paints.append(renderable_to_text(content) or "")
            except Exception:
                paints.append("")
            real_update(self, content, **kwargs)

        jump_events: list[tuple[int, bool]] = []
        real_show_jump = AgentJumpPanel.show_jump_map

        def recording_show_jump(self: Any, jump_map: Any, roster: Any = None) -> None:
            try:
                jump_events.append(
                    (
                        len(jump_map.targets) if jump_map is not None else 0,
                        self.has_class("hidden"),
                    )
                )
            except Exception:
                pass
            real_show_jump(self, jump_map, roster)

        import unittest.mock as mock

        with mock.patch.object(AgentPromptPanel, "update", recording_update):
            with mock.patch.object(
                AgentJumpPanel, "show_jump_map", recording_show_jump
            ):
                app._refresh_agents_display_after_finalize(
                    previous_agents=list(app._agents), defer_detail=True
                )
                await pilot.pause(0.5)
                app._refresh_agents_display(list_changed=True, defer_detail=True)
                await pilot.pause(0.5)

        assert not any("loading" in paint for paint in paints), (
            f"placeholder repainted: {[p[:80] for p in paints if 'loading' in p]}"
        )
        assert jump.has_targets
        assert not jump.has_class("hidden")
        assert all(count > 0 for count, _hidden in jump_events), (
            f"jump panel lost targets: {jump_events}"
        )
        if scroll is not None:
            assert int(scroll.scroll_y) == before_y


def test_update_tribe_display_rebuilds_on_theme_change(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from textual.app import App, ComposeResult

    from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel

    agent = _tribe_agent("theme", "theme")
    snapshot = build_agent_tribe_summary_snapshot(
        "epic", [agent], panel_collapsed=True, now=_NOW
    )
    builds: list[str] = []
    try:
        from sase.ace.tui.widgets.prompt_panel import _agent_display_tribe as tribe_mod

        real_builder = tribe_mod.build_tribe_detail_text

        def counting_builder(*args: Any, **kwargs: Any) -> Any:
            builds.append("built")
            return real_builder(*args, **kwargs)

        monkeypatch.setattr(tribe_mod, "build_tribe_detail_text", counting_builder)
    except Exception:
        pass

    class _ThemeApp(App[None]):
        def compose(self) -> ComposeResult:
            yield AgentPromptPanel(id="agent-prompt-panel")

    app = _ThemeApp()
    import asyncio

    async def _run() -> None:
        async with app.run_test(size=(80, 24)) as pilot:
            panel = app.query_one("#agent-prompt-panel", AgentPromptPanel)
            panel.update_tribe_display(snapshot, cheap=False)
            await pilot.pause()
            assert len(builds) == 1
            monkeypatch.setattr(panel, "_tribe_theme_name", lambda: "other-theme")
            panel.update_tribe_display(snapshot, cheap=False)
            await pilot.pause()
            assert len(builds) == 2

    asyncio.run(_run())
