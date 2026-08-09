"""Agent start entry point facade for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
    from ....patch import Patch
    from ...models import Agent
    from ...modals import SelectionItem
    from ._types import PromptContext, TabName


def _vcs_prompt_prefix(project_file: str, name: str) -> str:
    """Build a workspace prompt prefix such as ``#gh:name ``.

    Args:
        project_file: Path to the project spec file.
        name: Project or Patch name to embed in the prefix.

    Returns:
        A string such as ``"#gh:my_cl "``.
    """
    from sase.workspace_provider import detect_workflow_type

    workflow_type = detect_workflow_type(project_file)
    return f"#{workflow_type}:{name} "


def _rewrite_retry_prompt_name(
    raw_prompt: str,
    retry_name: str,
    *,
    current_agent_name: str | None = None,
) -> str:
    """Replace or prepend the top-level prompt ``%id`` directive for retry."""
    return rewrite_retry_prompt_name(
        raw_prompt,
        retry_name,
        current_agent_name=current_agent_name,
    )


def _force_name_reuse_in_prompt(
    raw_prompt: str,
    replacement_name: str | None = None,
) -> str:
    """Mark an explicit top-level prompt ``%id`` directive for forced reuse."""
    return force_name_reuse_in_prompt(raw_prompt, replacement_name=replacement_name)


class _EntryPointsBaseMixin:
    """Shared state and compatibility helpers for entry point mixins."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    patches: list[Patch]
    current_idx: int
    current_tab: TabName
    marked_indices: set[int]
    _agents: list[Agent]

    # State for prompt input
    _prompt_context: PromptContext | None = None
    # State for bulk agent runs
    _bulk_patches: list[Patch] | None = None
    # State for repeat-last-+/Ctrl+Space selection
    _last_custom_agent_selection: SelectionItem | None = None

    @property
    def changespecs(self) -> list[Patch]:
        return getattr(self, "patches", [])

    @changespecs.setter
    def changespecs(self, value: list[Patch]) -> None:
        self.patches = value

    @property
    def _bulk_changespecs(self) -> Any:
        return getattr(self, "_bulk_patches", None)

    @_bulk_changespecs.setter
    def _bulk_changespecs(self, value: Any) -> None:
        self._bulk_patches = value

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

    def _rewrite_retry_prompt_name(
        self,
        raw_prompt: str,
        retry_name: str,
        *,
        current_agent_name: str | None = None,
    ) -> str:
        return _rewrite_retry_prompt_name(
            raw_prompt,
            retry_name,
            current_agent_name=current_agent_name,
        )

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
        from sase.project_display_names import project_display_name_for

        self._last_custom_agent_selection = None
        clear_last_agent_selection()
        display_name = project_display_name_for(project_name)
        self.notify(  # type: ignore[attr-defined]
            "Saved +/Ctrl+Space selection is stale: "
            f"project {display_name!r} is not launchable; cleared saved selection",
            severity="warning",
        )

    def _clear_default_home_replay_selection(self) -> None:
        from sase.ace.last_agent_selection import clear_last_agent_selection

        self._last_custom_agent_selection = None
        clear_last_agent_selection()
        self.notify(  # type: ignore[attr-defined]
            "Saved +/Ctrl+Space selection was the implicit #git:home default; "
            "cleared it (use the home keymap to start a home-mode agent)",
            severity="warning",
        )

    def _selection_replays_default_vcs_prefix(self, selection: SelectionItem) -> bool:
        """Whether replaying *selection* would only reopen the implicit default.

        A bare home-mode launch normalizes to ``#git:home``; an older save path
        persisted that as a ``project`` selection for ``home``. Replaying such a
        selection pre-fills the prompt bar with the implicit default rather than
        a user-chosen VCS workflow, so it must be treated as non-replayable. The
        computed/default-normalized prefix is compared (not just
        ``project_name == "home"``) so a genuine non-default provider ref does
        not get rejected. ``item_type == "home"`` selections are left untouched
        and still open an empty home prompt.
        """
        if selection.item_type not in ("project", "cl"):
            return False
        name = (
            selection.cl_name
            if selection.item_type == "cl" and selection.cl_name
            else selection.project_name
        )
        if not name:
            return False

        from sase.ace.patch.project_spec_path import preferred_project_spec_path
        from sase.core.paths import sase_projects_dir

        project_dir = str(sase_projects_dir() / selection.project_name)
        project_file = preferred_project_spec_path(project_dir, selection.project_name)
        try:
            prefix = _vcs_prompt_prefix(project_file, name)
        except ValueError:
            return False

        from sase.history.vcs_xprompt_mru import is_default_vcs_xprompt_prefix

        return is_default_vcs_xprompt_prefix(prefix)

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

        # Only launchable selections reach here, so computing the VCS prefix
        # for the default-home check is cheap and never hits the missing/stale
        # project path guarded by the launchability check above.
        if last is not None and self._selection_replays_default_vcs_prefix(last):
            self._clear_default_home_replay_selection()
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
