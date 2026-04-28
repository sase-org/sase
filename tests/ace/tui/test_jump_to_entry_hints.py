"""Tests for jump-to-entry hint assignment and list hint rendering."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.ace.changespec import ChangeSpec
from sase.ace.tui.actions.event_handlers import EventHandlersMixin
from sase.ace.tui.actions.navigation._advanced import AdvancedNavigationMixin
from sase.ace.tui.actions.navigation.jump_hints import (
    JUMP_HINT_CHARS,
    build_jump_hint_maps,
    normalize_jump_key,
)
from sase.ace.tui.bgcmd import BackgroundCommandInfo
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.modals.jump_all_modal import JumpAllModal, JumpAllResult
from sase.ace.tui.widgets.agent_list import AgentList
from sase.ace.tui.widgets.bgcmd_list import BgCmdItem, BgCmdList
from sase.ace.tui.widgets._changespec_list_helpers import format_changespec_option
from sase.ace.tui.widgets.changespec_list import ChangeSpecList


def _make_changespec(name: str = "test_feature") -> ChangeSpec:
    return ChangeSpec(
        name=name,
        description="Test description",
        parent=None,
        cl=None,
        status="Ready",
        test_targets=None,
        kickstart=None,
        file_path="/tmp/test.gp",
        line_number=1,
    )


def _make_agent(cl_name: str = "test_feature") -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        raw_suffix="260101_120000",
    )


class _InlineJumpApp(AdvancedNavigationMixin):
    """Minimal changespec-tab harness for inline jump mode."""

    def __init__(self, changespecs: list[ChangeSpec]) -> None:
        self.changespecs = changespecs
        self.current_idx = 0
        self.current_tab = "changespecs"
        self._axe_items: list[Any] = []
        self._entry_jump_mode_active = False
        self._entry_jump_hint_to_index: dict[str, int] = {}
        self._entry_jump_index_to_hint: dict[int, str] = {}
        self._entry_jump_hint_to_banner: dict[str, Any] = {}
        self._entry_jump_banner_to_hint: dict[Any, str] = {}
        self._entry_jump_last_index: dict[str, int] = {}
        self._entry_jump_last_agents_anchor: Any = None
        self.refreshes = 0

    def _refresh_current_tab(self) -> None:
        self.refreshes += 1

    def _update_jump_footer(self) -> None:
        return


class _InlineJumpEventApp(EventHandlersMixin):
    """Small event-handler harness that records jump keys."""

    def __init__(self) -> None:
        self._entry_jump_mode_active = True
        self.handled_keys: list[str] = []
        self.activity_recorded = False

    def _record_user_activity(self) -> None:
        self.activity_recorded = True

    def _handle_entry_jump_key(self, key: str) -> bool:
        self.handled_keys.append(key)
        return True


class _KeyEvent:
    def __init__(self, key: str, character: str | None) -> None:
        self.key = key
        self.character = character
        self.prevented = False
        self.stopped = False

    def prevent_default(self) -> None:
        self.prevented = True

    def stop(self) -> None:
        self.stopped = True


def test_build_jump_hint_maps_uses_expected_order() -> None:
    indices = [10, 11, 12]
    hint_to_index, index_to_hint = build_jump_hint_maps(indices)
    assert hint_to_index == {"1": 10, "2": 11, "3": 12}
    assert index_to_hint == {10: "1", 11: "2", 12: "3"}


def test_build_jump_hint_maps_truncates_to_hint_alphabet() -> None:
    indices = list(range(len(JUMP_HINT_CHARS) + 5))
    hint_to_index, index_to_hint = build_jump_hint_maps(indices)
    assert len(hint_to_index) == len(JUMP_HINT_CHARS)
    assert hint_to_index["1"] == 0
    assert hint_to_index["0"] == 9
    assert hint_to_index["a"] == 10
    assert hint_to_index["z"] == 35
    assert hint_to_index["A"] == 36
    assert hint_to_index["Z"] == 61
    assert (len(JUMP_HINT_CHARS) + 1) not in index_to_hint


def test_jump_hint_alphabet_has_62_chars() -> None:
    assert len(JUMP_HINT_CHARS) == 62


def test_normalize_jump_key_prefers_uppercase_hint_character() -> None:
    assert normalize_jump_key("a", "A") == "A"
    assert normalize_jump_key("apostrophe", "'") == "apostrophe"
    assert normalize_jump_key("grave_accent", "`") == "grave_accent"
    assert normalize_jump_key("escape", None) == "escape"


def test_inline_jump_to_entry_allocates_and_dispatches_uppercase_hint() -> None:
    changespecs = [_make_changespec(f"feature_{i:02d}") for i in range(37)]
    app = _InlineJumpApp(changespecs)

    app.action_jump_to_entry()

    assert app._entry_jump_hint_to_index["A"] == 36
    assert app._entry_jump_index_to_hint[36] == "A"

    handled = app._handle_entry_jump_key("A")

    assert handled is True
    assert app.current_idx == 36
    assert app._entry_jump_mode_active is False


def test_inline_jump_on_key_uses_uppercase_event_character() -> None:
    app = _InlineJumpEventApp()
    event = _KeyEvent(key="a", character="A")

    app.on_key(event)  # type: ignore[arg-type]

    assert app.handled_keys == ["A"]
    assert event.prevented is True
    assert event.stopped is True


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

    option = widget.get_option_at_index(0)
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


def test_jump_all_modal_stores_last_position() -> None:
    last_pos = JumpAllResult(tab="changespecs", index=2)
    modal = JumpAllModal(
        changespecs=[],
        agents=[],
        axe_items=[],
        last_position=last_pos,
    )
    assert modal._last_position is last_pos


def test_jump_all_modal_no_last_position() -> None:
    modal = JumpAllModal(
        changespecs=[],
        agents=[],
        axe_items=[],
    )
    assert modal._last_position is None


def test_jump_all_modal_on_key_uses_uppercase_event_character(
    monkeypatch: Any,
) -> None:
    modal = JumpAllModal(
        changespecs=[_make_changespec(f"feature_{i:02d}") for i in range(37)],
        agents=[],
        axe_items=[],
    )
    dismissed: list[JumpAllResult | None] = []
    event = _KeyEvent(key="a", character="A")
    monkeypatch.setattr(modal, "dismiss", dismissed.append)

    modal.on_key(event)  # type: ignore[arg-type]

    assert dismissed == [JumpAllResult(tab="changespecs", index=36)]
    assert event.prevented is True
    assert event.stopped is True


def test_jump_all_modal_bgcmd_entry_includes_command(tmp_path: Path) -> None:
    info = BackgroundCommandInfo(
        command="rabbit test -c opt",
        project="myproject",
        workspace_num=1,
        workspace_dir="/tmp/ws1",
        started_at="2026-01-01T12:00:00",
    )
    slot_dir = tmp_path / "2"
    slot_dir.mkdir(parents=True)
    (slot_dir / "info.json").write_text(json.dumps(asdict(info)))

    with patch("sase.ace.tui.bgcmd.BGCMD_STATE_DIR", tmp_path):
        modal = JumpAllModal(
            changespecs=[],
            agents=[],
            axe_items=[BgCmdItem(slot=2)],
        )

    assert len(modal._entries) == 1
    assert modal._entries[0].name == "bgcmd #2: rabbit test -c opt"


def test_jump_all_modal_bgcmd_entry_falls_back_without_info(
    tmp_path: Path,
) -> None:
    with patch("sase.ace.tui.bgcmd.BGCMD_STATE_DIR", tmp_path):
        modal = JumpAllModal(
            changespecs=[],
            agents=[],
            axe_items=[BgCmdItem(slot=3)],
        )

    assert len(modal._entries) == 1
    assert modal._entries[0].name == "bgcmd #3"


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
