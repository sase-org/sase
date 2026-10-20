"""Shared apps and fixtures for deck split pilot tests."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding

from sase.ace.tui.actions.agents._deck_layout_actions import AgentDeckLayoutActionsMixin
from sase.ace.tui.bindings import DEFAULT_BINDINGS
from sase.ace.tui.widgets.agent_detail import AgentDetail
from tests.ace.tui.widgets.decks._deck_spread_test_helpers import pin_paged
from tests.ace.tui.widgets._agent_display_helpers import make_agent, make_artifact_agent

_DECK_KEY_ACTIONS = frozenset(
    {
        "toggle_deck_split_below",
        "toggle_deck_split_right",
        "toggle_deck_focus",
        "toggle_deck_focus_reverse",
        "swap_deck_panel_next",
        "swap_deck_panel_prev",
        "close_deck_panel",
        "turn_deck_layout",
    }
)

_ROOT = Path(__file__).resolve().parents[5]


class DeckKeyApp(AgentDeckLayoutActionsMixin, App[None]):
    """Detail host with live deck key bindings for real key presses."""

    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"
    BINDINGS = [
        binding
        for binding in DEFAULT_BINDINGS
        if isinstance(binding, Binding) and binding.action in _DECK_KEY_ACTIONS
    ]

    current_tab: str = "agents"

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


class DetailApp(App[None]):
    """Agent detail host for deck split tests."""

    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")
