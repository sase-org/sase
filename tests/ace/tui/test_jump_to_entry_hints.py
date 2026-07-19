"""Tests for jump-to-entry hint assignment and list hint rendering."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll

from sase.ace.changespec import ChangeSpec
from sase.ace.tui.actions.event_handlers import EventHandlersMixin
from sase.ace.tui.actions.changespec._grouping_nav import (
    ChangeSpecGroupingNavMixin,
)
from sase.ace.tui.actions.navigation._advanced import AdvancedNavigationMixin
from sase.ace.tui.models.changespec_groups import ChangeSpecGroupingMode
from sase.ace.tui.models.group_fold import GroupFoldRegistry
from sase.ace.tui.actions.navigation.jump_hints import (
    JUMP_HINT_CHARS,
    JUMP_HINT_CAPACITY,
    JumpHintMatchOutcome,
    build_jump_hint_maps,
    match_jump_hint,
    normalize_jump_key,
)
from sase.ace.tui.bgcmd import BackgroundCommandInfo
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_status import STOPPED_COLOR, STOPPED_STATUS
from sase.ace.tui.modals.jump_all_modal import JumpAllModal, JumpAllResult
from sase.ace.tui.widgets.agent_list import AgentList
from sase.ace.tui.widgets.bgcmd_list import BgCmdItem, BgCmdList
from sase.ace.tui.widgets._changespec_list_helpers import format_changespec_option
from sase.ace.tui.widgets.changespec_list import ChangeSpecList
from sase.ace.tui.widgets.keybinding_footer import KeybindingFooter


def _make_changespec(
    name: str = "test_feature", *, project: str = "test"
) -> ChangeSpec:
    return ChangeSpec(
        name=name,
        description="Test description",
        parent=None,
        cl=None,
        status="Ready",
        file_path=f"/tmp/{project}/{project}.sase",
        line_number=1,
    )


def _make_agent(cl_name: str = "test_feature", *, status: str = "RUNNING") -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.sase",
        status=status,
        start_time=None,
        raw_suffix="260101_120000",
    )


class _InlineJumpApp(AdvancedNavigationMixin, ChangeSpecGroupingNavMixin):
    """Minimal changespec-tab harness for inline jump mode."""

    def __init__(self, changespecs: list[ChangeSpec]) -> None:
        self.changespecs = changespecs
        self.current_idx = 0
        self.current_tab = "changespecs"
        self._axe_items: list[Any] = []
        self._entry_jump_mode_active = False
        self._entry_jump_hint_to_target: dict[str, object] = {}
        self._entry_jump_pending_prefix = ""
        self._entry_jump_hint_to_index: dict[str, int] = {}
        self._entry_jump_index_to_hint: dict[int, str] = {}
        self._entry_jump_hint_to_banner: dict[str, Any] = {}
        self._entry_jump_banner_to_hint: dict[Any, str] = {}
        self._entry_jump_hint_to_changespec_banner: dict[str, Any] = {}
        self._entry_jump_changespec_banner_to_hint: dict[Any, str] = {}
        self._entry_jump_index_stack: dict[str, list[int]] = {}
        self._entry_jump_forward_index_stack: dict[str, list[Any]] = {}
        self._entry_jump_agents_anchor_stack: list[Any] = []
        self._entry_jump_agents_forward_anchor_stack: list[Any] = []
        self._changespec_grouping_mode = ChangeSpecGroupingMode.BY_PROJECT
        self._changespec_group_fold_registry = GroupFoldRegistry()
        self._current_changespec_group_key: tuple[str, ...] | None = None
        self.refreshes = 0
        self.jump_footer_updates = 0
        self.notify = MagicMock()

    def _refresh_current_tab(self) -> None:
        self.refreshes += 1

    def _refresh_display(self) -> None:
        self.refreshes += 1

    def _update_jump_footer(self) -> None:
        self.jump_footer_updates += 1


class _InlineJumpEventApp(EventHandlersMixin):
    """Small event-handler harness that records jump keys."""

    def __init__(self) -> None:
        self._entry_jump_mode_active = True
        self.handled_keys: list[str] = []
        self.activity_recorded = False

    def _record_input_event(self) -> None:
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


class _JumpAllTestApp(App[object | None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def test_build_jump_hint_maps_uses_expected_order() -> None:
    indices = [10, 11, 12]
    hint_to_index, index_to_hint = build_jump_hint_maps(indices)
    assert hint_to_index == {"0": 10, "1": 11, "2": 12}
    assert index_to_hint == {10: "0", 11: "1", 12: "2"}


def test_build_jump_hint_maps_uses_one_character_through_exactly_62() -> None:
    indices = list(range(len(JUMP_HINT_CHARS)))
    hint_to_index, index_to_hint = build_jump_hint_maps(indices)
    assert len(hint_to_index) == len(JUMP_HINT_CHARS)
    assert hint_to_index["0"] == 0
    assert hint_to_index["9"] == 9
    assert hint_to_index["a"] == 10
    assert hint_to_index["z"] == 35
    assert hint_to_index["A"] == 36
    assert hint_to_index["Z"] == 61
    assert index_to_hint[61] == "Z"


def test_build_jump_hint_maps_switches_entire_63_target_session_to_two_chars() -> None:
    hint_to_index, index_to_hint = build_jump_hint_maps(list(range(63)))

    assert hint_to_index["00"] == 0
    assert hint_to_index["09"] == 9
    assert hint_to_index["0a"] == 10
    assert hint_to_index["0Z"] == 61
    assert hint_to_index["10"] == 62
    assert index_to_hint[0] == "00"


def test_build_jump_hint_maps_stops_at_zz_capacity() -> None:
    targets = list(range(JUMP_HINT_CAPACITY + 2))
    hint_to_index, index_to_hint = build_jump_hint_maps(targets)

    assert len(hint_to_index) == JUMP_HINT_CAPACITY
    assert hint_to_index["ZZ"] == JUMP_HINT_CAPACITY - 1
    assert JUMP_HINT_CAPACITY not in index_to_hint


def test_build_jump_hint_maps_one_target_starts_at_zero() -> None:
    assert build_jump_hint_maps(["only"]) == ({"0": "only"}, {"only": "0"})


def test_jump_hint_alphabet_has_62_chars() -> None:
    assert len(JUMP_HINT_CHARS) == 62


def test_match_jump_hint_waits_for_two_character_completion() -> None:
    hint_to_target, _ = build_jump_hint_maps(list(range(63)))

    pending = match_jump_hint(hint_to_target, "", "1")
    complete = match_jump_hint(hint_to_target, pending.prefix, "0")

    assert pending.outcome is JumpHintMatchOutcome.PENDING
    assert pending.prefix == "1"
    assert complete.outcome is JumpHintMatchOutcome.COMPLETE
    assert complete.target == 62


def test_match_jump_hint_is_case_sensitive_and_rejects_invalid_sequences() -> None:
    hint_to_target, _ = build_jump_hint_maps(list(range(63)))

    assert match_jump_hint(hint_to_target, "0", "Z").target == 61
    assert (
        match_jump_hint(hint_to_target, "0", "z").outcome
        is JumpHintMatchOutcome.COMPLETE
    )
    assert (
        match_jump_hint(hint_to_target, "Z", "Z").outcome
        is JumpHintMatchOutcome.INVALID
    )


def test_match_jump_hint_keeps_one_character_sessions_immediate() -> None:
    hint_to_target, _ = build_jump_hint_maps([10, 11])

    match = match_jump_hint(hint_to_target, "", "1")

    assert match.outcome is JumpHintMatchOutcome.COMPLETE
    assert match.target == 11


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


def test_inline_two_character_jump_waits_for_second_character() -> None:
    app = _InlineJumpApp([_make_changespec(f"feature_{i:02d}") for i in range(63)])

    app.action_jump_to_entry()

    assert app._entry_jump_index_to_hint[0] == "00"
    assert app._entry_jump_index_to_hint[62] == "10"
    refreshes_after_activation = app.refreshes
    assert app._handle_entry_jump_key("1") is True
    assert app.current_idx == 0
    assert app._entry_jump_mode_active is True
    assert app._entry_jump_pending_prefix == "1"
    assert app.refreshes == refreshes_after_activation

    assert app._handle_entry_jump_key("0") is True
    assert app.current_idx == 62
    assert app._entry_jump_mode_active is False
    assert app._entry_jump_pending_prefix == ""


def test_inline_two_character_jump_escape_clears_partial_prefix() -> None:
    app = _InlineJumpApp([_make_changespec(f"feature_{i:02d}") for i in range(63)])
    app.action_jump_to_entry()
    assert app._handle_entry_jump_key("0") is True

    assert app._handle_entry_jump_key("escape") is True

    assert app._entry_jump_mode_active is False
    assert app._entry_jump_pending_prefix == ""


def test_apostrophe_selects_first_target_directly_at_two_character_width() -> None:
    app = _InlineJumpApp([_make_changespec(f"feature_{i:02d}") for i in range(63)])
    app.current_idx = 62

    app.action_jump_to_entry()
    assert app._handle_entry_jump_key("apostrophe") is True

    assert app.current_idx == 0
    assert app._entry_jump_index_stack["changespecs"] == [62]


def test_fast_jump_selects_first_target_directly_at_two_character_width() -> None:
    app = _InlineJumpApp([_make_changespec(f"feature_{i:02d}") for i in range(63)])
    app.current_idx = 62

    app.action_jump_to_entry_fast()

    assert app.current_idx == 0
    assert app._entry_jump_index_stack["changespecs"] == [62]
    assert app._entry_jump_pending_prefix == ""


def test_apostrophe_without_history_dispatches_first_changespec_hint() -> None:
    changespecs = [_make_changespec(f"feature_{i:02d}") for i in range(3)]
    app = _InlineJumpApp(changespecs)
    app.current_idx = 2

    app.action_jump_to_entry()
    handled = app._handle_entry_jump_key("apostrophe")

    assert handled is True
    assert app.current_idx == 0
    assert app._entry_jump_index_stack["changespecs"] == [2]
    assert app._entry_jump_mode_active is False


def test_fast_jump_without_history_dispatches_first_changespec_without_footer() -> None:
    changespecs = [_make_changespec(f"feature_{i:02d}") for i in range(3)]
    app = _InlineJumpApp(changespecs)
    app.current_idx = 2

    app.action_jump_to_entry_fast()

    assert app.current_idx == 0
    assert app._entry_jump_index_stack["changespecs"] == [2]
    assert app._entry_jump_mode_active is False
    assert app.jump_footer_updates == 0


def test_fast_jump_with_history_restores_changespec_and_pops_origin() -> None:
    changespecs = [_make_changespec(f"feature_{i:02d}") for i in range(3)]
    app = _InlineJumpApp(changespecs)
    app.current_idx = 2
    app._entry_jump_index_stack["changespecs"] = [1]

    app.action_jump_to_entry_fast()

    assert app.current_idx == 1
    assert app._entry_jump_index_stack["changespecs"] == []
    assert app._entry_jump_mode_active is False
    assert app.jump_footer_updates == 0


def test_changespec_jump_stack_walks_back_and_forward() -> None:
    changespecs = [_make_changespec(f"feature_{i:02d}") for i in range(3)]
    app = _InlineJumpApp(changespecs)
    app.current_idx = 2

    app.action_jump_to_entry()
    handled = app._handle_entry_jump_key("0")

    assert handled is True
    assert app.current_idx == 0
    assert app._entry_jump_index_stack["changespecs"] == [2]

    app.action_jump_to_entry_fast()

    assert app.current_idx == 2
    assert app._entry_jump_index_stack["changespecs"] == []
    assert app._entry_jump_forward_index_stack["changespecs"] == [0]

    app.action_jump_to_entry_forward()

    assert app.current_idx == 0
    assert app._entry_jump_index_stack["changespecs"] == [2]
    assert app._entry_jump_forward_index_stack["changespecs"] == []


def test_new_changespec_hint_jump_clears_forward_history() -> None:
    changespecs = [_make_changespec(f"feature_{i:02d}") for i in range(3)]
    app = _InlineJumpApp(changespecs)
    app.current_idx = 2
    app._entry_jump_forward_index_stack["changespecs"] = [0]

    app.action_jump_to_entry()
    handled = app._handle_entry_jump_key("1")

    assert handled is True
    assert app.current_idx == 1
    assert app._entry_jump_index_stack["changespecs"] == [2]
    assert app._entry_jump_forward_index_stack["changespecs"] == []


def test_push_changespec_to_history_records_origin_and_clears_forward() -> None:
    changespecs = [_make_changespec(f"feature_{i:02d}") for i in range(3)]
    app = _InlineJumpApp(changespecs)
    app.current_idx = 2
    app._entry_jump_forward_index_stack["changespecs"] = [0]

    app._push_changespec_to_history()

    assert app._entry_jump_index_stack["changespecs"] == [2]
    assert app._entry_jump_forward_index_stack["changespecs"] == []


def test_forward_jump_discards_stale_changespec_anchor() -> None:
    changespecs = [_make_changespec(f"feature_{i:02d}") for i in range(2)]
    app = _InlineJumpApp(changespecs)
    app.current_idx = 1
    app._entry_jump_forward_index_stack["changespecs"] = [9]

    app.action_jump_to_entry_forward()

    assert app.current_idx == 1
    assert "changespecs" not in app._entry_jump_forward_index_stack
    app.notify.assert_called_once_with(
        "No next jump point",
        severity="information",
    )


def test_changespec_banner_anchor_restores_forward() -> None:
    changespecs = [
        _make_changespec("a_one", project="alpha"),
        _make_changespec("b_one", project="beta"),
    ]
    app = _InlineJumpApp(changespecs)
    app.current_idx = 1
    app._changespec_group_fold_registry.collapse(("alpha",))

    app.action_jump_to_entry()
    banner_hint = app._entry_jump_changespec_banner_to_hint[("alpha",)]
    handled = app._handle_entry_jump_key(banner_hint)

    assert handled is True
    assert app._current_changespec_group_key == ("alpha",)
    assert app.current_idx == 1
    assert app._entry_jump_index_stack["changespecs"] == [1]

    app.action_jump_to_entry_fast()

    assert app._current_changespec_group_key is None
    assert app.current_idx == 1
    assert app._entry_jump_forward_index_stack["changespecs"] == [
        ("changespec_banner", ("alpha",))
    ]

    app.action_jump_to_entry_forward()

    assert app._current_changespec_group_key == ("alpha",)
    assert app.current_idx == 1
    assert app._entry_jump_index_stack["changespecs"] == [1]


def test_fast_jump_with_history_pops_changespec_stack_lifo() -> None:
    changespecs = [_make_changespec(f"feature_{i:02d}") for i in range(4)]
    app = _InlineJumpApp(changespecs)
    app.current_idx = 3
    app._entry_jump_index_stack["changespecs"] = [0, 1, 2]

    app.action_jump_to_entry_fast()
    assert app.current_idx == 2
    assert app._entry_jump_index_stack["changespecs"] == [0, 1]

    app.action_jump_to_entry_fast()
    assert app.current_idx == 1
    assert app._entry_jump_index_stack["changespecs"] == [0]

    app.action_jump_to_entry_fast()
    assert app.current_idx == 0
    assert app._entry_jump_index_stack["changespecs"] == []


def test_fast_jump_discards_stale_changespec_back_stack_before_fallback() -> None:
    changespecs = [_make_changespec(f"feature_{i:02d}") for i in range(2)]
    app = _InlineJumpApp(changespecs)
    app.current_idx = 1
    app._entry_jump_index_stack["changespecs"] = [9]

    app.action_jump_to_entry_fast()

    assert app.current_idx == 0
    assert app._entry_jump_index_stack["changespecs"] == [1]
    assert app._entry_jump_mode_active is False
    assert app.jump_footer_updates == 0


def test_fast_jump_discards_stale_changespec_back_stack_before_valid_restore() -> None:
    changespecs = [_make_changespec(f"feature_{i:02d}") for i in range(2)]
    app = _InlineJumpApp(changespecs)
    app.current_idx = 1
    app._entry_jump_index_stack["changespecs"] = [0, 9]

    app.action_jump_to_entry_fast()

    assert app.current_idx == 0
    assert app._entry_jump_index_stack["changespecs"] == []
    assert app._entry_jump_mode_active is False
    assert app.jump_footer_updates == 0


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


def test_jump_all_modal_styles_stopped_agent_status() -> None:
    modal = JumpAllModal(
        changespecs=[],
        agents=[_make_agent(status=STOPPED_STATUS)],
        axe_items=[],
    )

    assert modal._entries[0].status == STOPPED_STATUS
    assert modal._entries[0].status_style == STOPPED_COLOR


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


def test_jump_all_modal_two_character_hint_dispatches_only_after_completion(
    monkeypatch: Any,
) -> None:
    modal = JumpAllModal(
        changespecs=[_make_changespec(f"feature_{i:02d}") for i in range(63)],
        agents=[],
        axe_items=[],
    )
    dismissed: list[JumpAllResult | None] = []
    monkeypatch.setattr(modal, "dismiss", dismissed.append)

    first = _KeyEvent(key="1", character="1")
    modal.on_key(first)  # type: ignore[arg-type]
    assert dismissed == []
    assert modal._pending_hint_prefix == "1"
    assert first.prevented is True
    assert first.stopped is True

    second = _KeyEvent(key="0", character="0")
    modal.on_key(second)  # type: ignore[arg-type]
    assert dismissed == [JumpAllResult(tab="changespecs", index=62)]
    assert modal._pending_hint_prefix == ""


def test_jump_all_backtick_remains_control_during_partial_hint(
    monkeypatch: Any,
) -> None:
    last_position = JumpAllResult(tab="agents", index=4)
    modal = JumpAllModal(
        changespecs=[_make_changespec(f"feature_{i:02d}") for i in range(63)],
        agents=[],
        axe_items=[],
        last_position=last_position,
    )
    dismissed: list[JumpAllResult | None] = []
    monkeypatch.setattr(modal, "dismiss", dismissed.append)

    modal.on_key(_KeyEvent(key="0", character="0"))  # type: ignore[arg-type]
    assert modal._pending_hint_prefix == "0"

    back = _KeyEvent(key="grave_accent", character="`")
    modal.on_key(back)  # type: ignore[arg-type]

    assert dismissed == [last_position]
    assert modal._pending_hint_prefix == ""
    assert back.prevented is True
    assert back.stopped is True


async def test_jump_all_modal_ctrl_d_scrolls_without_dismissing() -> None:
    result: object | None = "pending"

    async with _JumpAllTestApp().run_test(size=(120, 24)) as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = JumpAllModal(
            changespecs=[_make_changespec(f"feature_{i:02d}") for i in range(62)],
            agents=[],
            axe_items=[],
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        scroll = modal.query_one("#jump-all-scroll", VerticalScroll)
        visible_height = scroll.scrollable_content_region.height
        assert visible_height > 0
        assert scroll.max_scroll_y > 0

        await pilot.press("ctrl+d")
        await pilot.pause()

        assert scroll.scroll_y == visible_height // 2
        assert result == "pending"


async def test_jump_all_modal_ctrl_u_scrolls_up_without_dismissing() -> None:
    result: object | None = "pending"

    async with _JumpAllTestApp().run_test(size=(120, 24)) as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = JumpAllModal(
            changespecs=[_make_changespec(f"feature_{i:02d}") for i in range(62)],
            agents=[],
            axe_items=[],
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        scroll = modal.query_one("#jump-all-scroll", VerticalScroll)
        visible_height = scroll.scrollable_content_region.height
        assert visible_height > 0
        assert scroll.max_scroll_y > visible_height
        scroll.scroll_relative(y=visible_height, animate=False)
        await pilot.pause()
        assert scroll.scroll_y == visible_height

        await pilot.press("ctrl+u")
        await pilot.pause()

        assert scroll.scroll_y == visible_height - (visible_height // 2)
        assert result == "pending"


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
