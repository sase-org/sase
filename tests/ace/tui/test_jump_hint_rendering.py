"""Tests for jump hint rendering in lists and the footer."""

from typing import Any

from sase.ace.tui.bgcmd import BackgroundCommandInfo
from sase.ace.tui.widgets._changespec_list_helpers import format_changespec_option
from sase.ace.tui.widgets.agent_list import AgentList
from sase.ace.tui.widgets.bgcmd_list import BgCmdList
from sase.ace.tui.widgets.changespec_list import ChangeSpecList
from sase.ace.tui.widgets.keybinding_footer import KeybindingFooter
from tests.ace.tui._jump_to_entry_hints_helpers import (
    _make_agent,
    _make_changespec,
)


def test_changespec_list_hint_marker_rendered() -> None:
    option = format_changespec_option(
        _make_changespec(),
        is_selected=False,
        is_marked=False,
        hint_char="a",
    )
    assert "[a]" in str(option.prompt)


def test_changespec_list_update_renders_uppercase_hint_marker(
    monkeypatch: Any,
) -> None:
    widget = ChangeSpecList()
    monkeypatch.setattr(widget, "call_later", lambda callback: None)
    monkeypatch.setattr(widget, "post_message", lambda message: None)

    widget.update_list(
        [_make_changespec("uppercase_hint")],
        current_idx=0,
        jump_hints={0: "A"},
    )

    # Grouped render emits a project banner before the ChangeSpec row, so the
    # ChangeSpec row sits at row index 1.
    cs_row = next(i for i, e in enumerate(widget._row_entries) if e == 0)
    option = widget.get_option_at_index(cs_row)
    assert "[A]" in str(option.prompt)


def test_agent_list_hint_marker_rendered() -> None:
    widget = AgentList()
    option = widget._format_agent_option(
        _make_agent(),
        index=0,
        is_selected=False,
        hint_char="b",
    )
    assert "[b]" in str(option.prompt)


def test_jump_footer_shows_apostrophe_first_without_history() -> None:
    footer = KeybindingFooter()
    captured: list[tuple[list[tuple[str, str]], str | None]] = []

    def _capture(bindings: Any, mode_label: Any = None) -> None:
        captured.append((list(bindings), mode_label))

    footer._update_display = _capture  # type: ignore[method-assign]

    footer.update_jump_bindings(has_back=False)

    assert captured == [([("'", "first"), ("<esc>", "cancel")], "JUMP")]


def test_jump_footer_shows_apostrophe_back_with_history() -> None:
    footer = KeybindingFooter()
    captured: list[tuple[list[tuple[str, str]], str | None]] = []

    def _capture(bindings: Any, mode_label: Any = None) -> None:
        captured.append((list(bindings), mode_label))

    footer._update_display = _capture  # type: ignore[method-assign]

    footer.update_jump_bindings(has_back=True)

    assert captured == [([("'", "back"), ("<esc>", "cancel")], "JUMP")]


def test_bgcmd_list_hint_marker_rendered() -> None:
    widget = BgCmdList()
    info = BackgroundCommandInfo(
        command="make test",
        project="myproject",
        workspace_num=1,
        workspace_dir="/tmp/ws1",
        started_at="2026-01-01T12:00:00",
    )
    option = widget._format_bgcmd_option(
        slot=1,
        info=info,
        is_selected=False,
        is_running=True,
        hint_char="9",
    )
    assert "[9]" in str(option.prompt)
