"""Bulk agent entry points for marked Patches."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ....patch import Patch


class EntryBulkMixin:
    """Mixin providing marked-Patch agent launch entry points."""

    patches: list[Patch]
    marked_indices: set[int]
    _bulk_patches: list[Patch] | None

    def _start_agents_from_marked(self) -> None:
        """Start agents for all marked Patches.

        Shows a single prompt input bar. The prompt will be used for all
        marked items.
        """
        if not self.marked_indices:
            self.notify("No marked Patches", severity="warning")  # type: ignore[attr-defined]
            return

        # Collect all marked Patches (sorted by index for consistency)
        self._bulk_patches = [
            self.patches[idx]
            for idx in sorted(self.marked_indices)
            if idx < len(self.patches)
        ]

        if not self._bulk_patches:
            self.notify("No valid marked Patches", severity="warning")  # type: ignore[attr-defined]
            self._bulk_patches = None
            return

        # Use first patch for prompt context (history, etc.)
        first_cs = self._bulk_patches[0]
        count = len(self._bulk_patches)

        self.notify(f"Running agent on {count} marked Patch(s)")  # type: ignore[attr-defined]

        self._show_prompt_input_bar(  # type: ignore[attr-defined]
            first_cs.project_basename,
            cl_name=first_cs.name,
            update_target=first_cs.name,
            history_sort_key=first_cs.name,
        )
