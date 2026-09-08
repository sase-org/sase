"""View-file hint input processing for the ace TUI app."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterable
from dataclasses import dataclass, field

from sase.memory.legacy_glossary_read_report import (
    GlossaryReadReportSpec,
    write_glossary_read_report,
)
from sase.memory.memory_read_report import (
    MemoryReadReportSpec,
    write_memory_read_report,
)
from sase.pager.link_context import LinkResolutionContext

from ....hint_types import ViewFilesResult
from ....hints import parse_numeric_hint_selection, parse_view_input
from ...artifact_reads import ArtifactReadRefSpec
from ...tools.report import SlowToolCallReportSpec, write_tool_call_report
from ...widgets.prompt_panel._agent_display_state import CommitViewSpec
from ._artifact_ref_repair import repair_artifact_read_path
from ._commit_processing import CommitHintProcessingMixin
from ._files import build_pager_document
from ._link_context_capture import CapturedLinkContext, link_context_from_capture

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
    captured_link_context: CapturedLinkContext


@dataclass(frozen=True)
class _MaterializedReports:
    files: tuple[str, ...]
    failed_paths: tuple[str, ...]
    missing_paths: tuple[str, ...] = ()
    link_context: LinkResolutionContext = field(default_factory=LinkResolutionContext)


@dataclass(frozen=True)
class _PreparedViewRequest:
    request: _ViewRequest
    report_items: tuple[tuple[str, _HintReportSpec], ...]
    artifact_read_ref_items: tuple[tuple[str, ArtifactReadRefSpec], ...] = ()


def _materialize_selected_view_files(
    files: tuple[str, ...],
    report_items: tuple[tuple[str, _HintReportSpec], ...],
    artifact_read_ref_items: tuple[tuple[str, ArtifactReadRefSpec], ...],
    captured_link_context: CapturedLinkContext,
) -> _MaterializedReports:
    """Materialize reports, repair artifact-read paths, and drop stale files."""
    reports = dict(report_items)
    artifact_read_refs = dict(artifact_read_ref_items)
    materialized: list[str] = []
    failed: list[str] = []
    missing: list[str] = []
    for file_path in files:
        spec = reports.get(file_path)
        if spec is None:
            resolved_path = file_path
        else:
            if isinstance(spec, MemoryReadReportSpec):
                report_path = write_memory_read_report(spec)
            elif isinstance(spec, GlossaryReadReportSpec):
                report_path = write_glossary_read_report(spec)
            else:
                report_path = write_tool_call_report(spec)
            if report_path is None:
                failed.append(file_path)
                continue
            resolved_path = report_path
        if os.path.exists(resolved_path):
            materialized.append(resolved_path)
            continue
        ref_spec = artifact_read_refs.get(file_path)
        if ref_spec is not None:
            repaired_path = repair_artifact_read_path(ref_spec)
            if repaired_path is not None and os.path.exists(repaired_path):
                materialized.append(repaired_path)
                continue
        missing.append(resolved_path)
    return _MaterializedReports(
        tuple(materialized),
        tuple(failed),
        tuple(missing),
        link_context_from_capture(captured_link_context),
    )


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


class ViewInputProcessingMixin(CommitHintProcessingMixin):
    """Mixin providing view-file hint input processing."""

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
            captured_link_context=self._capture_view_link_context(),
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
        artifact_read_refs: dict[str, ArtifactReadRefSpec] = getattr(
            self, "_hint_artifact_read_refs", {}
        )
        selected_ref_items = tuple(
            (file_path, artifact_read_refs[file_path])
            for file_path in request.files
            if file_path in artifact_read_refs
        )
        return _PreparedViewRequest(request, selected_reports, selected_ref_items)

    async def _finish_view_request(self, prepared: _PreparedViewRequest) -> None:
        """Materialize a captured request off-thread, then route its UI action."""
        request = prepared.request
        outcome = await asyncio.to_thread(
            _materialize_selected_view_files,
            request.files,
            prepared.report_items,
            prepared.artifact_read_ref_items,
            request.captured_link_context,
        )

        # The request remains valid across navigation, but no UI effects should
        # be dispatched after the application has begun shutting down.
        if not bool(getattr(self, "is_running", True)):
            return

        for failed_path in outcome.failed_paths:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to build hint report: {failed_path}",
                severity="error",
            )
        for missing_path in outcome.missing_paths:
            self.notify(  # type: ignore[attr-defined]
                f"File no longer exists: {missing_path}",
                severity="warning",
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
            else:
                try:
                    document = await asyncio.to_thread(
                        build_pager_document,
                        files,
                        request.commit_specs,
                        link_context=outcome.link_context,
                    )
                except OSError as exc:
                    self.notify(  # type: ignore[attr-defined]
                        f"Could not open pager: {exc}",
                        severity="error",
                    )
                    return
                if not bool(getattr(self, "is_running", True)):
                    return
                self._view_files_with_pager_screen(document)  # type: ignore[attr-defined]

    def _capture_view_link_context(self) -> CapturedLinkContext:
        """Snapshot stable agent/patch inputs; no directory or marker I/O."""
        if getattr(self, "current_tab", None) == "agents":
            agent = self._get_selected_agent()  # type: ignore[attr-defined]
            if agent is None:
                return CapturedLinkContext(source="default")
            workspace_dir = getattr(agent, "workspace_dir", None)
            return CapturedLinkContext(
                source="agent",
                workspace_num=getattr(agent, "effective_workspace_num", None),
                project_file=getattr(agent, "project_file", None),
                workspace_dir=(None if workspace_dir is None else str(workspace_dir)),
            )

        patches = getattr(
            self,
            "patches",
            getattr(self, "changespecs", []),
        )
        if not patches:
            return CapturedLinkContext(source="default")
        try:
            patch = patches[getattr(self, "current_idx", 0)]
        except (IndexError, TypeError):
            return CapturedLinkContext(source="default")
        basename = getattr(patch, "project_basename", None)
        return CapturedLinkContext(
            source="patch",
            project_basename=None if basename is None else str(basename),
        )

    def _files_for_view_hints(self, hint_nums: Iterable[int]) -> list[str]:
        hint_input = " ".join(str(hint_num) for hint_num in hint_nums)
        files, _, _, _ = parse_view_input(hint_input, self._hint_mappings)
        return files
