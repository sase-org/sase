"""Artifact-reference candidate helpers for prompt completion."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from sase.ace.tui.widgets._file_completion_history import (
    FileCompletionHistoryMixin,
)
from sase.ace.tui.widgets.artifact_ref_completion import (
    ArtifactRefBugCandidate,
    ArtifactRefCommitCandidate,
    ArtifactRefCompletionCatalog,
    ArtifactRefCompletionResult,
    ArtifactRefPayloadCompletionMetadata,
    build_artifact_ref_completion_result,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate

if TYPE_CHECKING:
    from sase.artifact_refs import ArtifactRefContext


class FileCompletionArtifactCandidatesMixin(FileCompletionHistoryMixin):
    """Mixin providing artifact-reference candidates from warm snapshots."""

    if TYPE_CHECKING:
        _artifact_ref_files_revealed: bool
        _artifact_ref_bug_projection: (
            tuple[object, str | None, tuple[ArtifactRefBugCandidate, ...]] | None
        )

        def _get_warm_artifact_ref_context(self) -> ArtifactRefContext | None: ...
        def _xprompt_arg_assist_project_from_text(self) -> str | None: ...
        def _artifact_ref_sync_row(
            self,
            project: str | None,
            kind: str,
        ) -> CompletionCandidate | None: ...
        def _artifact_ref_sync_new_payloads(
            self,
            project: str | None,
            kind: str,
        ) -> frozenset[str]: ...

    def _artifact_ref_completion_result(
        self,
    ) -> ArtifactRefCompletionResult | None:
        """Build artifact candidates solely from warm immutable snapshots."""
        context = self._get_artifact_ref_completion_context()
        if context is None:
            return None
        catalog = self._get_warm_artifact_ref_completion_catalog()
        if catalog is None:
            if context.stage == "payload":
                return None
            catalog = ArtifactRefCompletionCatalog(
                project=None,
                kinds=tuple(self._get_warm_artifact_ref_known_kinds() or ()),
            )
        path_snapshot = None
        if context.stage == "kind" and context.path_directory is not None:
            directory_key = self._prompt_path_directory_key(context.path_directory)
            path_snapshot = self._get_warm_prompt_path_snapshot(directory_key)
        commit_rows: tuple[ArtifactRefCommitCandidate, ...] = ()
        commits_loading = False
        commits_truncated_payloads = 0
        if context.stage == "payload" and (context.kind or "").casefold() == "commit":
            project = self._xprompt_arg_assist_project_from_text()
            commit_snapshot = self._prompt_commit_snapshots.get(project)
            artifact_context = self._get_warm_artifact_ref_context()
            if artifact_context is not None:
                self._schedule_prompt_commit_inventory_load(
                    project,
                    artifact_context,
                    commit_snapshot,
                )
            commits_loading = project in self._prompt_commit_inflight
            if commit_snapshot is not None:
                commit_rows = commit_snapshot.rows
                commits_truncated_payloads = commit_snapshot.truncated_payloads
        result = build_artifact_ref_completion_result(
            context,
            catalog,
            include_files=self._artifact_ref_files_revealed,
            commits=commit_rows,
            commits_loading=commits_loading,
            commits_truncated_payloads=commits_truncated_payloads,
            bugs=self._snapshot_artifact_ref_bug_candidates(),
            paths=() if path_snapshot is None else path_snapshot.rows,
            paths_loading=context.stage == "kind" and path_snapshot is None,
        )
        if context.stage == "payload" and context.kind:
            project = self._xprompt_arg_assist_project_from_text()
            new_payloads = self._artifact_ref_sync_new_payloads(project, context.kind)
            if new_payloads:
                for candidate in result.candidates:
                    metadata = candidate.metadata
                    if (
                        isinstance(metadata, ArtifactRefPayloadCompletionMetadata)
                        and metadata.payload in new_payloads
                    ):
                        candidate.metadata = replace(metadata, is_new=True)
            sync_row = self._artifact_ref_sync_row(project, context.kind)
            if sync_row is not None:
                result.candidates.insert(0, sync_row)
        return result

    def _snapshot_artifact_ref_bug_candidates(
        self,
    ) -> tuple[ArtifactRefBugCandidate, ...]:
        """Project the mounted Beads pane's external-issue tracker caches."""
        try:
            pane = self.app.query_one("#artifacts-beads-pane")
        except Exception:
            return ()
        snapshot = getattr(pane, "snapshot", None)
        if snapshot is None:
            return ()
        target_project = self._xprompt_arg_assist_project_from_text()
        cached = getattr(self, "_artifact_ref_bug_projection", None)
        if cached is not None and cached[0] is snapshot and cached[1] == target_project:
            return cached[2]
        rows: list[ArtifactRefBugCandidate] = []
        for cache in getattr(snapshot, "external_projects", {}).values():
            project = str(
                getattr(cache, "display_name", "")
                or getattr(cache, "project", "")
                or ""
            )
            if not project:
                continue
            if target_project is not None:
                accepted = {
                    project.casefold(),
                    str(getattr(cache, "project", "") or "").casefold(),
                }
                if target_project.casefold() not in accepted:
                    continue
            for issue in getattr(cache, "issues", ()):
                number = getattr(issue, "number", None)
                if not isinstance(number, int):
                    continue
                rows.append(
                    ArtifactRefBugCandidate(
                        project=project,
                        number=number,
                        title=str(getattr(issue, "title", "") or ""),
                        updated_at=str(
                            getattr(issue, "updated_at", "")
                            or getattr(issue, "created_at", "")
                            or ""
                        ),
                    )
                )
        projected = tuple(rows)
        self._artifact_ref_bug_projection = (
            snapshot,
            target_project,
            projected,
        )
        return projected
