"""Off-thread liveness, preview loading, and detail rendering for Files."""

from __future__ import annotations

from dataclasses import dataclass
from os import stat_result
from pathlib import Path

from rich.text import Text

from sase.ace.tui.graphics._viewer_types import ArtifactViewMode
from sase.core.agent_identity_facade import present_agent_name
from sase.core.artifact_file_types import ArtifactFile
from sase.core.time import format_local
from sase.project_display_names import ProjectRefDisplaySnapshot

from .files_rendering import humanize_file_size
from .types import ARTIFACTS_ACCENTS

_PREVIEW_LINES = 40
_PREVIEW_CHARS = 32 * 1024
_TEXT_VIEW_MODES = frozenset({"markdown", "text"})

FileDetailCacheKey = tuple[str, int | None, int | None]


@dataclass(frozen=True, slots=True)
class FileDetailData:
    """Filesystem facts loaded without blocking Textual's message pump."""

    file_id: str
    resolved_stored_path: str | None
    stored_live: bool
    stored_mtime_ns: int | None
    stored_size: int | None
    resolved_source_path: str | None
    source_live: bool | None
    preview: str
    preview_truncated: bool

    @property
    def cache_key(self) -> FileDetailCacheKey:
        """Key liveness and preview data to the indexed file and stored stat."""

        return (self.file_id, self.stored_mtime_ns, self.stored_size)


def load_file_detail(
    row: ArtifactFile,
    *,
    view_mode: ArtifactViewMode,
) -> FileDetailData:
    """Resolve paths, stat them, and read a bounded text preview off-thread."""

    stored_path = _materialized_path(row)
    stored_stat = None if stored_path is None else _stat(stored_path)
    source_path = (
        None
        if not row.source_path
        else Path(row.source_path).expanduser().resolve(strict=False)
    )
    source_stat = None if source_path is None else _stat(source_path)
    preview = ""
    truncated = False
    if view_mode in _TEXT_VIEW_MODES and stored_stat is not None:
        assert stored_path is not None
        preview, truncated = _read_preview(stored_path)
    return FileDetailData(
        file_id=row.id,
        resolved_stored_path=None if stored_path is None else str(stored_path),
        stored_live=stored_stat is not None,
        stored_mtime_ns=(None if stored_stat is None else stored_stat.st_mtime_ns),
        stored_size=None if stored_stat is None else stored_stat.st_size,
        resolved_source_path=None if source_path is None else str(source_path),
        source_live=None if source_path is None else source_stat is not None,
        preview=preview,
        preview_truncated=truncated,
    )


