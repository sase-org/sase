"""Agent start entry point facade for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.modals.project_discovery import is_launchable_project

from ._entry_bulk import EntryBulkMixin
from ._entry_custom import EntryCustomMixin
from ._entry_name_prompts import (
    force_name_reuse_in_prompt,
    rewrite_retry_prompt_name,
)
from ._entry_prompt_history import EntryPromptHistoryMixin
from ._entry_quick_launch import EntryQuickLaunchMixin
from ._entry_relaunch import EntryRelaunchMixin

if TYPE_CHECKING:
    from ....changespec import ChangeSpec
    from ...models import Agent
    from ...modals import SelectionItem
    from ._types import PromptContext, TabName


def _vcs_prompt_prefix(project_file: str, name: str) -> str:
    """Build a VCS prompt prefix like ``#gh:name `` or ``#hg:name ``.

    Args:
        project_file: Path to the project spec file.
        name: Project or CL name to embed in the prefix.

    Returns:
        A string such as ``"#gh:my_cl "`` or ``"#hg:my_cl "``.
    """
    from sase.workspace_provider import detect_workflow_type

    workflow_type = detect_workflow_type(project_file)
    return f"#{workflow_type}:{name} "


def _rewrite_retry_prompt_name(raw_prompt: str, retry_name: str) -> str:
    """Replace or prepend the top-level prompt name directive for retry."""
    return rewrite_retry_prompt_name(raw_prompt, retry_name)


def _force_name_reuse_in_prompt(
    raw_prompt: str,
    replacement_name: str | None = None,
) -> str:
    """Mark an explicit top-level prompt name directive for forced reuse."""
    return force_name_reuse_in_prompt(raw_prompt, replacement_name=replacement_name)


class _EntryPointsBaseMixin:
    """Shared state and compatibility helpers for entry point mixins."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: TabName
    marked_indices: set[int]
    _agents: list[Agent]

    # State for prompt input
    _prompt_context: PromptContext | None = None
    # State for bulk agent runs
    _bulk_changespecs: list[ChangeSpec] | None = None
    # State for repeat-last-+/Ctrl+Space selection
    _last_custom_agent_selection: SelectionItem | None = None

    def _vcs_prompt_prefix_or_notify(self, project_file: str, name: str) -> str | None:
        """Build a VCS prompt prefix, or show a TUI error when detection fails."""
        try:
            return _vcs_prompt_prefix(project_file, name)
        except ValueError as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Cannot start agent for {name}: {exc}", severity="error"
            )
            return None

    def _is_launchable_project(self, project_name: str) -> bool:
        return is_launchable_project(project_name)

    def _rewrite_retry_prompt_name(self, raw_prompt: str, retry_name: str) -> str:
        return _rewrite_retry_prompt_name(raw_prompt, retry_name)

    def _force_name_reuse_in_prompt(
        self,
        raw_prompt: str,
        replacement_name: str | None = None,
    ) -> str:
        return _force_name_reuse_in_prompt(
            raw_prompt, replacement_name=replacement_name
        )

    def _clear_stale_last_custom_agent_selection(self, project_name: str) -> None:
        from sase.ace.last_agent_selection import clear_last_agent_selection

        self._last_custom_agent_selection = None
        clear_last_agent_selection()
        self.notify(  # type: ignore[attr-defined]
            "Saved +/Ctrl+Space selection is stale: "
            f"project {project_name!r} is not launchable; cleared saved selection",
            severity="warning",
        )

    def _last_selection_is_replayable(self, selection: SelectionItem) -> bool:
        if selection.item_type == "home":
            return True
        if selection.item_type not in ("project", "cl"):
            return False
        return self._is_launchable_project(selection.project_name)

    def _load_last_custom_agent_selection(self) -> tuple[SelectionItem | None, bool]:
        last = self._last_custom_agent_selection
        if last is None:
            from sase.ace.last_agent_selection import load_last_agent_selection

            last = load_last_agent_selection()
            if last is not None:
                self._last_custom_agent_selection = last

        if last is not None and not self._last_selection_is_replayable(last):
            self._clear_stale_last_custom_agent_selection(last.project_name)
            return None, True

        return last, False


class EntryPointsMixin(
    EntryCustomMixin,
    EntryPromptHistoryMixin,
    EntryQuickLaunchMixin,
    EntryRelaunchMixin,
    EntryBulkMixin,
    _EntryPointsBaseMixin,
):
    """Mixin providing agent start entry points."""

    pass


__all__ = [
    "EntryPointsMixin",
    "_force_name_reuse_in_prompt",
    "_rewrite_retry_prompt_name",
    "_vcs_prompt_prefix",
    "is_launchable_project",
]
