"""Hook hint input processing for the ace TUI app."""

from __future__ import annotations

from ....hint_types import EditHooksResult
from ....hints import (
    is_rerun_input,
    parse_edit_hooks_input,
    parse_numeric_hint_selection,
    parse_test_targets,
)
from ._types import HintMixinBase


class HookInputProcessingMixin(HintMixinBase):
    """Mixin providing hook hint input processing."""

    def _process_hooks_input(self, user_input: str) -> None:
        """Process edit hooks input."""
        if not user_input:
            return

        if user_input == ".":
            self._show_hook_history_modal()
            return

        patch = self.patches[self.current_idx]

        if is_rerun_input(user_input):
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
                patch, result, self._hook_hint_to_idx
            )
            if success:
                self._reload_and_reposition()  # type: ignore[attr-defined]

        elif user_input.startswith("//"):
            targets = parse_test_targets(user_input)
            if not targets:
                self.notify("No test targets provided", severity="warning")  # type: ignore[attr-defined]
                return

            result = EditHooksResult(
                action_type="test_targets",
                test_targets=targets,
            )
            success = self._apply_hook_changes(  # type: ignore[attr-defined]
                patch, result, self._hook_hint_to_idx
            )
            if success:
                self._reload_and_reposition()  # type: ignore[attr-defined]

        else:
            result = EditHooksResult(
                action_type="custom_hook",
                hook_command=user_input,
            )
            success = self._apply_hook_changes(  # type: ignore[attr-defined]
                patch, result, self._hook_hint_to_idx
            )
            if success:
                self._reload_and_reposition()  # type: ignore[attr-defined]

    def _show_hook_history_modal(self) -> None:
        """Show the hook history modal for selecting a previously used hook."""
        from sase.history.hook import add_or_update_hook

        from ....hooks import add_hook_to_patch
        from ...modals import HookHistoryAction, HookHistoryModal, HookHistoryResult
        from ...widgets import HintInputBar, PatchDetail

        def _on_hook_selected(result: HookHistoryResult | None) -> None:
            if result is None:
                return

            if result.action == HookHistoryAction.EDIT_FIRST:
                if self._refocus_existing_hint_bar():
                    return

                # Re-mount hooks input bar pre-filled with the command.
                detail_widget = self.query_one("#detail-panel", PatchDetail)  # type: ignore[attr-defined]
                patch = self.patches[self.current_idx]
                query_str = self.canonical_query_string  # type: ignore[attr-defined]
                (
                    hint_mappings,
                    hook_hint_to_idx,
                    hint_to_entry_id,
                    mentor_hint_to_info,
                ) = detail_widget.update_display_with_hints(
                    patch,
                    query_str,
                    hints_for="hooks_latest_only",
                    hooks_collapsed=self.hooks_collapsed,  # type: ignore[attr-defined]
                    stitches_collapsed=self.stitches_collapsed,  # type: ignore[attr-defined]
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
                self._hint_patch_name = patch.name
                self._hint_patch_name = patch.name  # type: ignore[attr-defined]

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

            # SUBMIT action: add hook to patch.
            patch = self.patches[self.current_idx]
            success = add_hook_to_patch(
                patch.file_path,
                patch.name,
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

        patch = self.patches[self.current_idx]
        targets = getattr(self, "_failed_hooks_targets", [])

        if not targets:
            self.notify("No targets available", severity="warning")  # type: ignore[attr-defined]
            return

        parsed = parse_numeric_hint_selection(user_input, range(1, len(targets) + 1))
        invalid_parts = [*parsed.malformed, *(str(i) for i in parsed.unavailable)]
        if invalid_parts:
            self.notify(  # type: ignore[attr-defined]
                f"Invalid selections: {', '.join(invalid_parts)}",
                severity="warning",
            )
            return

        if not parsed.numbers:
            self.notify("No valid targets selected", severity="warning")  # type: ignore[attr-defined]
            return

        selected_targets = [targets[i - 1] for i in parsed.numbers]

        success = self._add_test_target_hooks(patch, selected_targets)  # type: ignore[attr-defined]
        if success:
            self._reload_and_reposition()  # type: ignore[attr-defined]
