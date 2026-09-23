"""Patches-tab binding computation for :class:`KeybindingFooter`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...hooks import get_failed_hooks_file_path
from ...operations import get_available_workflows
from ...patch import Patch
from .._artifact_tab_model import DEFAULT_ARTIFACTS_RELATIONS_COLLAPSED


class PatchBindingsMixin:
    """Entry-dependent bindings for the Patches tab."""

    if TYPE_CHECKING:

        def _kd(self, action_name: str) -> str: ...

    def _compute_available_bindings(
        self,
        patch: Patch,
        *,
        mark_count: int = 0,
    ) -> list[tuple[str, str]]:
        """Compute conditional bindings for Patches tab.

        Includes entry-dependent bindings (based on the selected Patch)
        and app-state bindings (e.g. marks exist).
        """
        bindings: list[tuple[str, str]] = []

        # Accept proposal (only if proposed entries exist)
        if patch.commits and any(e.is_proposed for e in patch.commits):
            bindings.append((self._kd("accept_proposal"), "accept"))

        # Diff (only if PR exists)
        if patch.pr_url is not None:
            bindings.append((self._kd("show_diff"), "diff"))

        # Get base status for visibility checks
        from ...patch import get_base_status

        base_status = get_base_status(patch.status)

        _EDITABLE = ("WIP", "Draft", "Ready", "Mailed")

        # Reword (only if PR exists AND status is editable)
        if patch.pr_url is not None:
            if base_status in _EDITABLE:
                bindings.append((self._kd("reword"), "reword"))

        # Add tag (only if PR exists AND status is editable)
        if patch.pr_url is not None:
            if base_status in _EDITABLE:
                bindings.append((self._kd("add_tag"), "add tag"))

        # Mail (only if status is Ready)
        if base_status == "Ready":
            bindings.append((self._kd("mail"), "mail"))

        # Rebase (only if status is editable)
        if base_status in _EDITABLE:
            bindings.append((self._kd("rebase"), "rebase"))

        # Rewind (only if status is not Submitted/Reverted and >=2 accepted entries)
        if base_status not in ("Submitted", "Reverted") and patch.commits:
            numeric_entries = [e for e in patch.commits if not e.is_proposed]
            if len(numeric_entries) >= 2:
                bindings.append((self._kd("start_rewind"), "rewind"))

        # Sync (only if status is editable)
        if base_status in _EDITABLE:
            bindings.append((self._kd("sync"), "sync"))

        # Rename (only if status is not Submitted or Reverted)
        if base_status not in ("Submitted", "Reverted"):
            bindings.append((self._kd("rename_cl"), "rename"))

        # View files (only if PR exists)
        if patch.pr_url is not None:
            bindings.append((self._kd("view_files"), "files"))

        # Hooks from failed targets (only if failed hooks file exists)
        if get_failed_hooks_file_path(patch):
            bindings.append((self._kd("hooks_or_collapse_all"), "hooks (failed)"))

        # Run workflows (only if workflows available for this Patch)
        workflows = get_available_workflows(patch)
        if len(workflows) == 1:
            bindings.append((self._kd("run_workflow"), f"run {workflows[0]}"))
        elif len(workflows) > 1:
            bindings.append(
                (self._kd("run_workflow"), f"run ({len(workflows)} workflows)")
            )

        # --- App-state bindings ---

        # Marks (only when marks exist)
        if mark_count > 0:
            bindings.append(
                (self._kd("bulk_change_status"), f"bulk status ({mark_count})")
            )
            bindings.append((self._kd("clear_marks"), f"unmark ({mark_count})"))

        app = getattr(self, "_app", None)
        keymap = getattr(app, "_relation_keymap", None) if app is not None else None
        if keymap:
            collapsed = bool(
                getattr(
                    app,
                    "artifacts_relations_collapsed",
                    DEFAULT_ARTIFACTS_RELATIONS_COLLAPSED,
                )
            )
            bindings.append(
                (
                    self._kd("toggle_relation_panel"),
                    "expand relations" if collapsed else "collapse relations",
                )
            )

        return bindings
