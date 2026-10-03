"""Pager split keys inside ACE: the modal pager owns split, focus, swap, close, turn.

ACE binds the same keys to the Agents-tab deck split as non-priority app
bindings. Under the ``PagerScreen`` modal those bindings are cut from the
chain, so the keys must split and focus the pager while the Agents deck
underneath stays single.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding

from sase.ace.tui.bindings import DEFAULT_BINDINGS
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckLayout
from sase.pager import PagerScreen
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.split import PagerSplitLayout
from tests.ace.tui.widgets._agent_display_helpers import make_artifact_agent
from tests.ace.tui.widgets.decks._deck_spread_test_helpers import pin_paged

_ROOT = Path(__file__).resolve().parents[4]
_DECK_ACTIONS = frozenset(
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


class _AgentsDeckHost(App[None]):
    """An Agents-tab deck host carrying ACE's own deck split bindings."""

    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"
    BINDINGS = [
        binding
        for binding in DEFAULT_BINDINGS
        if isinstance(binding, Binding) and binding.action in _DECK_ACTIONS
    ]

    def __init__(self) -> None:
        super().__init__()
        self.deck_action_calls: list[str] = []

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")

    @property
    def detail(self) -> AgentDetail:
        return self.query_one("#agent-detail-panel", AgentDetail)

    def action_toggle_deck_split_below(self) -> None:
        self.deck_action_calls.append("toggle_deck_split_below")
        self.detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)

    def action_toggle_deck_split_right(self) -> None:
        self.deck_action_calls.append("toggle_deck_split_right")
        self.detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)

    def action_toggle_deck_focus(self) -> None:
        self.deck_action_calls.append("toggle_deck_focus")
        self.detail.toggle_deck_focus()

    def action_toggle_deck_focus_reverse(self) -> None:
        self.deck_action_calls.append("toggle_deck_focus_reverse")
        self.detail.toggle_deck_focus_reverse()

    def action_swap_deck_panel_next(self) -> None:
        self.deck_action_calls.append("swap_deck_panel_next")
        self.detail.swap_deck_panel(+1)

    def action_swap_deck_panel_prev(self) -> None:
        self.deck_action_calls.append("swap_deck_panel_prev")
        self.detail.swap_deck_panel(-1)

    def action_close_deck_panel(self) -> None:
        self.deck_action_calls.append("close_deck_panel")
        self.detail.close_deck_panel()

    def action_turn_deck_layout(self) -> None:
        self.deck_action_calls.append("turn_deck_layout")
        self.detail.turn_deck_layout()


def _document() -> PagerDocument:
    section = PagerSection(
        identity="file:/tmp/notes.py",
        title="notes.py",
        kind="file",
        body="".join(f"line {index}\n" for index in range(40)),
    )
    return PagerDocument(sections=(section,), title="notes.py", origin=PagerOrigin.FILE)


def _assert_deck_untouched(app: _AgentsDeckHost) -> None:
    assert app.detail.deck_layout is DeckLayout.SINGLE
    assert app.deck_action_calls == []


async def test_pager_modal_owns_split_keys_and_agents_deck_stays_single(
    tmp_path: Path,
) -> None:
    app = _AgentsDeckHost()
    pin_paged(app)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.detail.update_display(make_artifact_agent(tmp_path, status="DONE"))
        await pilot.pause()
        # Without the pager, the host bindings really do split the deck.
        await pilot.press("backslash")
        await pilot.pause()
        assert app.detail.deck_layout is DeckLayout.TOP_BOTTOM
        await pilot.press("backslash")
        await pilot.pause()
        assert app.detail.deck_layout is DeckLayout.SINGLE
        app.deck_action_calls.clear()

        screen = PagerScreen(_document())
        app.push_screen(screen)
        await pilot.pause()

        await pilot.press("backslash")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 2
        assert screen._split_state.layout is PagerSplitLayout.BELOW
        assert screen._focused_index == 1
        _assert_deck_untouched(app)

        # The other split key nests a third pane (it no longer rotates).
        await pilot.press("vertical_line")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 3
        assert len(screen._grid.panes) == 3
        _assert_deck_untouched(app)

        # ctrl+t turns the three-pane layout.
        before_grid = screen._grid
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert len(screen.views) == 3
        assert screen._grid != before_grid
        _assert_deck_untouched(app)

        # Focus ring in both directions reaches the pager.
        await pilot.press("ctrl+f")
        await pilot.pause()
        focused_after_next = screen._focused_index
        _assert_deck_untouched(app)
        await pilot.press("ctrl+b")
        await pilot.pause()
        assert screen._focused_index != focused_after_next
        _assert_deck_untouched(app)

        # Swap in both directions (primary chords and single-key aliases).
        views_before = set(screen.views)
        await pilot.press("ctrl+shift+f")
        await pilot.pause()
        assert set(screen.views) == views_before
        assert len(screen.views) == 3
        _assert_deck_untouched(app)
        await pilot.press("greater_than_sign")
        await pilot.pause()
        assert set(screen.views) == views_before
        _assert_deck_untouched(app)
        await pilot.press("ctrl+shift+b")
        await pilot.pause()
        assert set(screen.views) == views_before
        _assert_deck_untouched(app)
        await pilot.press("less_than_sign")
        await pilot.pause()
        assert set(screen.views) == views_before
        _assert_deck_untouched(app)

        # Close aliases each close the focused pane; the deck never splits
        # and no deck action fires.
        await pilot.press("ctrl+x")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 2
        _assert_deck_untouched(app)
        await pilot.press("ctrl+shift+d")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 1
        assert screen._split_state.layout is PagerSplitLayout.SINGLE
        _assert_deck_untouched(app)

        assert app.screen is screen
        assert app.detail.deck_layout is DeckLayout.SINGLE
