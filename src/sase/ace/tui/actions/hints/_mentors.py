"""Mentor killing methods for the ace TUI app."""

from __future__ import annotations

from ....changespec import ChangeSpec
from ...widgets import ChangeSpecDetail, HintInputBar
from ._types import HintMixinBase


class MentorKillingMixin(HintMixinBase):
    """Mixin providing mentor killing actions via hint mode."""

    def action_kill_mentors(self) -> None:
        """Show hints for running mentors and allow killing selected ones."""
        if not self.changespecs:
            return

        changespec = self.changespecs[self.current_idx]

        # Check if there are any running mentors
        has_running = False
        if changespec.mentors:
            for entry in changespec.mentors:
                if entry.status_lines:
                    for sl in entry.status_lines:
                        if sl.suffix_type == "running_agent":
                            has_running = True
                            break
                if has_running:
                    break

        if not has_running:
            self.notify("No running mentors to kill", severity="warning")  # type: ignore[attr-defined]
            return

        # Re-render detail with hints for running mentors
        detail_widget = self.query_one("#detail-panel", ChangeSpecDetail)  # type: ignore[attr-defined]
        query_str = self.canonical_query_string  # type: ignore[attr-defined]
        hint_mappings, hook_hint_to_idx, hint_to_entry_id, mentor_hint_to_info = (
            detail_widget.update_display_with_hints(
                changespec,
                query_str,
                hints_for="mentors_running",
                hooks_collapsed=self.hooks_collapsed,  # type: ignore[attr-defined]
                commits_collapsed=self.commits_collapsed,  # type: ignore[attr-defined]
                mentors_collapsed=self.mentors_collapsed,  # type: ignore[attr-defined]
            )
        )

        if not mentor_hint_to_info:
            self.notify("No running mentors found", severity="warning")  # type: ignore[attr-defined]
            return

        # Store state for later processing
        self._hint_mode_active = True
        self._hint_mode_hints_for = "mentors_running"
        self._hint_mappings = hint_mappings
        self._hook_hint_to_idx = hook_hint_to_idx
        self._hint_to_entry_id = hint_to_entry_id
        self._mentor_hint_to_info = mentor_hint_to_info
        self._hint_changespec_name = changespec.name

        # Mount the hint input bar
        detail_container = self.query_one("#detail-container")  # type: ignore[attr-defined]
        hint_bar = HintInputBar(mode="mentors", id="hint-input-bar")
        detail_container.mount(hint_bar)

    def _process_mentors_input(self, user_input: str) -> None:
        """Process mentor kill input - kill selected running mentors."""
        if not user_input:
            return

        changespec = self.changespecs[self.current_idx]
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
            self.notify("No valid mentors selected", severity="warning")  # type: ignore[attr-defined]
            return

        # Kill the selected mentors
        self._kill_selected_mentors(changespec, selected_hints)

    def _kill_selected_mentors(
        self,
        changespec: ChangeSpec,
        selected_hints: set[int],
    ) -> None:
        """Kill selected running mentor processes and mark them as killed."""
        from ....changespec import parse_project_file
        from ....hooks.processes import (
            extract_mentor_workflow_from_suffix,
            mark_mentor_agents_as_killed,
        )
        from ....mentors import update_changespec_mentors_field

        # Re-read fresh state from disk
        changespecs = parse_project_file(changespec.file_path)
        target_cs = None
        for cs in changespecs:
            if cs.name == changespec.name:
                target_cs = cs
                break

        if target_cs is None or not target_cs.mentors:
            self.notify("ChangeSpec not found", severity="error")  # type: ignore[attr-defined]
            return

        # Build set of (entry_id, profile_name, mentor_name) to kill
        mentors_to_kill: set[tuple[str, str, str]] = set()
        for hint in selected_hints:
            entry_id = self._hint_to_entry_id[hint]
            mentor_name, profile_name = self._mentor_hint_to_info[hint]
            mentors_to_kill.add((entry_id, profile_name, mentor_name))

        # Find and kill matching running mentor processes
        import os
        import signal

        from ....changespec import (
            MentorEntry,
            MentorStatusLine,
            extract_pid_from_agent_suffix,
        )

        killed_agents: list[tuple[MentorEntry, MentorStatusLine, int]] = []
        killed_count = 0

        for entry in target_cs.mentors:
            if not entry.status_lines:
                continue
            for sl in entry.status_lines:
                if sl.suffix_type != "running_agent" or not sl.suffix:
                    continue
                key = (entry.entry_id, sl.profile_name, sl.mentor_name)
                if key not in mentors_to_kill:
                    continue

                pid = extract_pid_from_agent_suffix(sl.suffix)
                if pid is None:
                    continue

                try:
                    os.killpg(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass

                killed_agents.append((entry, sl, pid))
                killed_count += 1

        if killed_agents:
            # Mark killed mentors with killed_agent suffix_type
            updated_mentors = mark_mentor_agents_as_killed(
                target_cs.mentors, killed_agents
            )
            update_changespec_mentors_field(
                changespec.file_path, changespec.name, updated_mentors
            )

            # Release workspaces claimed by killed mentor processes
            from sase.running_field import get_claimed_workspaces, release_workspace

            for _, status_line, _ in killed_agents:
                suffix = status_line.suffix
                if not suffix:
                    continue

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

        self.notify(f"Killed {killed_count} mentor(s)")  # type: ignore[attr-defined]
        self._reload_and_reposition()  # type: ignore[attr-defined]
