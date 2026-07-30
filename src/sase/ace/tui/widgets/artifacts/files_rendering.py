"""Pure Rich renderable builders for the Artifacts Files pane."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text

from sase.ace.tui.graphics._viewer_types import ArtifactViewMode
from sase.ace.tui.keymaps import KeymapRegistry, key_display_name
from sase.core.agent_identity_facade import present_agent_name
from sase.core.artifact_file_types import ArtifactFile
from sase.project_display_names import ProjectRefDisplaySnapshot

from .files_data import FilesSnapshot
from .files_filtering import FilesFilterValues, to_query_tokens
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


def build_files_info(
    registry: KeymapRegistry,
    snapshot: FilesSnapshot | None,
    *,
    project_scope: str | None,
    project_display_name: str | None,
    filters: FilesFilterValues | None = None,
    filtered_count: int | None = None,
) -> Text:
    """Build project scope, kind-summary chips, and active-filter status."""

    filters = filters or FilesFilterValues()
    accent = ARTIFACTS_ACCENTS["files"]
    scope = project_display_name or project_scope or "All projects"
    text = Text()
    text.append(" Files ", style=f"bold #1a1a1a on {accent}")
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
        snapshot.view_mode_for(row)
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
    text.append(
        f"◆ {snapshot.explicit_count:,} explicit",
        style=f"bold {accent}",
    )
    if not filters.is_empty:
        visible = len(snapshot.rows) if filtered_count is None else filtered_count
        text.append("  │  ", style="dim")
        text.append(
            f"filtered {visible:,}/{len(snapshot.rows):,}",
            style=f"bold {accent}",
        )
        tokens = to_query_tokens(filters)
        if tokens:
            text.append("  ·  ", style="dim")
            text.append(" ".join(tokens), style=accent)
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
    if error:
        text.append(error, style="bold #FF5F5F")
        return text
    if snapshot is None:
        text.append(
            "Loading artifact files…" if loading else "Files have not loaded yet",
            style="bold #FFD700" if loading else "dim",
        )
        return text
    text.append(f"{len(snapshot.rows):,} artifact files loaded", style="dim")
    if extending:
        text.append("  ·  Loading full index…", style="dim #FFD700")
    return text


def build_files_hints(
    registry: KeymapRegistry,
    *,
    has_agent: bool = True,
) -> Text:
    """Build the configured action hints shown below the panels."""

    keymap = registry.app
    parts = (
        (key_display_name(keymap.files_next), "next"),
        (key_display_name(keymap.files_prev), "prev"),
        (key_display_name(keymap.files_view_selected), "view"),
        (key_display_name(keymap.files_filters), "filter"),
        (key_display_name(keymap.files_cycle_kind), "kind"),
        (key_display_name(keymap.files_open_agent), "agent"),
        (key_display_name(keymap.files_open_external), "external"),
        (key_display_name(keymap.files_copy_reference), "copy ref"),
        (key_display_name(keymap.files_copy_path), "copy path"),
        (key_display_name(keymap.files_open_viewer), "viewer"),
        (key_display_name(keymap.files_refresh), "refresh"),
    )
    text = Text(justify="center")
    for index, (key, label) in enumerate(parts):
        if index:
            text.append("  ·  ", style="dim")
        disabled = label == "agent" and not has_agent
        text.append(
            key,
            style=("dim" if disabled else f"bold {ARTIFACTS_ACCENTS['files']}"),
        )
        text.append(f" {label}", style="dim")
    return text


def file_group_label(row: ArtifactFile, *, today: datetime) -> str:
    """Return Today, Yesterday, or an ISO date for one artifact row."""

    timestamp = _artifact_file_datetime(row, local_timezone=today)
    if timestamp is None:
        return "Unknown"
    day_delta = (today.date() - timestamp.date()).days
    if day_delta == 0:
        return "Today"
    if day_delta == 1:
        return "Yesterday"
    return timestamp.date().isoformat()


def file_group_header(label: str) -> Text:
    """Render one disabled date separator."""

    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(f"── {label} ", style="dim")
    text.append("─" * 20, style="dim #5F5F87")
    return text


def file_row_text(
    row: ArtifactFile,
    *,
    view_mode: ArtifactViewMode,
    projects: ProjectRefDisplaySnapshot,
    now: datetime | None = None,
) -> Text:
    """Render one aligned, single-line artifact-file row."""

    timestamp = _artifact_file_datetime(row, local_timezone=now)
    time_label = timestamp.strftime("%H:%M") if timestamp is not None else "--:--"
    project = projects.display_snapshot.label_for(row.project) if row.project else "-"
    agent = row.agent_name
    presented = present_agent_name(agent) if agent else (row.workflow or "file")
    size = humanize_file_size(row.size_bytes)
    color = FILE_VIEW_MODE_COLORS[view_mode]

    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(FILE_VIEW_MODE_GLYPHS[view_mode], style=f"bold {color}")
    text.append(f" {time_label}  ", style="dim")
    text.append(f"[{project}]".ljust(_PROJECT_WIDTH), style="bold #87D7FF")
    text.append(f"{presented}".ljust(_AGENT_WIDTH), style="bold white")
    if row.explicit:
        text.append("◆ ", style=f"bold {ARTIFACTS_ACCENTS['files']}")
    else:
        text.append("  ")
    text.append(row.label, style=color)
    text.append(f"  {size:>{_SIZE_WIDTH}}", style="dim")
    return text


def _artifact_file_datetime(
    row: ArtifactFile,
    *,
    local_timezone: datetime | None,
) -> datetime | None:
    """Parse an index timestamp and project aware values into local time."""

    if not row.created_at:
        return None
    try:
        timestamp = datetime.fromisoformat(row.created_at)
    except ValueError:
        return None
    if (
        timestamp.tzinfo is not None
        and local_timezone is not None
        and local_timezone.tzinfo is not None
    ):
        timestamp = timestamp.astimezone(local_timezone.tzinfo)
    return timestamp


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
    "file_group_header",
    "file_group_label",
    "file_row_text",
    "humanize_file_size",
]
