"""Event handlers and input processing for the ace TUI app."""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from pathlib import Path

from ....hint_types import EditHooksResult, ViewFilesResult
from ....hints import (
    is_rerun_input,
    parse_edit_hooks_input,
    parse_test_targets,
    parse_view_input,
)
from ...tools.report import SlowToolCallReportSpec, write_tool_call_report
from ...widgets import HintInputBar
from ...widgets.prompt_panel._agent_display_state import CommitViewSpec
from ..clipboard import copy_to_system_clipboard
from ._types import HintMixinBase


def _expand_view_hint_part(part: str) -> list[int]:
    if "-" in part and not part.startswith("-"):
        start_text, end_text = part.split("-", 1)
        try:
            start = int(start_text)
            end = int(end_text)
        except ValueError:
            return []
        if start <= end:
            return list(range(start, end + 1))
        return []
    try:
        return [int(part)]
    except ValueError:
        return []


def _parse_view_hint_selection(
    user_input: str,
    valid_hints: set[int],
) -> tuple[list[int], bool, bool, list[int]]:
    open_in_editor = False
    copy_to_clipboard = False
    selected_hints: list[int] = []
    invalid_hints: list[int] = []

    for raw_part in user_input.split():
        part = raw_part
        if part.endswith("@"):
            open_in_editor = True
            part = part[:-1]
        elif part.endswith("%"):
            copy_to_clipboard = True
            part = part[:-1]
        if not part:
            continue

        for hint_num in _expand_view_hint_part(part):
            if hint_num not in valid_hints:
                invalid_hints.append(hint_num)
                continue
            if hint_num not in selected_hints:
                selected_hints.append(hint_num)

    return selected_hints, open_in_editor, copy_to_clipboard, invalid_hints


