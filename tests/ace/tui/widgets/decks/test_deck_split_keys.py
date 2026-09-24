"""Key gating, footer and viewport tests for deck splits."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult

from sase.ace.tui.widgets import KeybindingFooter
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckLayout
from tests.ace.tui.widgets.decks._deck_spread_test_helpers import pin_paged
from tests.ace.tui.widgets._agent_display_helpers import make_artifact_agent

_ROOT = Path(__file__).resolve().parents[5]


class _DetailApp(App[None]):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


def _check(action: str, tab: str) -> bool | None:
    from sase.ace.tui._app_action_availability import check_app_action

    class _App:
        current_tab = tab
        _prompt_input_active = lambda self: False  # noqa: E731
        _screen_stack: tuple[object, ...] = ()

        def __getattr__(self, _name: str) -> object:
            return None

    app = _App()
    return check_app_action(app, action, (), lambda _a, _p: None)


def test_layout_actions_gated_to_agents_decks() -> None:
    assert _check("toggle_deck_split_below", "agents") is None
    assert _check("toggle_deck_split_below", "artifacts") is False
    assert _check("toggle_deck_focus", "agents") is False  # SINGLE, no split
    assert _check("grow_deck_panel", "services") is False
    assert _check("shrink_deck_panel", "artifacts") is False


def test_scroll_prompt_hidden_on_agents_while_decks_on() -> None:
    assert _check("scroll_prompt_down", "agents") is False
    assert _check("scroll_prompt_up", "agents") is False
    assert _check("scroll_prompt_down", "services") is None


def test_footer_deck_entries() -> None:
    from sase.ace.tui.models.agent import Agent, AgentType

    footer = KeybindingFooter()
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
    )
    base = footer._compute_agent_bindings(agent)
    assert not any(label in {"cards", "other panel", "resize"} for _, label in base)
    split = footer._compute_agent_bindings(agent, deck_split=True, deck_card_count=2)
    labels = [label for _, label in split]
    assert "cards" in labels
    assert "other panel" in labels
    assert "resize" in labels
    single_multi = footer._compute_agent_bindings(
        agent, deck_split=False, deck_card_count=3
    )
    labels = [label for _, label in single_multi]
    assert "cards" in labels
    assert "other panel" not in labels
    single_one = footer._compute_agent_bindings(
        agent, deck_split=False, deck_card_count=1
    )
    assert not any(
        label in {"cards", "other panel", "resize"} for _, label in single_one
    )


def test_rerender_for_viewport_only_images() -> None:
    from sase.ace.tui.widgets.file_panel import AgentFilePanel

    panel = AgentFilePanel()
    calls: list[str] = []
    panel._display_static_image = lambda path: calls.append(path)  # type: ignore[method-assign]
    panel._content_mode = "diff"
    panel._static_header_path = "/tmp/a.png"
    panel.rerender_for_viewport()
    assert calls == []
    panel._content_mode = "image"
    panel.rerender_for_viewport()
    assert calls == ["/tmp/a.png"]


async def test_click_focuses_other_panel(tmp_path: Path) -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)
        await pilot.pause()
        assert detail.deck_area.state.focused == 1
        area = detail.deck_area
        from sase.ace.tui.widgets.decks.panel import DeckPanelFocusRequested

        area.on_deck_panel_focus_requested(DeckPanelFocusRequested(0))
        await pilot.pause()
        assert detail.deck_area.state.focused == 0
        # Same index is a no-op.
        area.on_deck_panel_focus_requested(DeckPanelFocusRequested(0))
        assert detail.deck_area.state.focused == 0
