"""Trail entries must not retain search corpora.

``PagerSearchState`` carries no corpus or line starts: both rebuild from
the entry's document on restore, so a deep trail never pins a second full
copy of document text. The remembered query, direction, matches, and
scroll anchors restore exactly.
"""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.widgets.vim_search_controller import (
    SearchViewport,
    VimSearchController,
    VimSearchMode,
    line_start_offsets,
)
from sase.pager._layout import search_corpus
from sase.pager._screen_trail import PagerTrailMixin
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.trail import PagerSearchState


class _SearchHost:
    """Minimal search-controller host backed by one pager document."""

    def __init__(self, document: PagerDocument) -> None:
        self.document = document
        self._search = VimSearchController(self)
        self.overlay = Text()
        self.command = Text()
        self.shown = 0
        self.hidden = 0

    # Methods the trail mixin calls directly.
    _current_search_state = PagerTrailMixin._current_search_state
    _restore_search_state = PagerTrailMixin._restore_search_state

    def vim_search_corpus(self) -> str:
        return search_corpus(self.document)

    def vim_search_origin_scroll(self) -> tuple[int, int]:
        return (0, 0)

    def vim_search_overlay_viewport(self) -> SearchViewport:
        return SearchViewport(0, 0, 80, 20)

    def vim_search_started(self) -> None:
        pass

    def vim_search_exited(self, *, refresh: bool) -> None:
        pass

    def vim_search_show_overlay(self) -> None:
        self.shown += 1

    def vim_search_hide_overlay(self) -> None:
        self.hidden += 1

    def vim_search_paint_overlay(self, content: Text) -> None:
        self.overlay = content

    def vim_search_command_width(self) -> int:
        return 80

    def vim_search_paint_command_line(self, content: Text, mode: VimSearchMode) -> None:
        self.command = content

    def vim_search_scroll_overlay(self, *, x: int, y: int) -> None:
        pass

    def vim_search_restore_scroll(self, *, x: int, y: int) -> None:
        pass

    def vim_search_focus_overlay(self) -> None:
        pass

    def vim_search_focus_native(self) -> None:
        pass

    def vim_search_notify(self, message: str) -> None:
        pass


def _host() -> _SearchHost:
    section = PagerSection(
        identity="file:/tmp/notes.txt",
        title="notes.txt",
        kind="file",
        body="top\nneedle here\nbottom needle\n",
    )
    document = PagerDocument(
        sections=(section,), title="notes", origin=PagerOrigin.FILE
    )
    return _SearchHost(document)


def _commit_search(host: _SearchHost, query: str) -> None:
    assert host._search.start("forward")
    for character in query:
        host._search.handle_key(character, character)
    host._search.handle_key("enter", None)
    assert host._search.mode == "committed"


def test_search_state_carries_no_corpus_copy() -> None:
    """Snapshots keep query/matches but never the corpus or line starts."""
    host = _host()
    _commit_search(host, "needle")

    state = host._current_search_state()

    assert isinstance(state, PagerSearchState)
    assert not hasattr(state, "corpus")
    assert not hasattr(state, "line_starts")
    assert state.mode == "committed"
    assert state.query == "needle"
    assert len(state.match_spans) == 2


def test_restore_rebuilds_corpus_from_the_entry_document() -> None:
    """Restoring an active search rebuilds identical search state."""
    host = _host()
    _commit_search(host, "needle")
    state = host._current_search_state()
    expected_corpus = search_corpus(host.document)
    expected_spans = tuple(host._search.match_spans)
    expected_selection = host._search.current_selection

    host._search.exit(restore_scroll=False, refresh=False)
    assert host._search.corpus == ""
    shown = host.shown
    host._restore_search_state(state)

    assert host._search.mode == "committed"
    assert host._search.corpus == expected_corpus
    assert host._search.line_starts == line_start_offsets(expected_corpus)
    assert host._search.match_spans == expected_spans
    assert host._search.current_selection == expected_selection
    assert host.shown == shown + 1
    # The overlay repaints the rebuilt corpus with both matches marked.
    assert host.overlay.plain == expected_corpus


def test_restore_of_idle_search_keeps_the_controller_empty() -> None:
    """Restoring an idle search leaves no corpus behind."""
    host = _host()
    state = host._current_search_state()
    assert state.mode == "off"

    host._restore_search_state(state)

    assert host._search.mode == "off"
    assert host._search.corpus == ""
    assert host._search.line_starts == (0,)
