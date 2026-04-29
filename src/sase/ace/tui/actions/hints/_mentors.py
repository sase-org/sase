"""Mentor management methods for the ace TUI app."""

from __future__ import annotations

from ....changespec import ChangeSpec
from ...widgets import ChangeSpecDetail, HintInputBar
from ._types import HintMixinBase


class MentorKillingMixin(HintMixinBase):
    """Mixin providing mentor management actions via hint mode."""

    def action_kill_mentors(self) -> None:
        """Show hints for managing mentors - delete entries, lines, or field."""
        if not self.changespecs:
            return

        changespec = self.changespecs[self.current_idx]

        if not changespec.mentors:
            self.notify("No mentors to manage", severity="warning")  # type: ignore[attr-defined]
            return

        # Re-render detail with manage hints
        detail_widget = self.query_one("#detail-panel", ChangeSpecDetail)  # type: ignore[attr-defined]
        query_str = self.canonical_query_string  # type: ignore[attr-defined]
        hint_mappings, hook_hint_to_idx, hint_to_entry_id, mentor_hint_to_info = (
            detail_widget.update_display_with_hints(
                changespec,
                query_str,
                hints_for="mentors_manage",
                hooks_collapsed=self.hooks_collapsed,  # type: ignore[attr-defined]
                commits_collapsed=self.commits_collapsed,  # type: ignore[attr-defined]
                mentors_collapsed=self.mentors_collapsed,  # type: ignore[attr-defined]
                timestamps_collapsed=self.timestamps_collapsed,  # type: ignore[attr-defined]
                deltas_collapsed=self.deltas_collapsed,  # type: ignore[attr-defined]
            )
        )

        if not mentor_hint_to_info:
            self.notify("No mentor items to manage", severity="warning")  # type: ignore[attr-defined]
            return

        # Store state for later processing
        self._hint_mode_active = True
        self._hint_mode_hints_for = "mentors_manage"
        self._hint_mappings = hint_mappings
        self._hook_hint_to_idx = hook_hint_to_idx
        self._hint_to_entry_id = hint_to_entry_id
        self._mentor_hint_to_info = mentor_hint_to_info
        self._hint_changespec_name = changespec.name

        # Mount the hint input bar
        detail_container = self.query_one("#detail-container")  # type: ignore[attr-defined]
        if not detail_container.is_attached:
            return
        hint_bar = HintInputBar(mode="mentors", id="hint-input-bar")
        detail_container.mount(hint_bar)

    def _process_mentors_input(self, user_input: str) -> None:
        """Process mentor management input - delete entries, lines, or field."""
        if not user_input:
            return

        mentor_hint_to_info = self._mentor_hint_to_info

        # Parse hint numbers from input (space-separated, ranges like 1-3)
        selected_hints: set[int] = set()
        invalid_parts: list[str] = []

        parts = user_input.split()
        for part in parts:
            if "-" in part and not part.startswith("-"):
                try:
                    start_str, end_str = part.split("-", 1)
                    start = int(start_str)
                    end = int(end_str)
                    for i in range(start, end + 1):
                        if i in mentor_hint_to_info:
                            selected_hints.add(i)
                        else:
                            invalid_parts.append(str(i))
                except ValueError:
                    invalid_parts.append(part)
            else:
                try:
                    idx = int(part)
                    if idx in mentor_hint_to_info:
                        selected_hints.add(idx)
                    else:
                        invalid_parts.append(part)
                except ValueError:
                    invalid_parts.append(part)

        if invalid_parts:
            self.notify(  # type: ignore[attr-defined]
                f"Invalid hints: {', '.join(invalid_parts)}",
                severity="warning",
            )
            return

        if not selected_hints:
            self.notify("No valid selections", severity="warning")  # type: ignore[attr-defined]
            return

        # Categorize selections
        delete_field = False
        entry_ids_to_delete: set[str] = set()
        lines_to_delete: dict[str, set[tuple[str, str]]] = {}

        for hint in selected_hints:
            entry_id = self._hint_to_entry_id[hint]
            mentor_name, profile_name = mentor_hint_to_info[hint]

            if mentor_name == "__FIELD__":
                delete_field = True
            elif mentor_name == "__ENTRY__":
                entry_ids_to_delete.add(entry_id)
            else:
                lines_to_delete.setdefault(entry_id, set()).add(
                    (mentor_name, profile_name)
                )

        # If deleting field, don't need individual entry/line deletions
        if delete_field:
            entry_ids_to_delete = set()
            lines_to_delete = {}

        changespec = self.changespecs[self.current_idx]
        self._apply_mentor_deletions(
            changespec, delete_field, entry_ids_to_delete, lines_to_delete
        )

    def _apply_mentor_deletions(
        self,
        changespec: ChangeSpec,
        delete_field: bool,
        entry_ids_to_delete: set[str],
        lines_to_delete: dict[str, set[tuple[str, str]]],
    ) -> None:
        """Apply mentor deletions - kill running mentors, then remove data."""
        import os
        import signal

        from ....changespec import (
            extract_pid_from_agent_suffix,
            parse_project_file,
        )
        from ....hooks.processes import extract_mentor_workflow_from_suffix
        from ....mentors import remove_mentor_data

        # Re-read fresh state from disk for killing
        changespecs = parse_project_file(changespec.file_path)
        target_cs = None
        for cs in changespecs:
            if cs.name == changespec.name:
                target_cs = cs
                break

        if target_cs is None or not target_cs.mentors:
            self.notify("ChangeSpec not found or no mentors", severity="error")  # type: ignore[attr-defined]
            return

        # Determine which entries have running mentors that need killing
        if delete_field:
            kill_entry_ids = {e.entry_id for e in target_cs.mentors}
        else:
            kill_entry_ids = set(entry_ids_to_delete)

        # Kill running mentors in affected entries and release workspaces
        killed_count = 0
        killed_suffixes: list[str] = []

        for entry in target_cs.mentors:
            if entry.entry_id not in kill_entry_ids:
                continue
            if not entry.status_lines:
                continue
            for sl in entry.status_lines:
                if sl.suffix_type != "running_agent" or not sl.suffix:
                    continue
                pid = extract_pid_from_agent_suffix(sl.suffix)
                if pid is None:
                    continue
                try:
                    os.killpg(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
                killed_count += 1
                killed_suffixes.append(sl.suffix)

        if killed_suffixes:
            from sase.running_field import get_claimed_workspaces, release_workspace

            for suffix in killed_suffixes:
                workflow = extract_mentor_workflow_from_suffix(suffix)
                if not workflow:
                    continue
                for claim in get_claimed_workspaces(changespec.file_path):
                    if claim.workflow == workflow and claim.cl_name == changespec.name:
                        release_workspace(
                            changespec.file_path,
                            claim.workspace_num,
                            workflow,
                            changespec.name,
                        )
                        break

        # Apply deletions to disk
        success = remove_mentor_data(
            changespec.file_path,
            changespec.name,
            delete_field=delete_field,
            entry_ids_to_delete=entry_ids_to_delete or None,
            lines_to_delete=lines_to_delete or None,
        )

        if not success:
            self.notify("Failed to update mentors", severity="error")  # type: ignore[attr-defined]
            return

        # Build notification
        msg_parts: list[str] = []
        if delete_field:
            msg_parts.append("Deleted MENTORS field")
        else:
            if entry_ids_to_delete:
                n = len(entry_ids_to_delete)
                msg_parts.append(f"Deleted {n} {'entry' if n == 1 else 'entries'}")
            total_lines = sum(len(v) for v in lines_to_delete.values())
            if total_lines:
                msg_parts.append(f"removed {total_lines} line(s)")
        if killed_count:
            msg_parts.append(f"killed {killed_count} running mentor(s)")

        self.notify(", ".join(msg_parts) if msg_parts else "No changes")  # type: ignore[attr-defined]
        self._reload_and_reposition()  # type: ignore[attr-defined]
