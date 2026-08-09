"""Tests for jump hint behavior in the jump-all modal."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from unittest.mock import patch

from textual.containers import VerticalScroll

from sase.ace.tui.bgcmd import BackgroundCommandInfo
from sase.ace.tui.models.agent_status import STOPPED_COLOR, STOPPED_STATUS
from sase.ace.tui.modals.jump_all_modal import JumpAllModal, JumpAllResult
from sase.ace.tui.widgets.bgcmd_list import BgCmdItem
from tests.ace.tui._jump_to_entry_hints_helpers import (
    _JumpAllTestApp,
    _KeyEvent,
    _make_agent,
    _make_patch,
)


def test_jump_all_modal_stores_last_position() -> None:
    last_pos = JumpAllResult(tab="patches", index=2)
    modal = JumpAllModal(
        patches=[],
        agents=[],
        axe_items=[],
        last_position=last_pos,
    )
    assert modal._last_position is last_pos


def test_jump_all_modal_no_last_position() -> None:
    modal = JumpAllModal(
        patches=[],
        agents=[],
        axe_items=[],
    )
    assert modal._last_position is None


def test_jump_all_modal_styles_stopped_agent_status() -> None:
    modal = JumpAllModal(
        patches=[],
        agents=[_make_agent(status=STOPPED_STATUS)],
        axe_items=[],
    )

    assert modal._entries[0].status == STOPPED_STATUS
    assert modal._entries[0].status_style == STOPPED_COLOR


def test_jump_all_modal_on_key_uses_uppercase_event_character(
    monkeypatch: Any,
) -> None:
    modal = JumpAllModal(
        patches=[_make_patch(f"feature_{i:02d}") for i in range(37)],
        agents=[],
        axe_items=[],
    )
    dismissed: list[JumpAllResult | None] = []
    event = _KeyEvent(key="a", character="A")
    monkeypatch.setattr(modal, "dismiss", dismissed.append)

    modal.on_key(event)  # type: ignore[arg-type]

    assert dismissed == [JumpAllResult(tab="artifacts", index=36)]
    assert event.prevented is True
    assert event.stopped is True


def test_jump_all_modal_two_character_hint_dispatches_only_after_completion(
    monkeypatch: Any,
) -> None:
    modal = JumpAllModal(
        patches=[_make_patch(f"feature_{i:02d}") for i in range(63)],
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
    assert dismissed == [JumpAllResult(tab="artifacts", index=62)]
    assert modal._pending_hint_prefix == ""


def test_jump_all_backtick_remains_control_during_partial_hint(
    monkeypatch: Any,
) -> None:
    last_position = JumpAllResult(tab="agents", index=4)
    modal = JumpAllModal(
        patches=[_make_patch(f"feature_{i:02d}") for i in range(63)],
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
            patches=[_make_patch(f"feature_{i:02d}") for i in range(62)],
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
            patches=[_make_patch(f"feature_{i:02d}") for i in range(62)],
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
            patches=[],
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
            patches=[],
            agents=[],
            axe_items=[BgCmdItem(slot=3)],
        )

    assert len(modal._entries) == 1
    assert modal._entries[0].name == "bgcmd #3"
