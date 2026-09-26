"""Pilot coverage for inline Vim search in the Agents metadata panel."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import patch
import pytest

from sase.ace.testing import AcePage, set_agent_prompt_document
from sase.ace.tui.app import AceApp
from sase.ace.tui.keymaps import split_key_alternatives
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.widgets.agents_filter_bar import AgentsFilterBar
from sase.ace.tui.widgets.agent_header_panel import AgentHeaderPanel
from sase.ace.tui.widgets.renderable_text import renderable_to_text
from tests.ace.tui.widgets._agent_display_helpers import make_agent as _make_agent
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    wait_for_startup,
)


def _search_agents() -> list[Agent]:
    stopped = datetime(2026, 7, 19, 10, 10, 0)
    return [
        _make_agent(
            cl_name="search-fixture-first",
            agent_name="search.fixture.first",
            status="DONE",
            stop_time=stopped,
        ),
        _make_agent(
            cl_name="search-fixture-second",
            agent_name="search.fixture.second",
            status="DONE",
            stop_time=stopped,
            raw_suffix="20260612-120100",
        ),
    ]


async def test_inline_metadata_search_commit_repeat_q_and_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_search_agents())

    async with AcePage(
        query='"search-fixture"',
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("agent_count", 2)
        await set_agent_prompt_document(
            page,
            "Alpha needle result\nSecond needle result\n"
            + "\n".join(f"filler line {index}" for index in range(80)),
        )

        await page.press("comma", "slash", "n", "e", "e", "d", "l", "e")
        await page.pause()

        assert page.app._agent_metadata_search.mode == "typing"
        assert page.app._agent_metadata_search.current_selection is not None
        detail = page.app.query_one("#agent-detail-panel")
        panel = detail.deck_area.focused_panel()
        assert panel.search_scroll().has_class("-shown")

        frozen_corpus = page.app._agent_metadata_search.corpus
        await page.press("ctrl+r")
        await page.pause()
        assert page.app._agent_metadata_search.direction == "reverse"
        assert page.app._agent_metadata_search.query == "needle"
        assert page.app._agent_metadata_search.corpus == frozen_corpus
        assert page.app._agent_metadata_search.current_selection is not None
        assert page.app._agent_metadata_search.current_selection.index == 1

        await page.press("ctrl+r")
        await page.pause()
        assert page.app._agent_metadata_search.direction == "forward"
        assert page.app._agent_metadata_search.query == "needle"
        assert page.app._agent_metadata_search.current_selection is not None
        assert page.app._agent_metadata_search.current_selection.index == 0

        await page.press("enter", "n")
        await page.pause()
        assert page.app._agent_metadata_search.mode == "committed"
        assert page.app._agent_metadata_search.last_search == ("needle", "forward")
        assert page.app._agent_metadata_search.current_selection is not None
        assert page.app._agent_metadata_search.current_selection.index == 1

        await page.press("N")
        await page.pause()
        assert page.app._agent_metadata_search.mode == "committed"
        assert page.app._agent_metadata_search.current_selection is not None
        assert page.app._agent_metadata_search.current_selection.index == 0

        await page.press("ctrl+r", "n")
        await page.pause()
        assert page.app._agent_metadata_search.last_search == ("needle", "reverse")
        assert page.app._agent_metadata_search.current_selection is not None
        assert page.app._agent_metadata_search.current_selection.index == 1

        await page.press("q")
        await page.pause()
        assert page.app._agent_metadata_search.mode == "off"
        detail = page.app.query_one("#agent-detail-panel")
        panel = detail.deck_area.focused_panel()
        assert not panel.search_scroll().has_class("-shown")

        await page.press("question_mark")
        await page.expect_modal("HelpModal")
        await page.press("escape")
        await page.expect_no_modal()

        await page.press("comma", "slash", "n", "e", "e", "d", "l", "e", "enter")
        selected_before = page.app._get_selected_agent()
        await page.press("j")
        await page.pause()
        assert page.app._agent_metadata_search.mode == "off"
        assert page.app._get_selected_agent() is not selected_before


async def test_inline_metadata_search_yank_and_frozen_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda text: copied.append(text) or True,
    )
    patch_startup_loaders(monkeypatch, agents=_search_agents()[:1])

    async with AcePage(
        query='"search-fixture"',
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await set_agent_prompt_document(
            page,
            "Alpha needle result\nSecond needle result\n",
        )
        await page.press("comma", "slash", "n", "e", "e", "d", "l", "e", "enter")
        await page.pause()

        frozen = page.app._agent_metadata_search.corpus
        assert "needle" in frozen
        await set_agent_prompt_document(
            page,
            "replacement content from background refresh",
        )
        assert "needle" in frozen
        assert page.app._agent_metadata_search.corpus == frozen

        screen_type = type(page.app.screen)
        monkeypatch.setattr(
            screen_type,
            "get_selected_text",
            lambda _screen: "mouse-selected text",
        )
        await page.press("y")
        monkeypatch.setattr(
            screen_type,
            "get_selected_text",
            lambda _screen: "",
        )
        await page.press("y", "Y")
        await page.pause()
        assert copied == [
            "mouse-selected text",
            "needle",
            "Alpha needle result",
        ]


async def test_pinned_metadata_document_survives_a_debounced_repaint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A queued detail repaint must not replace the pinned corpus.

    Before the document was pinned this is exactly what dropped the
    injected corpus under load, after which ``/`` captured the real agent
    document and the search legitimately found nothing.
    """
    patch_startup_loaders(monkeypatch, agents=_search_agents())

    async with AcePage(
        query='"search-fixture"',
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("agent_count", 2)
        panel = await set_agent_prompt_document(page, "Alpha needle result\n")

        page.app._agent_detail_debouncer.schedule(
            page.app._fire_debounced_detail_update
        )
        await page.wait_for(
            lambda _state: not page.app._agent_detail_debouncer.is_pending,
        )
        await page.pause()

        assert "needle" in (renderable_to_text(panel.content) or "")


async def test_inline_metadata_search_exits_when_identity_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_search_agents()[:1])

    async with AcePage(
        query='"search-fixture"',
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await set_agent_prompt_document(page, "Alpha needle result\n")
        await page.press("comma", "slash", "n")
        assert page.app._agent_metadata_search.is_active

        detail = page.app.query_one("#agent-detail-panel")
        detail.show_empty()
        await page.pause()

        assert not page.app._agent_metadata_search.is_active
        panel = detail.deck_area.focused_panel()
        assert not panel.search_scroll().has_class("-shown")


def test_metadata_search_start_is_a_leader_action() -> None:
    agents = AceApp(auto_start_axe=False, initial_tab="agents")

    assert not hasattr(agents._keymap_registry.app, "search_forward")
    assert "edit_query" not in agents._keymap_registry.leader_mode.keys
    assert agents._keymap_registry.leader_mode.keys["search_forward"] == "slash"
    assert agents._keymap_registry.app.search_reverse == "ctrl+r"


async def test_inline_metadata_search_reverse_key_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_search_agents())

    with patch(
        "sase.config.load_merged_config",
        return_value={"ace": {"keymaps": {"app": {"search_reverse": "f5"}}}},
    ):
        async with AcePage(
            query='"search-fixture"',
            initial_tab="agents",
        ) as page:
            await wait_for_startup(page)
            await set_agent_prompt_document(
                page,
                "Alpha needle result\nSecond needle result\n",
            )

            await page.press("comma", "slash", "n", "e", "e", "d", "l", "e")
            await page.pause()
            assert page.app._agent_metadata_search.direction == "forward"
            assert page.app._agent_metadata_search.current_selection is not None
            assert page.app._agent_metadata_search.current_selection.index == 0

            await page.press("ctrl+r")
            await page.pause()
            assert page.app._agent_metadata_search.direction == "forward"
            assert page.app._agent_metadata_search.query == "needle"

            await page.press("f5")
            await page.pause()
            assert page.app._agent_metadata_search.direction == "reverse"
            assert page.app._agent_metadata_search.current_selection is not None
            assert page.app._agent_metadata_search.current_selection.index == 1