def build_file_detail(
    row: ArtifactFile | None,
    detail: FileDetailData | None,
    *,
    view_mode: ArtifactViewMode | None,
    projects: ProjectRefDisplaySnapshot,
    loading: bool = False,
) -> Text:
    """Render reference, metadata, origin, path, and optional preview sections."""

    if row is None:
        return Text("Select an artifact file to inspect it.", style="dim")

    mode = view_mode or "text"
    stored_path = detail.resolved_stored_path if detail is not None else row.path
    reference_target = stored_path or (
        f"{row.vcs_repo}@{row.vcs_sha}:{row.vcs_relpath}" if row.is_vcs_backed else "-"
    )
    text = Text()
    _heading(text, "REFERENCE")
    text.append(f"file:{row.id}", style="bold")
    text.append(f"  →  {reference_target}\n", style="dim")

    _heading(text, "FILE")
    _field(text, "Label", row.label)
    _field(text, "Kind", f"{row.kind} · {mode}")
    _field(text, "MIME type", row.mime_type)
    _field(text, "Size", humanize_file_size(row.size_bytes))
    sha = f"{row.sha256[:12]}…" if row.sha256 else None
    _field(text, "SHA-256", sha, value_style="dim")
    _field(text, "Created", _minute_precision(row.created_at))
    if any(value is None for value in (row.mime_type, row.size_bytes, row.sha256)):
        text.append(
            "Run `sase artifact doctor --fix` to backfill missing metadata.\n",
            style="dim",
        )

    _heading(text, "ORIGIN")
    project = projects.display_snapshot.label_for(row.project) if row.project else "-"
    agent = present_agent_name(row.agent_name) if row.agent_name else "-"
    workflow = row.workflow or "-"
    if row.explicit:
        text.append(
            f"Registered explicitly by {agent} during {workflow} in {project}.\n"
        )
    else:
        text.append(f"Captured automatically from {agent}'s run.\n")
    _field(text, "Project", project)
    _field(text, "Workflow", workflow)
    _field(text, "Agent", agent)
    _field(text, "Artifacts dir", row.agent_artifacts_dir or "-")

    if row.is_vcs_backed:
        _heading(text, "PROVENANCE")
        _field(text, "Repo", row.vcs_repo)
        _field(text, "Commit", row.vcs_sha, value_style="dim")
        _field(text, "Path", row.vcs_relpath, value_style="dim")
        _field(
            text,
            "Cached",
            (
                "checking…"
                if detail is None and loading
                else "yes"
                if detail is not None and detail.stored_live
                else "no"
            ),
        )
        _heading(text, "PATHS")
    else:
        _heading(text, "PATHS")
        _path_field(
            text,
            "Stored",
            stored_path,
            live=None if detail is None else detail.stored_live,
            loading=loading,
        )
    source_path = detail.resolved_source_path if detail is not None else row.source_path
    _path_field(
        text,
        "Source",
        source_path,
        live=None if detail is None else detail.source_live,
        loading=loading,
    )

    if mode in _TEXT_VIEW_MODES:
        _heading(text, "PREVIEW")
        if detail is None:
            text.append(
                "Loading file preview…\n" if loading else "Preview unavailable.\n",
                style="dim",
            )
        else:
            text.append(detail.preview or "_Empty file._", style="dim")
            text.append("\n")
            text.append(
                "… press enter for the full reader\n",
                style="dim italic",
            )
    return text


def _materialized_path(row: ArtifactFile) -> Path | None:
    if row.path:
        return Path(row.path).expanduser().resolve(strict=False)
    if not row.is_vcs_backed:
        return None
    from sase.artifact_ref_context import launch_artifact_ref_context
    from sase.core.artifact_file_vcs import materialize_artifact_file

    context = launch_artifact_ref_context(is_home_mode=False)
    return materialize_artifact_file(row, repositories=context.repositories)


def _stat(path: Path) -> stat_result | None:
    try:
        return path.stat()
    except OSError:
        return None


def _read_preview(path: Path) -> tuple[str, bool]:
    lines: list[str] = []
    characters = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index >= _PREVIEW_LINES or characters + len(line) > _PREVIEW_CHARS:
                    return "".join(lines).rstrip(), True
                lines.append(line)
                characters += len(line)
    except OSError:
        return "", False
    return "".join(lines).rstrip(), False


def _minute_precision(created_at: str | None) -> str:
    return format_local(created_at, "%Y-%m-%d %H:%M", default="-")


def _heading(text: Text, label: str) -> None:
    if text:
        text.append("\n")
    text.append(
        f"{label}\n",
        style=f"bold underline {ARTIFACTS_ACCENTS['files']}",
    )


def _field(
    text: Text,
    label: str,
    value: object | None,
    *,
    value_style: str | None = None,
) -> None:
    text.append(f"{label}: ", style="bold #87AFFF")
    text.append(f"{value if value not in (None, '') else '-'}\n", style=value_style)


def _path_field(
    text: Text,
    label: str,
    path: str | None,
    *,
    live: bool | None,
    loading: bool,
) -> None:
    text.append(f"{label}: ", style="bold #87AFFF")
    text.append(path or "-", style="dim")
    if path is not None:
        if live is True:
            text.append("  live", style="bold #5FD75F")
        elif live is False:
            text.append("  missing", style="bold #FF5F5F")
        else:
            text.append(
                "  checking…" if loading else "  unknown",
                style="dim",
            )
    text.append("\n")


__all__ = [
    "FileDetailCacheKey",
    "FileDetailData",
    "build_file_detail",
    "load_file_detail",
]
