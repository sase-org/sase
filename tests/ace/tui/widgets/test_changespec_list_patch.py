"""Direct tests for ``ChangeSpecList.patch_changespec_row``.

The patch path is the Phase 2 hot-path replacement for full
``update_list`` rebuilds when only one row's mark/selection changes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from textual.message import Message

from sase.ace.testing import make_changespec
from sase.ace.tui.widgets import ChangeSpecList


def _wire_widget(monkeypatch: Any) -> tuple[ChangeSpecList, list[Message]]:
    widget = ChangeSpecList()
    posted: list[Message] = []

    def _call_later(callback: Callable[[], None]) -> None:
        callback()

    monkeypatch.setattr(widget, "call_later", _call_later)
    monkeypatch.setattr(widget, "post_message", posted.append)
    return widget, posted


def test_patch_returns_false_before_initial_render(monkeypatch: Any) -> None:
    widget, _ = _wire_widget(monkeypatch)
    cs = make_changespec(name="alpha")
    assert widget.patch_changespec_row(0, cs, selected=True, marked=False) is False


def test_patch_refuses_when_banner_rows_offset_indices(monkeypatch: Any) -> None:
    """The grouped render path always emits banner rows, so the patch
    path's ``option_count == len(self._changespecs)`` gate is never
    satisfied on the CLs tab.  Single-row patches always fall back to a
    full :meth:`update_list` rebuild."""
    widget, _ = _wire_widget(monkeypatch)
    cs0 = make_changespec(name="alpha")
    cs1 = make_changespec(name="beta")
    widget.update_list([cs0, cs1], current_idx=0)

    ok = widget.patch_changespec_row(0, cs0, selected=True, marked=True)
    assert ok is False


def test_patch_unmarks_row_falls_back(monkeypatch: Any) -> None:
    widget, _ = _wire_widget(monkeypatch)
    cs0 = make_changespec(name="alpha")
    cs1 = make_changespec(name="beta")
    widget.update_list([cs0, cs1], current_idx=0, marked_indices={0})

    ok = widget.patch_changespec_row(0, cs0, selected=True, marked=False)
    assert ok is False


def test_patch_falls_back_when_name_drifts(monkeypatch: Any) -> None:
    widget, _ = _wire_widget(monkeypatch)
    cs0 = make_changespec(name="alpha")
    widget.update_list([cs0], current_idx=0)

    other = make_changespec(name="zulu")  # different name at same idx
    ok = widget.patch_changespec_row(0, other, selected=True, marked=False)
    assert ok is False


def test_patch_falls_back_when_idx_out_of_range(monkeypatch: Any) -> None:
    widget, _ = _wire_widget(monkeypatch)
    cs0 = make_changespec(name="alpha")
    widget.update_list([cs0], current_idx=0)

    ok = widget.patch_changespec_row(5, cs0, selected=True, marked=False)
    assert ok is False


def test_patch_records_optimal_target_width(monkeypatch: Any) -> None:
    """The cached target width is what bounds future patch attempts."""
    widget, _ = _wire_widget(monkeypatch)
    cs0 = make_changespec(name="alpha")
    widget.update_list([cs0], current_idx=0)

    assert widget._target_width > 0
    # Name index map populated.
    assert widget._option_idx_by_changespec_name == {"alpha": 0}