class InputProcessingMixin(HintMixinBase):
    """Mixin providing input processing for hint modes."""

    def on_hint_input_bar_submitted(self, event: HintInputBar.Submitted) -> None:
        """Handle hint input submission."""
        self._remove_hint_input_bar()

        if event.mode == "view":
            self._process_view_input(event.value)
        elif event.mode == "hooks":
            self._process_hooks_input(event.value)
        elif event.mode == "failed_hooks":
            self._process_failed_hooks_input(event.value)
        elif event.mode == "mentors":
            self._process_mentors_input(event.value)  # type: ignore[attr-defined]
        elif event.mode == "rewind":
            self._process_rewind_input(event.value)  # type: ignore[attr-defined]
        else:  # accept mode
            self._process_accept_input(event.value)  # type: ignore[attr-defined]

    def on_hint_input_bar_cancelled(self, event: HintInputBar.Cancelled) -> None:
        """Handle hint input cancellation."""
        del event  # unused
        self._remove_hint_input_bar()

    def _remove_hint_input_bar(self) -> None:
        """Remove the hint input bar and restore normal display."""
        # Clear hint mode state first
        self._hint_mode_active = False
        self._hint_mode_hints_for = None

        # Clear accept mode state
        self._accept_mode_active = False

        # Clear rewind mode state
        self._rewind_mode_active = False

        try:
            hint_bar = self.query_one("#hint-input-bar", HintInputBar)  # type: ignore[attr-defined]
            hint_bar.remove()
        except Exception:
            pass

        # Restore the correct tab's display
        if self.current_tab == "agents":
            self._refresh_agents_display()  # type: ignore[attr-defined]
        else:
            self._refresh_display()  # type: ignore[attr-defined]

    def _process_view_input(self, user_input: str) -> None:
        """Process view files input."""
        if not user_input:
            return

        commit_views = getattr(self, "_hint_commit_views", {})
        valid_hints = set(self._hint_mappings) | set(commit_views)
        selected_hints, open_in_editor, copy_to_clipboard, invalid_hints = (
            _parse_view_hint_selection(user_input, valid_hints)
        )

        if invalid_hints:
            self.notify(  # type: ignore[attr-defined]
                f"Invalid hints: {', '.join(str(h) for h in invalid_hints)}",
                severity="warning",
            )
            return

        commit_hint_nums = [hint for hint in selected_hints if hint in commit_views]
        files = self._files_for_view_hints(
            hint for hint in selected_hints if hint in self._hint_mappings
        )

        if not files and not commit_hint_nums:
            self.notify("No valid files selected", severity="warning")  # type: ignore[attr-defined]
            return

        if open_in_editor and commit_hint_nums:
            files = self._prepend_commit_diff_paths(commit_hint_nums, files)
            if not files:
                self.notify("No selected files could be opened", severity="warning")  # type: ignore[attr-defined]
                return

        if copy_to_clipboard and commit_hint_nums:
            self._copy_commit_selection_to_clipboard(commit_hint_nums, files)
            return

        if commit_hint_nums and not open_in_editor:
            self._open_commit_hint(commit_hint_nums)

        files = self._materialize_tool_call_reports(files)
        if not files:
            if not commit_hint_nums:
                self.notify("No selected files could be opened", severity="warning")  # type: ignore[attr-defined]
            return

        if copy_to_clipboard:
            self._copy_files_to_clipboard(files)  # type: ignore[attr-defined]
        elif open_in_editor:
            result = ViewFilesResult(
                files=files,
                open_in_editor=True,
                copy_to_clipboard=False,
                user_input=user_input,
                changespec_name=self._hint_changespec_name,
            )
            self._open_files_in_editor(result)  # type: ignore[attr-defined]
        else:
            from ...graphics import is_supported_image_path, is_supported_video_path

            if any(
                is_supported_image_path(f) or is_supported_video_path(f) for f in files
            ):
                self._view_files_with_artifact_viewer(files)  # type: ignore[attr-defined]
            else:
                self._view_files_with_pager(files)  # type: ignore[attr-defined]

    def _files_for_view_hints(self, hint_nums: Iterable[int]) -> list[str]:
        hint_input = " ".join(str(hint_num) for hint_num in hint_nums)
        files, _, _, _ = parse_view_input(hint_input, self._hint_mappings)
        return files

    def _prepend_commit_diff_paths(
        self,
        commit_hint_nums: list[int],
        files: list[str],
    ) -> list[str]:
        commit_views = getattr(self, "_hint_commit_views", {})
        selected_files: list[str] = []
        missing: list[str] = []
        for hint_num in commit_hint_nums:
            spec = commit_views[hint_num]
            if spec.diff_path:
                path = os.path.expanduser(spec.diff_path)
                if path not in selected_files:
                    selected_files.append(path)
            else:
                missing.append(spec.short_sha or spec.sha or str(hint_num))
        if missing:
            self.notify(  # type: ignore[attr-defined]
                f"No raw diff path for commit(s): {', '.join(missing)}",
                severity="warning",
            )
        for file_path in files:
            if file_path not in selected_files:
                selected_files.append(file_path)
        return selected_files

    def _open_commit_hint(self, commit_hint_nums: list[int]) -> None:
        commit_views = getattr(self, "_hint_commit_views", {})
        self._open_commit_view(tuple(commit_views[hint] for hint in commit_hint_nums))

    def _open_commit_view(self, specs: Sequence[CommitViewSpec]) -> None:
        from ...modals.commit_view_modal import CommitViewModal

        self.app.push_screen(CommitViewModal(specs))  # type: ignore[attr-defined]

    def _copy_commit_selection_to_clipboard(
        self,
        commit_hint_nums: list[int],
        files: list[str],
    ) -> None:
        commit_views = getattr(self, "_hint_commit_views", {})
        shas = [
            commit_views[hint_num].short_sha or commit_views[hint_num].sha
            for hint_num in commit_hint_nums
        ]
        shas = [sha for sha in shas if sha]
        if not files:
            content = " ".join(shas)
            if copy_to_system_clipboard(content):
                self.notify(f"Copied {len(shas)} commit SHA(s) to clipboard")  # type: ignore[attr-defined]
            else:
                self.notify("Failed to copy to clipboard", severity="error")  # type: ignore[attr-defined]
            return

        home = str(Path.home())
        shortened_files = [
            f.replace(home, "~", 1) if f.startswith(home) else f for f in files
        ]
        content = " ".join([*shas, *shortened_files])
        if copy_to_system_clipboard(content):
            self.notify("Copied commit SHA(s) and path(s) to clipboard")  # type: ignore[attr-defined]
        else:
            self.notify("Failed to copy to clipboard", severity="error")  # type: ignore[attr-defined]

    def _materialize_tool_call_reports(self, files: list[str]) -> list[str]:
        reports: dict[str, SlowToolCallReportSpec] = getattr(
            self, "_hint_tool_call_reports", {}
        )
        if not reports:
            return files

        materialized: list[str] = []
        for file_path in files:
            spec = reports.get(file_path)
            if spec is None:
                materialized.append(file_path)
                continue
            report_path = write_tool_call_report(spec)
            if report_path is None:
                self.notify(  # type: ignore[attr-defined]
                    f"Failed to build tool-call report: {file_path}",
                    severity="error",
                )
                continue
            materialized.append(report_path)
        return materialized

    def _process_hooks_input(self, user_input: str) -> None:
        """Process edit hooks input."""
        if not user_input:
            return

        if user_input == ".":
            self._show_hook_history_modal()
            return

        changespec = self.changespecs[self.current_idx]

        if is_rerun_input(user_input):
            # Rerun/delete hooks
            hints_to_rerun, hints_to_delete, invalid_hints = parse_edit_hooks_input(
                user_input, self._hint_mappings
            )

            if invalid_hints:
                self.notify(  # type: ignore[attr-defined]
                    f"Invalid hints: {', '.join(str(h) for h in invalid_hints)}",
                    severity="warning",
                )
                return

            if not hints_to_rerun and not hints_to_delete:
                self.notify("No valid hooks selected", severity="warning")  # type: ignore[attr-defined]
                return

            result = EditHooksResult(
                action_type="rerun_delete",
                hints_to_rerun=hints_to_rerun,
                hints_to_delete=hints_to_delete,
            )
            success = self._apply_hook_changes(  # type: ignore[attr-defined]
                changespec, result, self._hook_hint_to_idx
            )
            if success:
                self._reload_and_reposition()  # type: ignore[attr-defined]

        elif user_input.startswith("//"):
            # Test targets
            targets = parse_test_targets(user_input)
            if not targets:
                self.notify("No test targets provided", severity="warning")  # type: ignore[attr-defined]
                return

            result = EditHooksResult(
                action_type="test_targets",
                test_targets=targets,
            )
            success = self._apply_hook_changes(  # type: ignore[attr-defined]
                changespec, result, self._hook_hint_to_idx
            )
            if success:
                self._reload_and_reposition()  # type: ignore[attr-defined]

        else:
            # Custom hook command
            result = EditHooksResult(
                action_type="custom_hook",
                hook_command=user_input,
            )
            success = self._apply_hook_changes(  # type: ignore[attr-defined]
                changespec, result, self._hook_hint_to_idx
            )
            if success:
                self._reload_and_reposition()  # type: ignore[attr-defined]

    def _show_hook_history_modal(self) -> None:
        """Show the hook history modal for selecting a previously used hook."""
        from sase.history.hook import add_or_update_hook

        from ....hooks import add_hook_to_changespec
        from ...modals import HookHistoryAction, HookHistoryModal, HookHistoryResult
        from ...widgets import ChangeSpecDetail, HintInputBar

        def _on_hook_selected(result: HookHistoryResult | None) -> None:
            if result is None:
                return

            if result.action == HookHistoryAction.EDIT_FIRST:
                if self._refocus_existing_hint_bar():
                    return

                # Re-mount hooks input bar pre-filled with the command
                detail_widget = self.query_one("#detail-panel", ChangeSpecDetail)  # type: ignore[attr-defined]
                changespec = self.changespecs[self.current_idx]
                query_str = self.canonical_query_string  # type: ignore[attr-defined]
                (
                    hint_mappings,
                    hook_hint_to_idx,
                    hint_to_entry_id,
                    mentor_hint_to_info,
                ) = detail_widget.update_display_with_hints(
                    changespec,
                    query_str,
                    hints_for="hooks_latest_only",
                    hooks_collapsed=self.hooks_collapsed,  # type: ignore[attr-defined]
                    commits_collapsed=self.commits_collapsed,  # type: ignore[attr-defined]
                    mentors_collapsed=self.mentors_collapsed,  # type: ignore[attr-defined]
                    timestamps_collapsed=self.timestamps_collapsed,  # type: ignore[attr-defined]
                    deltas_collapsed=self.deltas_collapsed,  # type: ignore[attr-defined]
                )
                self._hint_mode_active = True
                self._hint_mode_hints_for = "hooks_latest_only"
                self._hint_mappings = hint_mappings
                self._hook_hint_to_idx = hook_hint_to_idx
                self._hint_to_entry_id = hint_to_entry_id
                self._mentor_hint_to_info = mentor_hint_to_info
                self._hint_changespec_name = changespec.name

                detail_container = self.query_one("#detail-container")  # type: ignore[attr-defined]
                if not detail_container.is_attached:
                    return
                hint_bar = HintInputBar(
                    mode="hooks",
                    initial_value=result.command,
                    id="hint-input-bar",
                )
                detail_container.mount(hint_bar)
                return

            # SUBMIT action — add hook to changespec
            changespec = self.changespecs[self.current_idx]
            success = add_hook_to_changespec(
                changespec.file_path,
                changespec.name,
                result.command,
                None,
            )
            if success:
                add_or_update_hook(result.command)
                self.notify(f"Added hook: {result.command}")  # type: ignore[attr-defined]
                self._reload_and_reposition()  # type: ignore[attr-defined]
            else:
                self.notify("Error adding hook", severity="error")  # type: ignore[attr-defined]

        self.app.push_screen(HookHistoryModal(), _on_hook_selected)  # type: ignore[attr-defined]

    def _process_failed_hooks_input(self, user_input: str) -> None:
        """Process failed hooks input to add selected targets as hooks.

        Input can be:
        - Single numbers: "1", "2", "3"
        - Space-separated: "1 3 5"
        - Ranges: "1-5"
        - Mixed: "1 3-5 7"
        """
        if not user_input:
            return

        changespec = self.changespecs[self.current_idx]
        targets = getattr(self, "_failed_hooks_targets", [])

        if not targets:
            self.notify("No targets available", severity="warning")  # type: ignore[attr-defined]
            return

        # Parse the input to get selected indices (1-based)
        selected_indices: set[int] = set()
        invalid_parts: list[str] = []

        parts = user_input.split()
        for part in parts:
            if "-" in part and not part.startswith("-"):
                # Range like "1-5"
                try:
                    start_str, end_str = part.split("-", 1)
                    start = int(start_str)
                    end = int(end_str)
                    for i in range(start, end + 1):
                        if 1 <= i <= len(targets):
                            selected_indices.add(i)
                        else:
                            invalid_parts.append(str(i))
                except ValueError:
                    invalid_parts.append(part)
            else:
                # Single number
                try:
                    idx = int(part)
                    if 1 <= idx <= len(targets):
                        selected_indices.add(idx)
                    else:
                        invalid_parts.append(part)
                except ValueError:
                    invalid_parts.append(part)

        if invalid_parts:
            self.notify(  # type: ignore[attr-defined]
                f"Invalid selections: {', '.join(invalid_parts)}",
                severity="warning",
            )
            return

        if not selected_indices:
            self.notify("No valid targets selected", severity="warning")  # type: ignore[attr-defined]
            return

        # Get the selected targets (convert 1-based to 0-based)
        selected_targets = [targets[i - 1] for i in sorted(selected_indices)]

        # Add them as hooks
        success = self._add_test_target_hooks(changespec, selected_targets)  # type: ignore[attr-defined]
        if success:
            self._reload_and_reposition()  # type: ignore[attr-defined]