async def test_bare_slash_opens_agents_query_editor_not_metadata_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_search_agents())

    async with AcePage(
        query='"search-fixture"',
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await page.press("slash")
        await page.pause()

        bar = page.app.query_one(AgentsFilterBar)
        assert bar.display is True
        assert page.app._agents_filter_session_open is True
        assert not page.app._agent_metadata_search.is_active


async def test_leader_metadata_search_does_not_modify_committed_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_search_agents())

    async with AcePage(
        query='"search-fixture"',
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        page.app._agent_search_query = "cl:search-fixture-first"
        page.app._refilter_agents()
        await page.pause()
        committed = page.app._agent_search_query

        await set_agent_prompt_document(page, "Alpha needle result\n")
        await page.press("comma", "slash", "n")
        await page.pause()

        assert page.app._agent_metadata_search.is_active
        assert page.app._agent_search_query == committed


def _configured_scroll_keys() -> tuple[str, str]:
    """Return the configured scroll-down/up keys without starting the app."""
    probe = AceApp(auto_start_axe=False, initial_tab="agents")
    registry = probe._keymap_registry  # noqa: SLF001
    down = split_key_alternatives(registry.app.scroll_detail_down)[0]
    up = split_key_alternatives(registry.app.scroll_detail_up)[0]
    return down, up


class _FakeOverlayScroll:
    """Minimal scroll container recording half-page scrolls for search tests."""

    def __init__(self, *, height: int = 10, max_y: int = 20) -> None:
        self._height = height
        self._max_y = max_y
        self.scroll_y = 0.0
        self.calls: list[int] = []

    @property
    def scrollable_content_region(self) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(height=self._height, width=80)

    @property
    def max_scroll_y(self) -> int:
        return self._max_y

    def scroll_relative(self, *, y: int = 0, animate: bool = False) -> None:
        del animate
        self.calls.append(int(y))
        self.scroll_y = float(min(self._max_y, max(0, int(self.scroll_y) + int(y))))


class _FakeDeckPanel:
    """Deck panel double exposing only the search overlay scroll."""

    def __init__(self, scroll: _FakeOverlayScroll) -> None:
        self._scroll = scroll

    def search_scroll(self) -> _FakeOverlayScroll:
        return self._scroll


class _SearchScrollHost:
    """Bind the real metadata-search key handler without starting AceApp."""

    def __init__(
        self,
        *,
        detail: Any,
        deck_panel: Any,
        down_key: str,
        up_key: str,
        mode: str,
        query: str = "",
    ) -> None:
        from types import SimpleNamespace
        from textual.events import Key  # noqa: F401 (kept for Key construction below)

        from sase.ace.tui.widgets.vim_search_controller import VimSearchController

        self._detail = detail
        self._deck_panel = deck_panel
        self._keymap_registry = SimpleNamespace(
            app=SimpleNamespace(
                scroll_detail_down=down_key,
                scroll_detail_up=up_key,
                search_reverse="ctrl+r",
            )
        )
        self._agent_metadata_search = VimSearchController(self)
        self._agent_metadata_search.mode = mode  # type: ignore[assignment]
        self._agent_metadata_search.query = query
        self._Key = Key

    def _agent_detail(self) -> Any:
        return self._detail

    def _agent_metadata_search_deck_panel(self) -> Any:
        return self._deck_panel

    # VimSearchController host protocol no-ops for scroll-key handling.
    def vim_search_corpus(self) -> str:
        return ""

    def vim_search_origin_scroll(self) -> tuple[int, int]:
        return (0, 0)

    def vim_search_overlay_viewport(self) -> Any:
        from sase.ace.tui.widgets.vim_search_controller import SearchViewport

        return SearchViewport(scroll_x=0, scroll_y=0, width=0, height=0)

    def vim_search_started(self) -> None:
        return None

    def vim_search_exited(self, *, refresh: bool) -> None:
        del refresh
        return None

    def vim_search_show_overlay(self) -> None:
        return None

    def vim_search_hide_overlay(self) -> None:
        return None

    def vim_search_paint_overlay(self, content: Any) -> None:
        del content
        return None

    def vim_search_command_width(self) -> int:
        return 0

    def vim_search_paint_command_line(self, content: Any, mode: Any) -> None:
        del content, mode
        return None

    def vim_search_scroll_overlay(self, *, x: int, y: int) -> None:
        del x, y
        return None

    def vim_search_restore_scroll(self, *, x: int, y: int) -> None:
        del x, y
        return None

    def vim_search_focus_overlay(self) -> None:
        return None

    def vim_search_focus_native(self) -> None:
        return None

    def vim_search_notify(self, message: str) -> None:
        del message
        return None

    def key_event(self, key: str) -> Any:
        return self._Key(key, None)

    def _try_scroll_expanded_header_for_key(self, key: str) -> bool:
        from sase.ace.tui.actions.agents._metadata_search import (
            AgentMetadataSearchMixin,
        )

        return AgentMetadataSearchMixin._try_scroll_expanded_header_for_key(self, key)

    def _scroll_agent_metadata_search(self, key: str) -> bool:
        from sase.ace.tui.actions.agents._metadata_search import (
            AgentMetadataSearchMixin,
        )

        return AgentMetadataSearchMixin._scroll_agent_metadata_search(self, key)

    def handle(self, key: str) -> bool:
        from sase.ace.tui.actions.agents._metadata_search import (
            AgentMetadataSearchMixin,
        )

        return AgentMetadataSearchMixin._handle_agent_metadata_search_key(
            self,
            self.key_event(key),  # type: ignore[arg-type]
        )


async def _show_search_header_overflow(
    detail: Any, tmp_path: Any, pilot: Any, *, name: str
) -> Any:
    """Show a long artifact and expand it so the header genuinely overflows."""
    import dataclasses

    from sase.ace.tui.widgets.agent_detail import AgentDetail
    from tests.ace.tui.widgets._agent_display_helpers import make_artifact_agent

    assert isinstance(detail, AgentDetail)
    raw = (
        "Can you help me start rendering the AGENT XPROMPT section in the sticky "
        "header above the agent data deck panel? Make sure that we provide a good "
        "preview of the contents in this section.\n"
        "\n"
        "- first list item explains the quote bar\n"
        "- second list item explains the row budget\n"
        "```\n"
        "some fenced code block line\n"
        "```\n"
        "A final hard-wrapped prose paragraph keeps going so the preview budget "
        "overflows and the border subtitle names the hidden line count."
    )
    direc = tmp_path / name
    direc.mkdir(exist_ok=True)
    agent = make_artifact_agent(direc, status="DONE", raw_xprompt=raw)
    agent = dataclasses.replace(agent, cl_name=f"cl-{name}", raw_suffix=name)
    detail.update_display(agent)
    await pilot.pause()
    panel = detail.query_one("#agent-header-panel", AgentHeaderPanel)
    if not panel.is_expanded:
        assert detail.toggle_header_expanded() is True
        await pilot.pause()
    assert int(panel.max_scroll_y) > 0
    assert panel.is_header_scrollable() is True
    return panel


async def test_committed_search_header_takes_priority_over_overlay(
    tmp_path: Any,
) -> None:
    """Committed search routes configured Ctrl+D/U to an overflowing header first."""
    from textual.app import App, ComposeResult

    from sase.ace.tui.widgets.agent_detail import AgentDetail

    class _DetailApp(App[None]):
        def compose(self) -> ComposeResult:
            yield AgentDetail(id="agent-detail-panel")

    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = await _show_search_header_overflow(
            detail, tmp_path, pilot, name="committed-header"
        )
        down_key, up_key = _configured_scroll_keys()
        overlay = _FakeOverlayScroll(height=10, max_y=20)
        host = _SearchScrollHost(
            detail=detail,
            deck_panel=_FakeDeckPanel(overlay),
            down_key=down_key,
            up_key=up_key,
            mode="committed",
        )
        header_h = int(panel.scrollable_content_region.height)
        expected_step = max(1, header_h // 2)

        assert host.handle(down_key) is True
        await pilot.pause()
        assert float(panel.scroll_y) == float(expected_step)
        assert overlay.calls == []

        assert host.handle(up_key) is True
        await pilot.pause()
        assert float(panel.scroll_y) == 0.0
        assert overlay.calls == []

        detail.update_display_immediate(_make_agent(agent_name="solo-fallback"))
        await pilot.pause()
        panel = detail.query_one("#agent-header-panel", AgentHeaderPanel)
        assert int(panel.max_scroll_y) == 0
        assert panel.is_header_scrollable() is False
        assert host.handle(down_key) is True
        await pilot.pause()
        assert overlay.calls == [5]


async def test_typing_search_header_takes_priority(tmp_path: Any) -> None:
    """Typing search routes configured Ctrl+D/U to an overflowing header first."""
    from textual.app import App, ComposeResult

    from sase.ace.tui.widgets.agent_detail import AgentDetail

    class _DetailApp(App[None]):
        def compose(self) -> ComposeResult:
            yield AgentDetail(id="agent-detail-panel")

    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = await _show_search_header_overflow(
            detail, tmp_path, pilot, name="typing-header"
        )
        down_key, up_key = _configured_scroll_keys()
        overlay = _FakeOverlayScroll(height=10, max_y=20)
        host = _SearchScrollHost(
            detail=detail,
            deck_panel=_FakeDeckPanel(overlay),
            down_key=down_key,
            up_key=up_key,
            mode="typing",
            query="needle",
        )
        header_h = int(panel.scrollable_content_region.height)
        expected_step = max(1, header_h // 2)

        assert host.handle(down_key) is True
        await pilot.pause()
        assert float(panel.scroll_y) == float(expected_step)
        assert overlay.calls == []
        assert host._agent_metadata_search.query == "needle"
        assert host._agent_metadata_search.mode == "typing"

        detail.update_display_immediate(_make_agent(agent_name="solo-typing"))
        await pilot.pause()
        panel = detail.query_one("#agent-header-panel", AgentHeaderPanel)
        assert panel.is_header_scrollable() is False
        header_y = float(panel.scroll_y)
        assert host.handle(down_key) is True
        await pilot.pause()
        assert float(panel.scroll_y) == header_y
        assert overlay.calls == []
        assert host._agent_metadata_search.query == "needle"
        assert host._agent_metadata_search.mode == "typing"


def test_search_help_subtitle_drops_optional_hints_to_fit() -> None:
    from sase.ace.tui.actions.agents._deck_search_host import search_help_subtitle

    full = "[n/N] next/prev  [/] reverse  [y] yank  [esc/q] close"
    assert search_help_subtitle(False, "/", 0) == full
    assert search_help_subtitle(False, "/", len(full)) == full
    assert search_help_subtitle(False, "/", len(full) - 1) == (
        "[n/N] next/prev  [esc/q] close"
    )
    assert search_help_subtitle(False, "/", 20) == "[esc/q] close"
    assert search_help_subtitle(False, "/", 3) == "[esc/q] close"
    assert search_help_subtitle(True, "/", 80) == (
        "[enter] accept  [/] reverse  [esc/^c] cancel"
    )
    assert search_help_subtitle(True, "/", 35) == "[enter] accept  [esc/^c] cancel"
    assert search_help_subtitle(True, "/", 16) == "[esc/^c] cancel"
