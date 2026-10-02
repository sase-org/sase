"""Pager split keys inside ACE: the modal pager owns ``\\``, ``|`` and ``ctrl+f``.

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
    {"toggle_deck_split_below", "toggle_deck_split_right", "toggle_deck_focus"}
)


class _AgentsDeckHost(App[None]):
    """An Agents-tab deck host carrying ACE's own deck split bindings."""

    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"
    BINDINGS = [
        binding
        for binding in DEFAULT_BINDINGS
        if isinstance(binding, Binding) and binding.action in _DECK_ACTIONS
    ]

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")

    @property
    def detail(self) -> AgentDetail:
        return self.query_one("#agent-detail-panel", AgentDetail)

    def action_toggle_deck_split_below(self) -> None:
        self.detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)

    def action_toggle_deck_split_right(self) -> None:
        self.detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)

    def action_toggle_deck_focus(self) -> None:
        self.detail.toggle_deck_focus()


def _document() -> PagerDocument:
    section = PagerSection(
        identity="file:/tmp/notes.py",
        title="notes.py",
        kind="file",
        body="".join(f"line {index}\n" for index in range(40)),
    )
    return PagerDocument(sections=(section,), title="notes.py", origin=PagerOrigin.FILE)


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

        screen = PagerScreen(_document())
        app.push_screen(screen)
        await pilot.pause()

        await pilot.press("backslash")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 2
        assert screen._split_state.layout is PagerSplitLayout.BELOW
        assert screen._focused_index == 1

        await pilot.press("vertical_line")
        await pilot.pause()
        assert screen._split_state.layout is PagerSplitLayout.BESIDE

        await pilot.press("ctrl+f")
        await pilot.pause()
        assert screen._focused_index == 0

        assert app.screen is screen
        assert app.detail.deck_layout is DeckLayout.SINGLE
