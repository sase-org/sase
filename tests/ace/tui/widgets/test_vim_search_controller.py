"""Focused unit tests for the shared Vim-style search controller."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.widgets._vim_search import SearchDirection
from sase.ace.tui.widgets.vim_search_controller import (
    SearchViewport,
    VimSearchController,
    VimSearchMode,
    line_start_offsets,
    offset_for_row,
    offset_to_row_col,
)


class _RecordingHost:
    def __init__(
        self,
        corpus: str,
        *,
        origin: tuple[int, int] = (0, 0),
        viewport: SearchViewport | None = None,
    ) -> None:
        self.corpus = corpus
        self.origin = origin
        self.viewport = viewport or SearchViewport(0, 0, 80, 20)
        self.started = 0
        self.exited: list[bool] = []
        self.overlay_visible = False
        self.overlay = Text()
        self.command = Text()
        self.command_mode: VimSearchMode = "off"
        self.scrolls: list[tuple[int, int]] = []
        self.restores: list[tuple[int, int]] = []
        self.focused: list[str] = []
        self.notifications: list[str] = []

    def vim_search_corpus(self) -> str:
        return self.corpus

    def vim_search_origin_scroll(self) -> tuple[int, int]:
        return self.origin

    def vim_search_overlay_viewport(self) -> SearchViewport:
        return self.viewport

    def vim_search_started(self) -> None:
        self.started += 1

    def vim_search_exited(self, *, refresh: bool) -> None:
        self.exited.append(refresh)

    def vim_search_show_overlay(self) -> None:
        self.overlay_visible = True

    def vim_search_hide_overlay(self) -> None:
        self.overlay_visible = False

    def vim_search_paint_overlay(self, content: Text) -> None:
        self.overlay = content

    def vim_search_command_width(self) -> int:
        return 80

    def vim_search_paint_command_line(
        self,
        content: Text,
        mode: VimSearchMode,
    ) -> None:
        self.command = content
        self.command_mode = mode

    def vim_search_scroll_overlay(self, *, x: int, y: int) -> None:
        self.scrolls.append((x, y))
        self.viewport = SearchViewport(
            scroll_x=x,
            scroll_y=y,
            width=self.viewport.width,
            height=self.viewport.height,
        )

    def vim_search_restore_scroll(self, *, x: int, y: int) -> None:
        self.restores.append((x, y))
        self.focused.append("native")

    def vim_search_focus_overlay(self) -> None:
        self.focused.append("overlay")

    def vim_search_focus_native(self) -> None:
        self.focused.append("native")

    def vim_search_notify(self, message: str) -> None:
        self.notifications.append(message)


def _type_query(controller: VimSearchController, query: str) -> None:
    for character in query:
        assert controller.handle_key(character, character) == "consumed"


def test_controller_transitions_from_typing_to_committed_and_off() -> None:
    host = _RecordingHost("alpha beta alpha")
    controller = VimSearchController(host)

    assert controller.start("forward")
    assert controller.mode == "typing"
    assert host.overlay_visible
    assert host.started == 1

    _type_query(controller, "alpha")
    assert controller.current_selection is not None
    assert controller.current_selection.index == 0
    assert "[1/2]" in host.command.plain

    assert controller.handle_key("enter", None) == "consumed"
    assert controller.mode == "committed"
    assert controller.last_search == ("alpha", "forward")
    assert host.command_mode == "committed"

    host.viewport = SearchViewport(4, 6, 80, 20)
    assert controller.handle_key("escape", None) == "consumed"
    assert controller.mode == "off"
    assert not host.overlay_visible
    assert host.exited == [True]
    assert host.restores == [(4, 6)]


def test_controller_preview_includes_match_exactly_at_origin() -> None:
    corpus = "zero\nalpha\nalpha"
    directions: tuple[SearchDirection, ...] = ("forward", "reverse")
    for direction in directions:
        host = _RecordingHost(corpus, origin=(0, 1))
        controller = VimSearchController(host)

        controller.start(direction)
        _type_query(controller, "alpha")

        assert controller.origin_offset == 5
        assert controller.current_selection is not None
        assert controller.current_selection.index == 0
        assert not controller.current_selection.wrapped


def test_controller_repeat_reports_forward_and_reverse_wraps() -> None:
    host = _RecordingHost("alpha beta alpha")
    controller = VimSearchController(host)
    controller.start("forward")
    _type_query(controller, "alpha")
    controller.handle_key("enter", None)

    controller.repeat()
    assert controller.current_selection is not None
    assert controller.current_selection.index == 1
    assert host.notifications == []

    controller.repeat()
    assert controller.current_selection is not None
    assert controller.current_selection.index == 0
    assert host.notifications[-1] == "search hit BOTTOM, continuing at TOP"

    controller.repeat(reverse=True)
    assert controller.current_selection is not None
    assert controller.current_selection.index == 1
    assert host.notifications[-1] == "search hit TOP, continuing at BOTTOM"


def test_controller_toggle_direction_while_typing_preserves_frozen_state() -> None:
    host = _RecordingHost("alpha\nmiddle\nalpha", origin=(0, 1))
    controller = VimSearchController(host)

    controller.start("forward")
    _type_query(controller, "alpha")
    assert controller.current_selection is not None
    assert controller.current_selection.index == 1
    original_corpus = controller.corpus
    original_spans = controller.match_spans

    assert controller.toggle_direction()

    assert controller.mode == "typing"
    assert controller.direction == "reverse"
    assert controller.query == "alpha"
    assert controller.corpus == original_corpus
    assert controller.match_spans == original_spans
    assert controller.current_selection is not None
    assert controller.current_selection.index == 0
    assert host.started == 1
    assert "?alpha" in host.command.plain


def test_controller_toggle_direction_after_commit_updates_repeat_order() -> None:
    host = _RecordingHost("alpha beta alpha")
    controller = VimSearchController(host)

    controller.start("forward")
    _type_query(controller, "alpha")
    controller.handle_key("enter", None)
    assert controller.current_selection is not None
    assert controller.current_selection.index == 0

    assert controller.toggle_direction()

    assert controller.mode == "committed"
    assert controller.direction == "reverse"
    assert controller.last_search == ("alpha", "reverse")
    assert controller.current_selection is not None
    assert controller.current_selection.index == 0

    controller.repeat()
    assert controller.current_selection is not None
    assert controller.current_selection.index == 1


def test_controller_question_mark_reverse_restart_can_be_disabled() -> None:
    host = _RecordingHost("alpha beta alpha")
    controller = VimSearchController(host)
    controller.start("forward")
    _type_query(controller, "alpha")
    controller.handle_key("enter", None)

    disposition = controller.handle_key(
        "question_mark",
        "?",
        passthrough_exit_keys=None,
        allow_question_mark_reverse=False,
    )

    assert disposition == "passthrough"
    assert controller.mode == "off"
    assert host.exited == [False]


def test_controller_question_mark_reverse_restart_stays_enabled_by_default() -> None:
    host = _RecordingHost("alpha beta alpha")
    controller = VimSearchController(host)
    controller.start("forward")
    _type_query(controller, "alpha")
    controller.handle_key("enter", None)

    assert (
        controller.handle_key("question_mark", "?", passthrough_exit_keys=None)
        == "consumed"
    )

    assert controller.mode == "typing"
    assert controller.direction == "reverse"
    assert controller.query == ""
    assert host.started == 2


def test_controller_scrolls_to_match_with_context_and_horizontal_margin() -> None:
    corpus = "\n".join(["short"] * 8 + ["abcdefghijklmnop needle"])
    host = _RecordingHost(
        corpus,
        viewport=SearchViewport(scroll_x=0, scroll_y=0, width=10, height=4),
    )
    controller = VimSearchController(host)

    controller.start("forward")
    _type_query(controller, "needle")

    assert host.scrolls[-1] == (13, 5)


def test_controller_structural_key_exits_and_passes_through() -> None:
    host = _RecordingHost("alpha")
    controller = VimSearchController(host)
    controller.start("forward")
    _type_query(controller, "alpha")
    controller.handle_key("enter", None)

    disposition = controller.handle_key(
        "j",
        None,
        passthrough_exit_keys={"j"},
    )

    assert disposition == "passthrough"
    assert controller.mode == "off"
    assert host.exited == [False]
    assert host.restores == []
    assert host.focused[-1] == "native"


def test_controller_empty_corpus_notifies_without_entering_search() -> None:
    host = _RecordingHost("")
    controller = VimSearchController(host)

    assert not controller.start("forward")
    assert controller.mode == "off"
    assert not host.overlay_visible
    assert host.notifications == ["Nothing to search"]


def test_controller_offset_helpers_map_logical_lines() -> None:
    starts = line_start_offsets("alpha\nbeta\ngamma")

    assert starts == (0, 6, 11)
    assert offset_to_row_col(starts, 0) == (0, 0)
    assert offset_to_row_col(starts, 6) == (1, 0)
    assert offset_to_row_col(starts, 10) == (1, 4)
    assert offset_for_row(starts, 2) == 11
    assert offset_for_row(starts, 200) == 11
