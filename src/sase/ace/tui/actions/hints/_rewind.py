"""Rewind workflow methods for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...widgets import HintInputBar
from ._types import HintMixinBase

if TYPE_CHECKING:
    from ....patch import Patch


class RewindMixin(HintMixinBase):
    """Mixin providing rewind workflow actions."""

    # Type hints for attributes accessed from AceApp
    _rewind_mode_active: bool

    def action_start_rewind(self) -> None:
        """Start rewind mode - prompt user to select entry to rewind to."""
        if self._refocus_existing_hint_bar():
            return

        if not self.patches:
            return

        patch = self.patches[self.current_idx]

        # Check if there are at least 2 all-numeric COMMITS entries
        # (we need an entry after the selected one)
        numeric_entries = [e for e in (patch.commits or []) if not e.is_proposed]
        if len(numeric_entries) < 2:
            self.notify(  # type: ignore[attr-defined]
                "Need at least 2 accepted commits to rewind",
                severity="warning",
            )
            return

        # Build placeholder with available entry numbers (excluding the last one)
        # since you can't rewind to the last entry
        available_nums = sorted([e.number for e in numeric_entries])
        # All but the last can be selected
        selectable_nums = available_nums[:-1]
        placeholder = f"Enter entry number to rewind to ({selectable_nums[0]}-{selectable_nums[-1]})"

        # Store rewind mode state
        self._rewind_mode_active = True

        # Mount the rewind input bar
        detail_container = self.query_one("#detail-container")  # type: ignore[attr-defined]
        if not detail_container.is_attached:
            return
        rewind_bar = HintInputBar(
            mode="rewind", placeholder=placeholder, id="hint-input-bar"
        )
        detail_container.mount(rewind_bar)

    def _process_rewind_input(self, user_input: str) -> None:
        """Process the selected entry number for rewind.

        Supports a ``!`` suffix (e.g. ``3!``) to skip VCS operations
        and only perform bookkeeping (renumber Patch + timestamp).

        Args:
            user_input: The user's input (entry number, optionally with ``!``).
        """
        if not user_input:
            return

        patch = self.patches[self.current_idx]

        # Strip trailing '!' suffix for bookkeeping-only mode
        stripped = user_input.strip()
        skip_vcs = stripped.endswith("!")
        if skip_vcs:
            stripped = stripped[:-1]

        # Parse and validate entry number
        try:
            selected_entry_num = int(stripped)
        except ValueError:
            self.notify(  # type: ignore[attr-defined]
                f"Invalid entry number: {user_input}",
                severity="warning",
            )
            return

        # Validate entry exists and is all-numeric (accepted)
        numeric_entries = [e for e in (patch.commits or []) if not e.is_proposed]
        entry_nums = {e.number for e in numeric_entries}

        if selected_entry_num not in entry_nums:
            self.notify(  # type: ignore[attr-defined]
                f"Entry ({selected_entry_num}) not found or is a proposal",
                severity="warning",
            )
            return

        # Validate there's at least one all-numeric entry AFTER the selected one
        entries_after = [e for e in numeric_entries if e.number > selected_entry_num]
        if not entries_after:
            self.notify(  # type: ignore[attr-defined]
                f"No entries after ({selected_entry_num}) - cannot rewind to last entry",
                severity="warning",
            )
            return

        # Validate selected entry has a DIFF file (skip in bookkeeping-only mode)
        if not skip_vcs:
            selected_entry = next(
                (e for e in numeric_entries if e.number == selected_entry_num), None
            )
            if not selected_entry or not selected_entry.diff:
                self.notify(  # type: ignore[attr-defined]
                    f"Entry ({selected_entry_num}) has no DIFF path",
                    severity="warning",
                )
                return

        # Run rewind workflow
        self._run_rewind_workflow(patch, selected_entry_num, skip_vcs=skip_vcs)

    def _run_rewind_workflow(
        self,
        patch: Patch,
        selected_entry_num: int,
        *,
        skip_vcs: bool = False,
    ) -> None:
        """Execute the rewind workflow.

        Args:
            patch: The Patch to rewind.
            selected_entry_num: The entry number to rewind to.
            skip_vcs: If True, skip VCS operations (bookkeeping only).
        """
        cl_name = patch.name
        project_file = patch.file_path
        from ..patch_durable import submit_patch_operation

        submitted = submit_patch_operation(
            self,
            verb="rewind",
            name=cl_name,
            project_file=project_file,
            extra_argv=(str(selected_entry_num),),
            payload={"entry": selected_entry_num, "skip_vcs": skip_vcs},
        )

        if submitted:
            suffix = " (bookkeeping only)" if skip_vcs else ""
            self.notify(f"Rewinding to entry ({selected_entry_num}){suffix}...")  # type: ignore[attr-defined]
