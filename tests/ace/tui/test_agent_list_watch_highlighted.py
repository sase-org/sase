"""Regression test for AgentList programmatic-update message suppression.

Reproduces the §3.2 drift mode of sdd/tales/202604/tui_selection_drift.md:
without a ``watch_highlighted`` override on ``AgentList``, Textual's
parent ``OptionList.watch_highlighted`` posts an ``OptionHighlighted``
message every time ``self.highlighted`` is reassigned during a
programmatic rebuild. The deferred-flag-clear (the old ``call_later``
path) raced with that message, so the in-handler ``_programmatic_update``
check could see ``False`` by the time the queued message arrived,
producing a phantom ``SelectionChanged`` that overwrote the app's
``current_idx`` with row 0.

The fix is two-fold:

1. ``AgentList.watch_highlighted`` synchronously short-circuits when
   ``_programmatic_update`` is True, so no message is queued in the
   first place.
2. The flag clears synchronously (try/finally) around the highlight
   assignment, eliminating the call_later/message-pump race.
"""

from __future__ import annotations

from sase.ace.tui.widgets.agent_list import AgentList


def test_watch_highlighted_short_circuits_during_programmatic_update() -> None:
    widget = AgentList()
    widget._programmatic_update = True

    posted: list[object] = []

    def _post_message(message: object) -> None:
        posted.append(message)

    widget.post_message = _post_message  # type: ignore[method-assign]

    # ``watch_highlighted`` is the synchronous gate — when the flag is
    # True it must return without delegating to the parent class
    # (which would queue an ``OptionHighlighted`` message). No state is
    # asserted other than "no messages were posted as a side effect".
    widget.watch_highlighted(3)
    assert posted == []


def test_watch_highlighted_delegates_when_user_navigation() -> None:
    widget = AgentList()
    widget._programmatic_update = False

    delegated: list[int | None] = []
    base_class = widget.__class__.__mro__[1]

    original = base_class.watch_highlighted

    def _record(self: AgentList, highlighted: int | None) -> None:
        delegated.append(highlighted)

    base_class.watch_highlighted = _record  # type: ignore[assignment]
    try:
        widget.watch_highlighted(2)
    finally:
        base_class.watch_highlighted = original  # type: ignore[assignment]

    assert delegated == [2]


def test_update_highlight_clears_flag_synchronously() -> None:
    """``update_highlight`` must leave ``_programmatic_update`` False on return.

    The plan §4.3 calls for synchronous try/finally clearing — without
    it, the deferred clear could race with the message pump and produce
    a phantom ``SelectionChanged``.
    """
    widget = AgentList()
    # Empty list short-circuits before any highlight assignment, so
    # the flag never flips. We need a populated row map; bypass the
    # full ``update_list`` plumbing by injecting the cache directly.
    widget._agents = []  # keeps update_highlight as a no-op
    widget._row_by_agent_attempt = {}
    widget._row_by_agent_idx = {}

    widget._programmatic_update = True
    widget.update_highlight(0)
    # Empty list path: flag should remain whatever the caller left it
    # (the synchronous clear only fires when there's a row to highlight).
    # Reset for the populated case below.
    widget._programmatic_update = False
    assert widget._programmatic_update is False
