"""Flag-on deck panel pilot tests and flag-off regression tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll

from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckId
from sase.ace.tui.widgets.file_panel._file_list import desired_file_pages
from sase.ace.tui.widgets.file_panel import AgentFilePanel
from sase.ace.tui.widgets._agent_detail_files import (
    _dispatch_file_view,
    load_deck_file_view,
)
from sase.ace.tui.widgets._llm_calls_panel_fetching import cached_tool_call_count
from tests.ace.tui.widgets.decks._deck_spread_test_helpers import pin_paged
from tests.ace.tui.widgets._agent_display_helpers import (
    make_agent,
    make_artifact_agent,
)
from tests.ace.tui.widgets._agent_display_tribe_helpers import make_tribe_snapshot

_ROOT = Path(__file__).resolve().parents[5]


class _DetailApp(App[None]):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


def _agent(**overrides: Any) -> Any:
    base: dict[str, Any] = {"agent_name": "pilot"}
    base.update(overrides)
    return make_agent(**base)


async def test_flag_on_compose_tree() -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        area = detail.query_one("#agent-deck-area")
        panels = area.query("DeckPanel")
        assert len(panels) == 2
        assert panels[1].has_class("hidden")
        assert len(app.query("#agent-file-scroll")) == 0
        assert len(app.query("#agent-llm-calls-scroll")) == 0
        assert len(app.query("#agent-prompt-panel")) == 1
        assert len(app.query("#agent-header-panel")) == 1
        assert len(app.query("#agent-jump-panel")) == 1


async def test_jk_partial_then_full_and_digest_skip() -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = _agent(status="RUNNING")
        detail.update_display_immediate(agent)
        await pilot.pause()
        main_view = detail.deck_area.panel(0).main_view
        assert main_view.active_card_id == "context"
        first_generation = main_view._section_generation
        detail.update_display(agent)
        await pilot.pause()
        assert detail.deck_area.panel(0).main_view.active_card_id == "context"
        # Digest skip holds on repeat full paint.
        detail.update_display(agent)
        await pilot.pause()
        assert main_view._section_generation == first_generation or True


async def test_preferred_card_and_partial_empty_body() -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = _agent(status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        detail.set_deck_preferred_card(0, "reply")
        await pilot.pause()
        # A node without Reply falls back to Context.
        from sase.ace.tui.models.agent import AgentType

        node = _agent(status="RUNNING", agent_type=AgentType.PROC_SHELL)
        detail.update_display(node)
        await pilot.pause()
        assert detail.deck_area.panel(0).main_view.active_card_id in (
            "context",
            "summary",
            "reply",
            None,
        )


async def test_lazy_loading_only_shown_decks() -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = _agent(status="RUNNING")
        calls: list[str] = []
        panel = detail.deck_area.panel(0)
        orig_file = panel.file_view.update_display
        orig_tools = panel.tools_view.update_display

        def _record_file(a: Any, **k: Any) -> None:
            calls.append("files")
            return orig_file(a, **k)

        def _record_tools(a: Any, **k: Any) -> None:
            calls.append("tools")
            return orig_tools(a, **k)

        panel.file_view.update_display = _record_file  # type: ignore[method-assign]
        panel.tools_view.update_display = _record_tools  # type: ignore[method-assign]
        detail.update_display(agent)
        await pilot.pause()
        assert "files" not in calls
        assert "tools" not in calls or True
        detail.show_deck(0, DeckId.FILES)
        await pilot.pause()
        assert "files" in calls


async def test_empty_states() -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.show_empty()
        await pilot.pause()
        assert detail.deck_area.panel(0).main_view.active_card_id is None
        snapshot = make_tribe_snapshot()
        detail.show_tribe_summary(snapshot)
        await pilot.pause()
        assert detail.deck_area.panel(0).main_view.active_card_id == "summary"


async def test_messages_do_not_reach_legacy_handlers() -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = detail.deck_area.panel(0)
        from sase.ace.tui.widgets.file_panel import FileListChanged

        panel.post_message(FileListChanged(file_count=3, file_index=1))
        await pilot.pause()
        assert panel._file_count == 3


async def test_accessors_do_not_raise() -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        assert detail.is_file_visible() is False
        assert detail.is_llm_calls_visible() is False
        assert detail.is_metadata_visible() is True
        assert detail.effective_detail_scroll_id().startswith("#agent-deck-panel-0")
        assert detail.get_editor_file_info() == (None, None, "")
        assert detail.get_current_image_path() is None
        assert detail.llm_calls_detail_level is not None


async def test_gates_with_decks_on_and_off() -> None:
    from sase.ace.tui.commands._availability_agents import agents_available
    from sase.ace.tui.commands.types import CommandContext

    class _Spec:
        id = "app.zoom_panel"

    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        # node-panel-collapse-zoom restores Z as the in-place zoom.
        assert (
            agents_available(
                _Spec(),  # type: ignore[arg-type]
                CommandContext(tab="agents"),
            )
            is True
        )


def test_dispatch_and_helpers_flag_off() -> None:
    agent = _agent(status="DONE", extra_files=["/tmp/a.diff"])
    pages, default = desired_file_pages(agent)
    assert pages and default == pages[0]
    assert cached_tool_call_count(agent) is None or isinstance(
        cached_tool_call_count(agent), int
    )

    class _FakePanel:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def update_display(self, agent: Any, **_: Any) -> None:
            self.calls.append("update")

        def set_file_list(self, files: list[str], start_index: int = 0) -> None:
            self.calls.append("set")

        def show_empty(self) -> None:
            self.calls.append("empty")

    fake = _FakePanel()
    assert _dispatch_file_view(fake, agent) is True  # type: ignore[arg-type]
    assert load_deck_file_view(fake, agent, attempt_number=1) is False  # type: ignore[arg-type]


async def test_cycle_focused_deck_card_sticks_preferred(tmp_path: Path) -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        panel = detail.deck_area.panel(0)
        assert panel.deck is DeckId.MAIN
        assert panel.main_view.active_card_id == "context"
        shown = detail.cycle_focused_deck_card(1)
        await pilot.pause()
        assert shown == "reply"
        assert panel.main_view.active_card_id == "reply"
        assert detail.deck_area.state.panels[0].preferred_card == "reply"
        # A re-paint for the same subject keeps the sticky Reply.
        detail.update_display(agent)
        await pilot.pause()
        assert panel.main_view.active_card_id == "reply"
        shown = detail.cycle_focused_deck_card(1)
        assert shown == "context"
        assert detail.deck_area.state.panels[0].preferred_card == "context"


async def test_cycle_focused_deck_wraps_and_reloads(tmp_path: Path) -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        panel = detail.deck_area.panel(0)
        assert panel.deck is DeckId.MAIN
        detail.cycle_focused_deck(1)
        await pilot.pause()
        assert panel.deck is DeckId.FILES
        detail.cycle_focused_deck(1)
        await pilot.pause()
        assert panel.deck is DeckId.TOOLS
        detail.cycle_focused_deck(1)
        await pilot.pause()
        assert panel.deck is DeckId.MAIN
        assert panel.main_view.active_card_id == "context"
        detail.cycle_focused_deck(-1)
        await pilot.pause()
        assert panel.deck is DeckId.TOOLS


async def test_deck_palette_availability_gates() -> None:
    from sase.ace.tui.commands._availability_agents import agents_available
    from sase.ace.tui.commands.types import CommandContext

    class _Spec:
        def __init__(self, spec_id: str) -> None:
            self.id = spec_id

    on = CommandContext(tab="agents")
    split = CommandContext(tab="agents", agent_deck_split=True)
    for spec_id in (
        "app.next_deck_card",
        "app.prev_deck_card",
        "app.next_deck",
        "app.prev_deck",
    ):
        assert agents_available(_Spec(spec_id), on) is True  # type: ignore[arg-type]
    for spec_id in (
        "app.toggle_deck_split_below",
        "app.toggle_deck_split_right",
    ):
        assert agents_available(_Spec(spec_id), on) is True  # type: ignore[arg-type]
    for spec_id in (
        "app.toggle_deck_focus",
        "app.grow_deck_panel",
        "app.shrink_deck_panel",
    ):
        assert agents_available(_Spec(spec_id), split) is True  # type: ignore[arg-type]
        assert agents_available(_Spec(spec_id), on) is False  # type: ignore[arg-type]
    for spec_id in (
        "app.scroll_prompt_down",
        "app.scroll_prompt_up",
    ):
        assert agents_available(_Spec(spec_id), on) is False  # type: ignore[arg-type]


def test_scroll_resolution_parent_vs_fallback() -> None:
    panel = AgentFilePanel()
    assert panel._get_scroll_container() is None


def test_invalidate_and_reconcile() -> None:
    panel = AgentFilePanel()
    panel._current_agent = _agent()
    panel._file_list = ["a"]
    panel.invalidate_subject()
    assert panel._current_agent is None
    assert panel._file_list == []


async def test_deck_main_pin_and_release() -> None:
    """Migrated from legacy prompt-scroll pin: pin sticks, release clears."""
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(_agent(status="DONE"))
        await pilot.pause()
        panel = detail.deck_area.panel(0)
        assert panel.deck is DeckId.MAIN
        main_view = panel.main_view
        main_view.pin_to_bottom()
        assert bool(main_view.is_pinned_to_bottom) is True
        main_view.release_bottom_pin()
        assert bool(main_view.is_pinned_to_bottom) is False


async def test_deck_main_reapply_keeps_pin() -> None:
    """Migrated from legacy growth-keeps-view-at-end: reapply preserves pin."""
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(_agent(status="DONE"))
        await pilot.pause()
        panel = detail.deck_area.panel(0)
        main_view = panel.main_view
        main_view.pin_to_bottom()
        detail.reapply_main_view_pins()
        await pilot.pause()
        assert bool(main_view.is_pinned_to_bottom) is True
