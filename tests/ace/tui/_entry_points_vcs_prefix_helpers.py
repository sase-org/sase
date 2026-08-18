"""Shared helpers for entry-point VCS prefix tests."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.tui.actions.agent_workflow import _entry_points
from sase.ace.tui.actions.agent_workflow._entry_points import EntryPointsMixin
from sase.ace.tui.actions.agent_workflow._prompt_bar_mount import PromptBarMountMixin

# An editor buffer with leading xprompt frontmatter, a real multi-agent ``---``
# separator, and a trailing ` @` review marker: the marker requests review (not
# launch), and the cleaned remainder must reload through editor-file (xprompt
# markdown) semantics.
_MARKED_MULTI_AGENT_MARKDOWN = (
    "---\n"
    "description: Review auth and API separately\n"
    "xprompts:\n"
    "  _shared: Use the same style guide.\n"
    "---\n"
    "Review auth.\n"
    "---\n"
    "Review API. @"
)
_CLEANED_MULTI_AGENT_MARKDOWN = (
    "---\n"
    "description: Review auth and API separately\n"
    "xprompts:\n"
    "  _shared: Use the same style guide.\n"
    "---\n"
    "Review auth.\n"
    "---\n"
    "Review API."
)
_LIFTED_FRONTMATTER = (
    "---\n"
    "description: Review auth and API separately\n"
    "xprompts:\n"
    "  _shared: Use the same style guide.\n"
    "---"
)


class _App(EntryPointsMixin):
    def __init__(self) -> None:
        self.notifications: list[tuple[str, str | None]] = []
        self.prompt_launches: list[dict[str, Any]] = []
        self.editor_launches: list[dict[str, Any]] = []
        self.editor_prompts: list[str] = []
        self.finished_prompts: list[str] = []
        self.patches: list[Any] = []
        self.current_idx = 0
        self._prompt_context = None
        self.pushed_screens: list[tuple[Any, Any]] = []

    def notify(self, message: str, *, severity: str | None = None) -> None:
        self.notifications.append((message, severity))

    def _show_prompt_input_bar_for_home(self, **kwargs: Any) -> None:
        self.prompt_launches.append(kwargs)

    def _select_and_open_editor_for_home(self, **kwargs: Any) -> None:
        self.editor_launches.append(kwargs)

    def _open_editor_for_agent_prompt(self, prompt: str) -> str:
        self.editor_prompts.append(prompt)
        return f"edited: {prompt}"

    def _finish_agent_launch(self, prompt: str) -> None:
        self.finished_prompts.append(prompt)

    def push_screen(self, screen: Any, callback: Any = None) -> None:
        self.pushed_screens.append((screen, callback))


class _EditorApp(EntryPointsMixin, PromptBarMountMixin):
    def __init__(self, *, editor_result: str | None = None) -> None:
        self.notifications: list[tuple[str, str | None]] = []
        self.editor_prompts: list[str] = []
        self.finished_prompts: list[str] = []
        self.mounted: list[Any] = []
        self.prompt_launches: list[dict[str, Any]] = []
        self._prompt_context = None
        self.editor_result = editor_result

    def notify(self, message: str, *, severity: str | None = None) -> None:
        self.notifications.append((message, severity))

    def _open_editor_for_agent_prompt(self, prompt: str) -> str:
        self.editor_prompts.append(prompt)
        if self.editor_result is not None:
            return self.editor_result
        return f"edited: {prompt}"

    def _finish_agent_launch(self, prompt: str) -> None:
        self.finished_prompts.append(prompt)

    def _unmount_prompt_bar(self) -> None:
        return None

    def mount(self, widget: Any) -> None:
        self.mounted.append(widget)


def _patch_missing_workspace_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(_project_file: str, _name: str) -> str:
        raise ValueError("No workspace plugin detected a workflow type")

    monkeypatch.setattr(_entry_points, "is_launchable_project", lambda _project: True)
    monkeypatch.setattr(_entry_points, "_vcs_prompt_prefix", _raise)
