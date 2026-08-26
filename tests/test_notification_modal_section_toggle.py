"""Notification modal grouped-section rendering and toggle tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.modals.notification_modal_constants import HEADER_ID_PREFIX
from sase.ace.tui.modals.notification_section_modes import NotificationSectionModes
from sase.notification_gates.presentation import (
    GATE_CHIP_COLOR_ACTION_DATA_KEY,
    GATE_CHIP_GLYPH_ACTION_DATA_KEY,
    GATE_CHIP_LABEL_ACTION_DATA_KEY,
)
from sase.notifications import Notification

from tests._notification_modal_helpers import _make_notification, _wire_fake_option_list


def _task(
    notification_id: str,
    timestamp: str,
    slug: str,
    glyph: str,
    color: str,
) -> Notification:
    notification = _make_notification(
        notification_id,
        action="TaskTriage",
        timestamp=timestamp,
        action_data={
            "panel": "beads",
            GATE_CHIP_GLYPH_ACTION_DATA_KEY: glyph,
            GATE_CHIP_LABEL_ACTION_DATA_KEY: slug,
            GATE_CHIP_COLOR_ACTION_DATA_KEY: color,
        },
    )
    notification.notes = [f"{notification_id} — title"]
    return notification


def _beads_modal() -> NotificationModal:
    newest_flake = _task(
        "flake-new",
        "2026-03-17T13:00:00-04:00",
        "flake",
        "≈",
        "#00D7D7",
    )
    bug = _task("bug", "2026-03-17T12:00:00-04:00", "bug", "⨯", "#FF5F5F")
    older_flake = _task(
        "flake-old",
        "2026-03-17T11:00:00-04:00",
        "flake",
        "≈",
        "#00D7D7",
    )
    modal = NotificationModal([newest_flake, bug, older_flake])
    modal._active_notification_tag = "beads"
    return modal


def _plain_options(modal: NotificationModal) -> list[tuple[str | None, bool, str]]:
    return [
        (option.id, option.disabled, str(option.prompt))
        for option in modal._create_notification_options()
    ]


def _recent_modes() -> NotificationSectionModes:
    modes = NotificationSectionModes()
    assert modes.toggle("beads") == "recent"
    return modes


def test_beads_tab_renders_disabled_headers_and_single_intersection_spacer() -> None:
    modal = _beads_modal()

    options = modal._create_notification_options()
    header_ids = [
        option.id
        for option in options
        if option.id is not None and option.id.startswith(f"{HEADER_ID_PREFIX}sec:")
    ]
    spacer_ids = [
        option.id
        for option in options
        if option.id is not None and option.id.startswith(f"{HEADER_ID_PREFIX}gap:")
    ]

    assert header_ids == ["hdr:sec:beads:type:bug", "hdr:sec:beads:type:flake"]
    assert spacer_ids == ["hdr:gap:beads:type:flake"]
    assert all(
        option.disabled
        for option in options
        if option.id is not None and option.id.startswith(HEADER_ID_PREFIX)
    )
    first_id = options[0].id
    assert first_id is not None
    assert not first_id.startswith(f"{HEADER_ID_PREFIX}gap:")


def test_visual_notification_index_order_skips_section_rows() -> None:
    modal = _beads_modal()

    assert modal._visual_notification_index_order() == [1, 0, 2]


def test_toggle_sections_flips_to_flat_and_keeps_highlighted_notification() -> None:
    modal = _beads_modal()
    option_list = _wire_fake_option_list(modal, highlighted_index=2)
    modal._display_file = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    modal.action_toggle_sections()

    flat = _beads_modal()
    flat._section_modes = _recent_modes()
    assert [
        (option.id, option.disabled, str(option.prompt))
        for option in option_list.options
    ] == _plain_options(flat)
    assert modal._get_selected_index() == 2
    modal.notify.assert_called_once_with("Beads · newest first")


def test_section_modes_are_per_tab() -> None:
    row = _make_notification("general", action="JumpToAgent")
    modal = _beads_modal()
    modal._notifications.append(row)

    assert modal._section_modes.mode_for("beads") == "grouped"
    assert modal._section_modes.mode_for("general") == "recent"
    modal._active_notification_tag = "beads"
    assert modal._section_modes.toggle("beads") == "recent"

    modal._active_notification_tag = None
    assert modal._active_section_strategy() is None
    assert modal._section_modes.mode_for("general") == "recent"

    modal._active_notification_tag = "beads"
    assert modal._active_section_strategy() is None


def test_toggle_sections_on_tab_without_strategy_is_noop_and_notifies() -> None:
    modal = NotificationModal([_make_notification("general", action="JumpToAgent")])
    before = _plain_options(modal)
    _wire_fake_option_list(modal, highlighted_index=0)
    modal._display_file = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]

    modal.action_toggle_sections()

    assert _plain_options(modal) == before
    modal.notify.assert_called_once_with("No sections for General")


def test_jump_hints_land_on_notification_rows_in_grouped_visual_order() -> None:
    modal = _beads_modal()

    modal.action_jump_to_entry()
    options = modal._create_notification_options(jump_hints=modal.jump_hints_by_key())

    prompted_rows = [
        (option.id, str(option.prompt)) for option in options if not option.disabled
    ]
    assert prompted_rows[0][0] == "1"
    assert "[0]" in prompted_rows[0][1]
    assert prompted_rows[1][0] == "0"
    assert "[1]" in prompted_rows[1][1]
    assert prompted_rows[2][0] == "2"
    assert "[2]" in prompted_rows[2][1]
