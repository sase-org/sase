"""Pure Rich renderable builders for the Artifacts Files pane."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from rich.text import Text

from sase.ace.tui.graphics._viewer_types import ArtifactViewMode
from sase.ace.tui.keymaps import KeymapRegistry, key_display_name
from sase.core.agent_identity_facade import present_agent_name
from sase.core.time import parse_local
from sase.project_display_names import ProjectRefDisplaySnapshot

from .files_data import FileOrigin, FileVersion, FilesSnapshot, LogicalFile
from .files_filtering import FilesFilterValues
from .shell import ArtifactsPaneState, build_footer_hints, build_state_badge
from .types import ARTIFACTS_ACCENTS


FILE_VIEW_MODE_GLYPHS: dict[ArtifactViewMode, str] = {
    "image": "▨",
    "video": "▶",
    "pdf": "▤",
    "markdown": "▤",
    "text": "•",
}
FILE_VIEW_MODE_COLORS: dict[ArtifactViewMode, str] = {
    "image": "#87D7FF",
    "video": "#D7AF5F",
    "pdf": "#AF87FF",
    "markdown": "#AF87FF",
    "text": "#AFAFAF",
}
_PROJECT_WIDTH = 12
_AGENT_WIDTH = 20
_SIZE_WIDTH = 10
_ORIGIN_BADGES: dict[FileOrigin, tuple[str, str]] = {
    "ref": ("R", "#5FD7AF"),
    "created": ("C", "#FFD700"),
    "capture": ("A", "#FFAF5F"),
}


def build_files_info(
    registry: KeymapRegistry,
    snapshot: FilesSnapshot | None,
    *,
    project_scope: str | None,
    project_display_name: str | None,
    filters: FilesFilterValues | None = None,
    filtered_count: int | None = None,
    accent: str = ARTIFACTS_ACCENTS["files"],
) -> Text:
    """Build project scope, kind-summary chips, and active-filter status."""

    filters = filters or FilesFilterValues()
    scope = project_display_name or project_scope or "All projects"
    text = Text()
    text.append(" File ", style=f"bold #1a1a1a on {accent}")
    text.append("  Project scope  ", style="dim")
    text.append(f" {scope} ", style=f"bold {accent}")
    text.append("  ·  ", style="dim")
    text.append(
        f"{key_display_name(registry.app.pick_artifacts_project)} change",
        style="dim",
    )
    if snapshot is None:
        return text

    documents = snapshot.view_mode_counts.get("pdf", 0) + snapshot.view_mode_counts.get(
        "markdown", 0
    )
    chips: tuple[tuple[ArtifactViewMode, int, str], ...] = (
        (
            "image",
            snapshot.view_mode_counts.get("image", 0),
            "images",
        ),
        ("pdf", documents, "documents"),
        (
            "video",
            snapshot.view_mode_counts.get("video", 0),
            "videos",
        ),
        ("text", snapshot.view_mode_counts.get("text", 0), "files"),
    )
    active_modes = {
        snapshot.view_mode_for(row.latest)
        for row in snapshot.rows
        if row.kind in filters.kinds
    }
    text.append("  │  ", style="dim")
    for index, (mode, count, label) in enumerate(chips):
        if index:
            text.append(" · ", style="dim")
        style = f"bold {FILE_VIEW_MODE_COLORS[mode]}"
        if filters.kinds:
            style = (
                f"{style} reverse"
                if mode in active_modes
                else f"dim {FILE_VIEW_MODE_COLORS[mode]}"
            )
        text.append(f"{FILE_VIEW_MODE_GLYPHS[mode]} {count:,} {label}", style=style)
    text.append(" · ", style="dim")
    origins: tuple[FileOrigin, ...] = ("ref", "created", "capture")
    for index, origin in enumerate(origins):
        if index:
            text.append(" · ", style="dim")
        badge, color = _ORIGIN_BADGES[origin]
        text.append(
            f"{badge} {snapshot.origin_counts.get(origin, 0):,}",
            style=f"bold {color}",
        )
    if not filters.is_empty:
        visible = len(snapshot.rows) if filtered_count is None else filtered_count
        text.append("  │  ", style="dim")
        text.append(
            f"filtered {visible:,}/{len(snapshot.rows):,}",
            style=f"bold {accent}",
        )
    return text


def build_files_status(
    snapshot: FilesSnapshot | None,
    *,
    loading: bool,
    load_error: str | None,
    extending: bool,
) -> Text:
    """Build loading, failure, and loaded-row status text."""

    text = Text()
    error = load_error or (None if snapshot is None else snapshot.load_error)
    if snapshot is None:
        if error:
            text.append(error, style="bold #FF5F5F")
        else:
            text.append(
                "Loading artifact files…" if loading else "Files have not loaded yet",
                style="bold #FFD700" if loading else "dim",
            )
        return text
    if loading or error:
        # A refresh is running or failed, but cached rows remain: preserve
        # them and overlay a stale badge instead of blanking the count.
        text.append_text(
            build_state_badge(
                ArtifactsPaneState.STALE,
                error_message=error if not loading else None,
            )
        )
        text.append("  ·  ", style="dim")
    text.append(f"{len(snapshot.rows):,} artifact files loaded", style="dim")
    if extending:
        text.append("  ·  Loading full index…", style="dim #FFD700")
    return text


def build_files_hints(
    registry: KeymapRegistry,
    *,
    has_agent: bool = True,
    accent: str = ARTIFACTS_ACCENTS["files"],
) -> Text:
    """Build the configured action hints shown below the panels."""

    keymap = registry.app
    parts = (
        (key_display_name(keymap.files_next), "next"),
        (key_display_name(keymap.files_prev), "prev"),
        (key_display_name(keymap.files_view_selected), "view"),
        (key_display_name(keymap.files_filters), "filter"),
        (key_display_name(keymap.files_cycle_kind), "kind"),
        (key_display_name(keymap.files_prev_version), "prev version"),
        (key_display_name(keymap.files_next_version), "next version"),
        (key_display_name(keymap.files_open_agent), "agent"),
        (key_display_name(keymap.files_open_external), "external"),
        (key_display_name(keymap.artifacts_copy_reference), "copy ref"),
        (key_display_name(keymap.files_copy_path), "copy path"),
        (key_display_name(keymap.files_open_viewer), "viewer"),
        (key_display_name(keymap.refresh), "refresh"),
    )
    disabled_labels = frozenset() if has_agent else frozenset({"agent"})
    return build_footer_hints(parts, accent=accent, disabled_labels=disabled_labels)


def file_row_text(
    row: LogicalFile,
    *,
    view_mode: ArtifactViewMode,
    projects: ProjectRefDisplaySnapshot,
) -> Text:
    """Render one aligned, single-line artifact-file row."""

    version = row.latest
    timestamp = _artifact_file_datetime(version)
    time_label = timestamp.strftime("%H:%M") if timestamp is not None else "--:--"
    project_refs = row.projects
    project = (
        projects.display_snapshot.label_for(project_refs[0]) if project_refs else "-"
    )
    agent = row.agents[0] if row.agents else None
    presented = present_agent_name(agent) if agent else (version.workflow or "file")
    size = humanize_file_size(version.size_bytes)
    color = FILE_VIEW_MODE_COLORS[view_mode]
    origin_badge, origin_color = _origin_badge(row)
    version_label = f" {len(row.versions)}v" if len(row.versions) > 1 else ""

    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(FILE_VIEW_MODE_GLYPHS[view_mode], style=f"bold {color}")
    text.append(f" {time_label}  ", style="dim")
    text.append(f"[{project}]".ljust(_PROJECT_WIDTH), style="bold #87D7FF")
    text.append(f"{presented}".ljust(_AGENT_WIDTH), style="bold white")
    text.append(f"{origin_badge} ", style=f"bold {origin_color}")
    text.append(row.label, style=color)
    if version_label:
        text.append(version_label, style="dim")
    text.append(f"  {size:>{_SIZE_WIDTH}}", style="dim")
    return text


def _artifact_file_datetime(
    row: FileVersion,
) -> datetime | None:
    """Parse an index timestamp in the configured display timezone."""

    return parse_local(row.created_at)


def _origin_badge(row: LogicalFile) -> tuple[str, str]:
    if len(row.origins) > 1:
        return "+", "#FFFFFF"
    origin = next(iter(row.origins), "capture")
    origin_key = origin if origin in _ORIGIN_BADGES else "capture"
    return _ORIGIN_BADGES[cast(FileOrigin, origin_key)]


def humanize_file_size(size_bytes: int | None) -> str:
    """Format an optional byte count using the CLI's binary-unit vocabulary."""

    if size_bytes is None:
        return "-"
    value = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size_bytes} B"


__all__ = [
    "FILE_VIEW_MODE_COLORS",
    "FILE_VIEW_MODE_GLYPHS",
    "build_files_hints",
    "build_files_info",
    "build_files_status",
    "file_row_text",
    "humanize_file_size",
]
