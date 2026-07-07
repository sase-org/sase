"""Bulk agent entry points for marked ChangeSpecs."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ....changespec import ChangeSpec


class EntryBulkMixin:
    """Mixin providing marked-ChangeSpec agent launch entry points."""

    changespecs: list[ChangeSpec]
    marked_indices: set[int]
    _bulk_changespecs: list[ChangeSpec] | None

    def _start_agents_from_marked(self) -> None:
        """Start agents for all marked ChangeSpecs.

        Shows a single prompt input bar. The prompt will be used for all
        marked items.
        """
        if not self.marked_indices:
            self.notify("No marked ChangeSpecs", severity="warning")  # type: ignore[attr-defined]
            return

        # Collect all marked ChangeSpecs (sorted by index for consistency)
        self._bulk_changespecs = [
            self.changespecs[idx]
            for idx in sorted(self.marked_indices)
            if idx < len(self.changespecs)
        ]

        if not self._bulk_changespecs:
            self.notify("No valid marked ChangeSpecs", severity="warning")  # type: ignore[attr-defined]
            self._bulk_changespecs = None
            return

        # Use first changespec for prompt context (history, etc.)
        first_cs = self._bulk_changespecs[0]
        count = len(self._bulk_changespecs)

        self.notify(f"Running agent on {count} marked ChangeSpec(s)")  # type: ignore[attr-defined]

        self._show_prompt_input_bar(  # type: ignore[attr-defined]
            first_cs.project_basename,
            cl_name=first_cs.name,
            update_target=first_cs.name,
            history_sort_key=first_cs.name,
        )
