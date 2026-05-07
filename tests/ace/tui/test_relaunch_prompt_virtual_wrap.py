"""Tests for relaunch prompt loading in the ace TUI."""

from __future__ import annotations

from unittest.mock import Mock, patch

from sase.ace.tui.actions.agent_workflow._entry_points import EntryPointsMixin
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class _RelaunchApp(EntryPointsMixin):
    """Small test double for the EntryPointsMixin relaunch path."""

    def __init__(self) -> None:
        self.mounted: PromptInputBar | None = None
        self.unmounted = False

    def _unmount_prompt_bar(self) -> None:
        self.unmounted = True

    def mount(self, widget: PromptInputBar) -> None:
        self.mounted = widget


@patch("subprocess.run")
def test_edit_and_relaunch_agent_preserves_raw_prompt_without_prettier(
    mock_run: Mock,
) -> None:
    app = _RelaunchApp()
    raw_prompt = "first   line with spacing\nsecond line " + ("very-long " * 12)

    app._edit_and_relaunch_agent(
        raw_prompt,
        "/tmp/project/project.gp",
        "branch",
        False,
    )

    assert app.unmounted is True
    assert app.mounted is not None
    assert app.mounted._initial_value == raw_prompt
    mock_run.assert_not_called()
