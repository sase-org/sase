"""Immutable data model and off-thread loader for Artifacts Files."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from sase.ace.tui.graphics import artifact_file_view_mode
from sase.ace.tui.graphics._viewer_types import ArtifactViewMode
from sase.ace.tui.util.trace import tui_trace
from sase.core.artifact_file_query_facade import query_artifact_files
from sase.core.artifact_file_types import ArtifactFile


FILES_FIRST_PAGE_LIMIT = 500
_VIEW_MODES: tuple[ArtifactViewMode, ...] = (
    "image",
    "markdown",
    "pdf",
    "text",
    "video",
)


@dataclass(frozen=True, slots=True)
class FilesSnapshot:
    """One project-scoped artifact-file result accepted by the UI thread."""

    rows: tuple[ArtifactFile, ...]
    project: str | None
    complete: bool
    view_modes: Mapping[str, ArtifactViewMode]
    view_mode_counts: Mapping[ArtifactViewMode, int]
    explicit_count: int
    load_error: str | None = None

    def view_mode_for(self, row: ArtifactFile) -> ArtifactViewMode:
        """Return the classifier result computed while loading the snapshot."""

        return self.view_modes.get(row.id, "text")


def _files_snapshot(
    rows: Sequence[ArtifactFile],
    *,
    project: str | None,
    complete: bool = True,
    load_error: str | None = None,
) -> FilesSnapshot:
    """Build a snapshot while classifying each row exactly once."""

    accepted_rows = tuple(rows)
    view_modes: dict[str, ArtifactViewMode] = {}
    counts: Counter[ArtifactViewMode] = Counter()
    for row in accepted_rows:
        mode = artifact_file_view_mode(row.path, kind=row.kind) or "text"
        view_modes[row.id] = mode
        counts[mode] += 1
    return FilesSnapshot(
        rows=accepted_rows,
        project=project,
        complete=complete,
        view_modes=MappingProxyType(view_modes),
        view_mode_counts=MappingProxyType(
            {mode: counts.get(mode, 0) for mode in _VIEW_MODES}
        ),
        explicit_count=sum(row.explicit for row in accepted_rows),
        load_error=load_error,
    )


def load_files_snapshot(
    project: str | None,
    limit: int | None,
) -> FilesSnapshot:
    """Query the Rust-backed index without allowing binding failures to escape."""

    with tui_trace(
        "artifacts.files.load_snapshot",
        project=project,
        limit=limit,
    ) as trace:
        try:
            rows = query_artifact_files(project=project, limit=limit)
        except (ImportError, RuntimeError) as exc:
            trace["error"] = type(exc).__name__
            return _files_snapshot(
                (),
                project=project,
                complete=True,
                load_error=str(exc),
            )
        result = _files_snapshot(
            rows,
            project=project,
            complete=limit is None or len(rows) < limit,
        )
        trace["rows"] = len(result.rows)
        return result


__all__ = [
    "FILES_FIRST_PAGE_LIMIT",
    "FilesSnapshot",
    "load_files_snapshot",
]
