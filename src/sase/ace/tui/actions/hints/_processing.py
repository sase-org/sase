"""Event handlers and input processing for the ace TUI app."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from sase.memory.legacy_glossary_read_report import (
    GlossaryReadReportSpec,
    write_glossary_read_report,
)
from sase.memory.memory_read_report import (
    MemoryReadReportSpec,
    write_memory_read_report,
)
from sase.pager import link_pager_enabled

from ....hint_types import EditHooksResult, ViewFilesResult
from ....hints import (
    is_rerun_input,
    parse_edit_hooks_input,
    parse_numeric_hint_selection,
    parse_test_targets,
    parse_view_input,
)
from ...tools.report import SlowToolCallReportSpec, write_tool_call_report
from ...widgets import HintInputBar
from ...widgets.prompt_panel._agent_display_state import CommitViewSpec
from ..clipboard import schedule_copy_delivery
from ._files import build_pager_document
from ._types import HintMixinBase

type _HintReportSpec = (
    SlowToolCallReportSpec | GlossaryReadReportSpec | MemoryReadReportSpec
)


@dataclass(frozen=True)
class _ViewRequest:
    """Immutable destination intent captured from one submitted view action."""

    files: tuple[str, ...]
    open_in_editor: bool
    copy_to_clipboard: bool
    user_input: str
    patch_name: str
    commit_specs: tuple[CommitViewSpec, ...]


@dataclass(frozen=True)
class _MaterializedReports:
    files: tuple[str, ...]
    failed_paths: tuple[str, ...]


@dataclass(frozen=True)
class _PreparedViewRequest:
    request: _ViewRequest
    report_items: tuple[tuple[str, _HintReportSpec], ...]


def _write_selected_hint_reports(
    files: tuple[str, ...],
    report_items: tuple[tuple[str, _HintReportSpec], ...],
) -> _MaterializedReports:
    """Materialize selected reports without touching Textual application state."""
    reports = dict(report_items)
    materialized: list[str] = []
    failed: list[str] = []
    for file_path in files:
        spec = reports.get(file_path)
        if spec is None:
            materialized.append(file_path)
            continue
        if isinstance(spec, MemoryReadReportSpec):
            report_path = write_memory_read_report(spec)
        elif isinstance(spec, GlossaryReadReportSpec):
            report_path = write_glossary_read_report(spec)
        else:
            report_path = write_tool_call_report(spec)
        if report_path is None:
            failed.append(file_path)
            continue
        materialized.append(report_path)
    return _MaterializedReports(tuple(materialized), tuple(failed))


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

        parsed = parse_numeric_hint_selection(part, valid_hints)
        invalid_hints.extend(parsed.unavailable)
        for hint_num in parsed.numbers:
            if hint_num not in selected_hints:
                selected_hints.append(hint_num)

    return selected_hints, open_in_editor, copy_to_clipboard, invalid_hints


class InputProcessingMixin(HintMixinBase):
    """Mixin providing input processing for hint modes."""

    def on_hint_input_bar_submitted(self, event: HintInputBar.Submitted) -> None:
        """Handle hint input submission."""
        if event.mode == "view":
            ready = getattr(self, "_agent_hint_render_ready", None)
            identity = getattr(self, "_agent_hint_render_identity", None)
            if (
                getattr(self, "current_tab", None) == "agents"
                and ready is not None
                and identity is not None
                and not ready.is_set()
            ):
                session = self._agent_hint_render_session
                self.run_worker(  # type: ignore[attr-defined]
                    self._submit_agent_view_when_ready(
                        event.value,
                        identity,
                        session,
                        ready,
                    ),
                    group="hint-view-readiness",
                    exclusive=True,
                )
                return
            self._submit_ready_view_input(event.value)
        elif event.mode == "hooks":
            self._remove_hint_input_bar()
            self._process_hooks_input(event.value)
        elif event.mode == "failed_hooks":
            self._remove_hint_input_bar()
            self._process_failed_hooks_input(event.value)
        elif event.mode == "mentors":
            self._remove_hint_input_bar()
            self._process_mentors_input(event.value)  # type: ignore[attr-defined]
        elif event.mode == "rewind":
            self._remove_hint_input_bar()
            self._process_rewind_input(event.value)  # type: ignore[attr-defined]
        else:  # accept mode
            self._remove_hint_input_bar()
            self._process_accept_input(event.value)  # type: ignore[attr-defined]

    def on_hint_input_bar_cancelled(self, event: HintInputBar.Cancelled) -> None:
        """Handle hint input cancellation."""
        del event  # unused
        self._remove_hint_input_bar()

    def _remove_hint_input_bar(self, *, refresh: bool = True) -> None:
        """Remove the hint input bar and restore normal display."""
        self._cancel_agent_hint_render_tasks()

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
        if refresh:
            if self.current_tab == "agents":
                self._refresh_agents_display()  # type: ignore[attr-defined]
            else:
                self._refresh_display()  # type: ignore[attr-defined]

    def _submit_ready_view_input(self, user_input: str) -> None:
        """Snapshot and dispatch a view request against published mappings."""
        self._remove_hint_input_bar()
        prepared = self._prepare_view_input(user_input)
        if prepared is not None:
            self.run_worker(  # type: ignore[attr-defined]
                self._finish_view_request(prepared),
                group="hint-view-request",
            )

    async def _submit_agent_view_when_ready(
        self,
        user_input: str,
        agent_identity: tuple[object, ...],
        session: int,
        ready: asyncio.Event,
    ) -> None:
        """Wait for the deferred render, then revalidate its UI context."""
        await ready.wait()

        # Pump-free work interleaves with navigation. Re-capture both pieces of
        # UI state after the await before interpreting the user's hint numbers.
        if (
            self.current_tab != "agents"
            or self._agent_hint_render_session != session
            or self._agent_hint_render_identity != agent_identity
            or not self._hint_mode_active
        ):
            return
        selected = self._get_selected_agent()  # type: ignore[attr-defined]
        if selected is None or tuple(selected.identity) != agent_identity:
            return
        self._submit_ready_view_input(user_input)

    async def _process_view_input(self, user_input: str) -> None:
        """Process view files input."""
        prepared = self._prepare_view_input(user_input)
        if prepared is not None:
            await self._finish_view_request(prepared)

    def _prepare_view_input(self, user_input: str) -> _PreparedViewRequest | None:
        """Validate and snapshot one submitted view request on the UI thread."""
        if not user_input:
            return None

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
            return None

        commit_hint_nums = [hint for hint in selected_hints if hint in commit_views]
        commit_specs = tuple(commit_views[hint] for hint in commit_hint_nums)
        files = self._files_for_view_hints(
            hint for hint in selected_hints if hint in self._hint_mappings
        )

        if not files and not commit_hint_nums:
            self.notify("No valid files selected", severity="warning")  # type: ignore[attr-defined]
            return None

        if open_in_editor and commit_hint_nums:
            files = self._prepend_commit_diff_paths(commit_hint_nums, files)
            if not files:
                self.notify("No selected files could be opened", severity="warning")  # type: ignore[attr-defined]
                return None

        if commit_specs and not open_in_editor and not copy_to_clipboard:
            self._open_commit_view(commit_specs)

        request = _ViewRequest(
            files=tuple(files),
            open_in_editor=open_in_editor,
            copy_to_clipboard=copy_to_clipboard,
            user_input=user_input,
            patch_name=getattr(
                self,
                "_hint_patch_name",
                getattr(self, "_hint_patch_name", ""),
            ),
            commit_specs=commit_specs,
        )
        tool_reports: dict[str, SlowToolCallReportSpec] = getattr(
            self, "_hint_tool_call_reports", {}
        )
        glossary_reports: dict[str, GlossaryReadReportSpec] = getattr(
            self, "_hint_glossary_reports", {}
        )
        memory_reports: dict[str, MemoryReadReportSpec] = getattr(
            self, "_hint_memory_reports", {}
        )
        reports: dict[str, _HintReportSpec] = {
            **tool_reports,
            **glossary_reports,
            **memory_reports,
        }
        selected_reports = tuple(
            (file_path, reports[file_path])
            for file_path in request.files
            if file_path in reports
        )
        return _PreparedViewRequest(request, selected_reports)

    async def _finish_view_request(self, prepared: _PreparedViewRequest) -> None:
        """Materialize a captured request off-thread, then route its UI action."""
        request = prepared.request
        if prepared.report_items:
            outcome = await asyncio.to_thread(
                _write_selected_hint_reports,
                request.files,
                prepared.report_items,
            )
        else:
            outcome = _MaterializedReports(request.files, ())

        # The request remains valid across navigation, but no UI effects should
        # be dispatched after the application has begun shutting down.
        if not bool(getattr(self, "is_running", True)):
            return

        for failed_path in outcome.failed_paths:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to build hint report: {failed_path}",
                severity="error",
            )

        files = list(outcome.files)
        if not files:
            if request.copy_to_clipboard and request.commit_specs:
                self._copy_commit_specs_to_clipboard(request.commit_specs, files)
            elif not request.commit_specs:
                self.notify("No selected files could be opened", severity="warning")  # type: ignore[attr-defined]
            return

        if request.copy_to_clipboard:
            if request.commit_specs:
                self._copy_commit_specs_to_clipboard(request.commit_specs, files)
            else:
                self._copy_files_to_clipboard(files)  # type: ignore[attr-defined]
        elif request.open_in_editor:
            result = ViewFilesResult(
                files=files,
                open_in_editor=True,
                copy_to_clipboard=False,
                user_input=request.user_input,
                patch_name=request.patch_name,
            )
            self._open_files_in_editor(result)  # type: ignore[attr-defined]
        else:
            from ...graphics import is_supported_image_path, is_supported_video_path

            if any(
                is_supported_image_path(f) or is_supported_video_path(f) for f in files
            ):
                self._view_files_with_artifact_file_viewer(files)  # type: ignore[attr-defined]
            elif link_pager_enabled():
                document = await asyncio.to_thread(
                    build_pager_document, files, request.commit_specs
                )
                self._view_files_with_sase_pager(document)  # type: ignore[attr-defined]
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
        self._copy_commit_specs_to_clipboard(
            tuple(commit_views[hint_num] for hint_num in commit_hint_nums),
            files,
        )

    def _copy_commit_specs_to_clipboard(
        self,
        commit_specs: Sequence[CommitViewSpec],
        files: list[str],
    ) -> None:
        shas = [spec.short_sha or spec.sha for spec in commit_specs]
        shas = [sha for sha in shas if sha]
        if not files:
            content = " ".join(shas)
            schedule_copy_delivery(
                self,
                content,
                copied_label=f"{len(shas)} commit SHA(s)",
                task_name="sase-copy-hinted-commits",
            )
            return

        home = str(Path.home())
        shortened_files = [
            f.replace(home, "~", 1) if f.startswith(home) else f for f in files
        ]
        content = " ".join([*shas, *shortened_files])
        schedule_copy_delivery(
            self,
            content,
            copied_label="commit SHA(s) and path(s)",
            task_name="sase-copy-hinted-commit-paths",
        )

    def _process_hooks_input(self, user_input: str) -> None:
        """Process edit hooks input."""
        if not user_input:
            return

        if user_input == ".":
            self._show_hook_history_modal()
            return

        patch = self.patches[self.current_idx]

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
                patch, result, self._hook_hint_to_idx
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
                patch, result, self._hook_hint_to_idx
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
                patch, result, self._hook_hint_to_idx
            )
            if success:
                self._reload_and_reposition()  # type: ignore[attr-defined]

    def _show_hook_history_modal(self) -> None:
        """Show the hook history modal for selecting a previously used hook."""
        from sase.history.hook import add_or_update_hook

        from ....hooks import add_hook_to_patch
        from ...modals import HookHistoryAction, HookHistoryModal, HookHistoryResult
        from ...widgets import PatchDetail, HintInputBar

        def _on_hook_selected(result: HookHistoryResult | None) -> None:
            if result is None:
                return

            if result.action == HookHistoryAction.EDIT_FIRST:
                if self._refocus_existing_hint_bar():
                    return

                # Re-mount hooks input bar pre-filled with the command
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

            # SUBMIT action — add hook to patch
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

        # Get the selected targets (convert 1-based to 0-based)
        selected_targets = [targets[i - 1] for i in parsed.numbers]

        # Add them as hooks
        success = self._add_test_target_hooks(patch, selected_targets)  # type: ignore[attr-defined]
        if success:
            self._reload_and_reposition()  # type: ignore[attr-defined]
