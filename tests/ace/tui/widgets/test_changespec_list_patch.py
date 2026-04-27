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


def test_patch_replaces_row_in_place_no_clear_options(monkeypatch: Any) -> None:
    widget, _ = _wire_widget(monkeypatch)
    cs0 = make_changespec(name="alpha")
    cs1 = make_changespec(name="beta")
    widget.update_list([cs0, cs1], current_idx=0)

    clears: list[None] = []
    monkeypatch.setattr(widget, "clear_options", lambda: clears.append(None))

    replace_calls: list[tuple[int, Any]] = []

    def _replace(idx: int, prompt: Any) -> None:
        replace_calls.append((idx, prompt))

    monkeypatch.setattr(widget, "replace_option_prompt_at_index", _replace)

    ok = widget.patch_changespec_row(0, cs0, selected=True, marked=True)
    assert ok is True
    assert len(replace_calls) == 1
    assert replace_calls[0][0] == 0
    assert clears == []  # patching never clears the option list
    assert 0 in widget._marked_indices


def test_patch_unmarks_row(monkeypatch: Any) -> None:
    widget, _ = _wire_widget(monkeypatch)
    cs0 = make_changespec(name="alpha")
    cs1 = make_changespec(name="beta")
    widget.update_list([cs0, cs1], current_idx=0, marked_indices={0})
    monkeypatch.setattr(widget, "replace_option_prompt_at_index", lambda *a: None)

    ok = widget.patch_changespec_row(0, cs0, selected=True, marked=False)
    assert ok is True
    assert 0 not in widget._marked_indices


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
