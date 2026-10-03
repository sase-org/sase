"""Controller tests for the optional match-painting host hook.

Hosts with ``vim_search_paint_matches`` receive sorted match spans and
the current index, and never pay for a full styled ``Text`` copy. Hosts
without it — such as the ACE agent-metadata search — keep exactly
today's full-text overlay path. Repeats reuse the cached spans while the
query and corpus are unchanged instead of re-running the regex.
"""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.widgets import vim_search_controller as controller_module
from sase.ace.tui.widgets._vim_search import SearchSpan
from sase.ace.tui.widgets.vim_search_controller import (
    MATCH_STYLE,
    SearchViewport,
    VimSearchController,
    VimSearchMode,
)


class _MatchHost:
    """Host with the new match-painting hook."""

    def __init__(self, corpus: str) -> None:
        self.corpus = corpus
        self.viewport = SearchViewport(0, 0, 80, 20)
        self.paints: list[tuple[tuple[SearchSpan, ...], int | None]] = []
        self.overlay_texts: list[Text] = []
        self.notifications: list[str] = []

    def vim_search_corpus(self) -> str:
        return self.corpus

    def vim_search_origin_scroll(self) -> tuple[int, int]:
        return (0, 0)

    def vim_search_overlay_viewport(self) -> SearchViewport:
        return self.viewport

    def vim_search_started(self) -> None:
        pass

    def vim_search_exited(self, *, refresh: bool) -> None:
        pass

    def vim_search_show_overlay(self) -> None:
        pass

    def vim_search_hide_overlay(self) -> None:
        pass

    def vim_search_paint_overlay(self, content: Text) -> None:
        self.overlay_texts.append(content)

    def vim_search_paint_matches(
        self,
        match_spans: tuple[SearchSpan, ...],
        current_index: int | None,
    ) -> None:
        self.paints.append((tuple(match_spans), current_index))

    def vim_search_command_width(self) -> int:
        return 80

    def vim_search_paint_command_line(self, content: Text, mode: VimSearchMode) -> None:
        pass

    def vim_search_scroll_overlay(self, *, x: int, y: int) -> None:
        self.viewport = SearchViewport(
            scroll_x=x,
            scroll_y=y,
            width=self.viewport.width,
            height=self.viewport.height,
        )

    def vim_search_restore_scroll(self, *, x: int, y: int) -> None:
        pass

    def vim_search_focus_overlay(self) -> None:
        pass

    def vim_search_focus_native(self) -> None:
        pass

    def vim_search_notify(self, message: str) -> None:
        self.notifications.append(message)


class _PlainHost(_MatchHost):
    """Host without the hook: the legacy full-text overlay path."""

    vim_search_paint_matches = None  # type: ignore[assignment]


def _type_query(controller: VimSearchController, query: str) -> None:
    for character in query:
        assert controller.handle_key(character, character) == "consumed"


def test_match_hook_receives_spans_and_index_without_full_text() -> None:
    host = _MatchHost("alpha beta alpha")
    controller = VimSearchController(host)

    assert controller.start("forward")
    assert host.paints == [((), None)]
    _type_query(controller, "alpha")

    assert host.overlay_texts == []
    spans, current_index = host.paints[-1]
    assert spans == tuple(controller.match_spans)
    assert len(spans) == 2
    selection = controller.current_selection
    assert selection is not None
    assert current_index == selection.index


def test_hosts_without_the_hook_keep_the_full_text_path() -> None:
    host = _PlainHost("alpha beta alpha")
    controller = VimSearchController(host)

    assert controller.start("forward")
    _type_query(controller, "alpha")

    assert host.paints == []
    assert host.overlay_texts
    overlay = host.overlay_texts[-1]
    assert overlay.plain == "alpha beta alpha"
    assert any(str(span.style) == MATCH_STYLE for span in overlay.spans)


def test_repeat_reuses_cached_spans(
    monkeypatch: object,
) -> None:
    calls: list[str] = []
    original = controller_module.find_search_matches

    def _counting(text: str, query: str, **kwargs: object) -> tuple:
        calls.append(query)
        return original(text, query, **kwargs)

    monkeypatch.setattr(  # type: ignore[attr-defined]
        controller_module, "find_search_matches", _counting
    )
    host = _MatchHost("alpha beta alpha")
    controller = VimSearchController(host)
    controller.start("forward")
    _type_query(controller, "alpha")
    controller.handle_key("enter", None)
    measured = len(calls)

    controller.repeat()
    controller.repeat()
    controller.repeat(reverse=True)

    assert len(calls) == measured
    assert tuple(controller.match_spans) == host.paints[-1][0]


def test_direction_toggle_while_typing_reuses_spans(
    monkeypatch: object,
) -> None:
    calls: list[str] = []
    original = controller_module.find_search_matches

    def _counting(text: str, query: str, **kwargs: object) -> tuple:
        calls.append(query)
        return original(text, query, **kwargs)

    monkeypatch.setattr(  # type: ignore[attr-defined]
        controller_module, "find_search_matches", _counting
    )
    host = _MatchHost(
        "alpha\nmiddle\nalpha",
    )
    controller = VimSearchController(host)
    controller.start("forward")
    _type_query(controller, "alpha")
    measured = len(calls)

    assert controller.toggle_direction()

    assert len(calls) == measured
    assert controller.direction == "reverse"
    assert tuple(controller.match_spans) == host.paints[-1][0]
