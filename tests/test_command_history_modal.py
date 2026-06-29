"""Tests for command-history modal display labels."""

from __future__ import annotations

from unittest.mock import patch

from rich.text import Text

from sase.ace.tui.modals.command_history_modal import CommandHistoryModal
from sase.history.command import CommandEntry


class _StaticCapture:
    def __init__(self) -> None:
        self.value: object = None

    def update(self, value: object) -> None:
        self.value = value


def test_command_history_modal_uses_project_display_name() -> None:
    """Command history displays PROJECT_NAME while keeping canonical storage."""
    entry = CommandEntry(
        command="make test",
        project="gh_acme__widgets",
        cl_name="fix-build",
        timestamp="260101_120000",
        last_used="260101_120000",
    )

    with (
        patch(
            "sase.ace.tui.modals.command_history_modal.get_commands_for_display",
            return_value=[("~ gh_acme__widgets/fix-build | make test", entry)],
        ),
        patch(
            "sase.ace.tui.modals.command_history_modal.project_display_name_for",
            side_effect=lambda key: {"gh_acme__widgets": "widgets"}.get(key, key),
        ),
    ):
        modal = CommandHistoryModal(current_project="gh_acme__widgets")
        header_plain = modal._get_header_text().plain

    item = modal._all_items[0]
    assert item.display_context.strip() == "widgets/fix-build"
    assert item.display_project == "widgets"
    assert "gh_acme__widgets" not in item.display_context
    assert header_plain == "~ = widgets"

    preview = _StaticCapture()
    metadata = _StaticCapture()

    def query_one(selector: str, _widget_type: type) -> _StaticCapture:
        return metadata if selector == "#command-history-metadata" else preview

    modal.query_one = query_one  # type: ignore[assignment]
    modal._update_preview(item)

    assert isinstance(metadata.value, Text)
    assert "Project: widgets" in metadata.value.plain
    assert "gh_acme__widgets" not in metadata.value.plain
