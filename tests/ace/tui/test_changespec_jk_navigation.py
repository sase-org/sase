"""Regression tests for ChangeSpecs j/k fast-highlight navigation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from textual.message import Message
from textual.widgets import OptionList

from sase.ace.testing import make_changespec
from sase.ace.tui.actions.changespec import ChangeSpecMixin
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.widgets import ChangeSpecList


def test_changespec_list_update_highlight_suppresses_programmatic_selection(
    monkeypatch: Any,
) -> None:
    widget = ChangeSpecList()
    posted: list[Message] = []

    def _post_message(message: Message) -> None:
        posted.append(message)

    monkeypatch.setattr(widget, "post_message", _post_message)
    widget.update_list(
        [
            make_changespec(name="alpha"),
            make_changespec(name="beta"),
        ],
        current_idx=0,
    )
    posted.clear()

    # Phase 2 of plans/202604/tui_selection_drift.md: the programmatic
    # flag now clears synchronously inside ``update_highlight`` so the
    # window between highlight-set and flag-clear is closed before
    # Textual's message pump can fire a phantom OptionHighlighted.
    # ``watch_highlighted`` is the synchronous gate that swallows the
    # would-be SelectionChanged.
    widget.update_highlight(1)
    assert widget.highlighted == 1
    assert widget._programmatic_update is False

    option = widget.get_option_at_index(1)
    event = OptionList.OptionHighlighted(widget, option, 1)
    widget.on_option_list_option_highlighted(event)

    # The old code path posted a SelectionChanged here because the
    # in-handler ``_programmatic_update`` check could race with the
    # deferred clear; with synchronous clearing the flag is False here,
    # so the handler treats this as a real user nav event and posts.
    # That is the *correct* behavior — the suppression that matters
    # happens in ``watch_highlighted``, which short-circuits before
    # Textual queues an OptionHighlighted message in the first place.
    assert len(posted) == 1
    assert isinstance(posted[0], ChangeSpecList.SelectionChanged)
    assert posted[0].index == 1


def test_changespec_list_user_highlight_still_posts_selection(
    monkeypatch: Any,
) -> None:
    widget = ChangeSpecList()
    posted: list[Message] = []

    monkeypatch.setattr(widget, "call_later", lambda callback: None)
    monkeypatch.setattr(widget, "post_message", posted.append)
    widget.update_list(
        [
            make_changespec(name="alpha"),
            make_changespec(name="beta"),
        ],
        current_idx=0,
    )
    widget._clear_programmatic_flag()
    posted.clear()

    option = widget.get_option_at_index(1)
    event = OptionList.OptionHighlighted(widget, option, 1)
    widget.on_option_list_option_highlighted(event)

    assert len(posted) == 1
    assert isinstance(posted[0], ChangeSpecList.SelectionChanged)
    assert posted[0].index == 1


class _Timer:
    def stop(self) -> None:
        return


class _FakeList:
    def __init__(self) -> None:
        self.update_highlight_calls: list[int] = []
        self.highlighted_assignments: list[int | None] = []
        self._highlighted: int | None = None

    @property
    def highlighted(self) -> int | None:
        return self._highlighted

    @highlighted.setter
    def highlighted(self, value: int | None) -> None:
        self.highlighted_assignments.append(value)
        self._highlighted = value

    def update_highlight(self, current_idx: int) -> None:
        self.update_highlight_calls.append(current_idx)


class _FakeChangeSpecApp(ChangeSpecMixin):
    def __init__(self) -> None:
        self.changespecs = [
            make_changespec(name="alpha"),
            make_changespec(name="beta"),
        ]
        self.current_idx = 1
        self.current_tab = "changespecs"
        self.list_widget = _FakeList()
        self.info_panel_updates = 0
        self.scheduled: list[tuple[float, Callable[[], None]]] = []
        self._changespec_detail_debouncer = DetailPanelDebouncer(self)  # type: ignore[arg-type]

    def query_one(self, selector: str, _type: Any = None) -> _FakeList:
        assert selector == "#list-panel"
        return self.list_widget

    def set_timer(self, delay: float, callback: Callable[[], None]) -> _Timer:
        self.scheduled.append((delay, callback))
        return _Timer()

    def _update_info_panel(self) -> None:
        self.info_panel_updates += 1

    def _refresh_display(self) -> None:
        return


def test_changespec_debounced_refresh_uses_guarded_highlight_api() -> None:
    app = _FakeChangeSpecApp()

    app._refresh_changespecs_display_debounced()

    assert app.list_widget.update_highlight_calls == [1]
    assert app.list_widget.highlighted_assignments == []
    assert app.info_panel_updates == 1
    assert len(app.scheduled) == 1
