"""Artifact-reference rows for the prompt input completion panel."""

from __future__ import annotations

import os

from rich.text import Text

from sase.ace.tui.widgets._completion_match_highlight import (
    DIR_STYLE,
    FILE_BASENAME_STYLE,
    append_highlighted,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_rows_utils import (
    truncate_cell,
)
from sase.ace.tui.widgets.artifact_ref_completion import (
    ArtifactRefKindCompletionMetadata,
    ArtifactRefPayloadCompletionMetadata,
    ArtifactRefSyncCompletionMetadata,
    AtReferenceFileCompletionMetadata,
    AtReferenceLoadingCompletionMetadata,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate

_ARTIFACT_SOURCE_BADGES = {
    "document": ("[D] ", "bold #87D7FF"),
    "file": ("[F] ", "bold #D7AF5F"),
    "commit": ("[G] ", "bold #AF87FF"),
    "bug": ("[B] ", "bold #FF875F"),
    "bead": ("[◆] ", "bold #FFD700"),
    "agent": ("[A] ", "bold #FF5FD7"),
}

# Stand-in "accent" color: this rendering module has no access to the live
# app theme (every other color here is a hardcoded Rich style too).
_SYNC_ACCENT_STYLE = "bold #5FD7AF"
_SYNC_SUCCESS_STYLE = "bold #5FFF5F"
_SYNC_ERROR_STYLE = "bold #FF5F5F"
_NEW_PAYLOAD_BADGE = ("[✦] ", _SYNC_ACCENT_STYLE)
_SYNC_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def append_artifact_ref_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
    kind_width: int = 0,
    inner_width: int = 0,
) -> None:
    """Append one kind, local-file, or provider-specific payload row."""
    metadata = candidate.metadata
    if isinstance(metadata, AtReferenceLoadingCompletionMetadata):
        content.append(candidate.display, style="dim")
        return
    if isinstance(metadata, ArtifactRefSyncCompletionMetadata):
        glyph, glyph_style = _sync_glyph(metadata)
        content.append(f"{glyph}  ", style=glyph_style)
        content.append(metadata.label, style="dim")
        if metadata.detail:
            content.append(f" · {metadata.detail}", style="dim")
        return
    if isinstance(metadata, ArtifactRefKindCompletionMetadata):
        content.append("@  ", style="bold #5FD7AF")
        append_highlighted(
            content,
            metadata.kind,
            metadata.label_match,
            base_style="bold green" if is_selected else "green",
        )
        content.append(" " * max(0, kind_width - len(metadata.kind)))
        content.append(f"  {metadata.source_label}", style="dim")
        return
    if isinstance(metadata, AtReferenceFileCompletionMetadata):
        if metadata.is_dir:
            content.append("\U0001f4c1 ")
            append_highlighted(
                content,
                candidate.display,
                metadata.label_match,
                base_style=DIR_STYLE,
                segment_split=_basename_start(candidate.display),
            )
        else:
            content.append("\U0001f4c4 ")
            append_highlighted(
                content,
                candidate.display,
                metadata.label_match,
                base_style=FILE_BASENAME_STYLE,
                segment_split=_basename_start(candidate.display),
            )
        return
    if not isinstance(metadata, ArtifactRefPayloadCompletionMetadata):
        content.append(candidate.display, style="bold" if is_selected else "")
        return

    badge, badge_style = (
        _NEW_PAYLOAD_BADGE
        if metadata.is_new
        else _ARTIFACT_SOURCE_BADGES[metadata.source]
    )
    content.append(badge, style=badge_style)
    append_highlighted(
        content,
        candidate.display,
        metadata.label_match,
        base_style=FILE_BASENAME_STYLE,
        segment_split=(
            candidate.display.find("@") + 1
            if metadata.source == "commit" and "@" in candidate.display
            else _basename_start(candidate.display)
        ),
    )
    details = [
        (value, metadata.title_match if index == 0 else ())
        for index, value in enumerate((metadata.label, metadata.detail, metadata.age))
        if value and value != candidate.display
    ]
    if details:
        available = None
        if inner_width > 0:
            row_width = 4 + Text(candidate.display).cell_len
            available = max(0, inner_width - 2 - row_width)
        _append_payload_tail(content, details, available)


def _sync_glyph(metadata: ArtifactRefSyncCompletionMetadata) -> tuple[str, str]:
    """Return the status glyph and style for one ``@<kind>::`` sync row."""
    if metadata.phase == "running":
        frame = _SYNC_SPINNER_FRAMES[metadata.frame % len(_SYNC_SPINNER_FRAMES)]
        return frame, _SYNC_ACCENT_STYLE
    if metadata.phase == "settled_error":
        return "✗", _SYNC_ERROR_STYLE
    return "✓", _SYNC_SUCCESS_STYLE


def _basename_start(text: str) -> int:
    """Return the basename character offset, ignoring a trailing slash."""
    core = text[:-1] if text.endswith("/") else text
    return core.rfind("/") + 1


def _append_payload_tail(
    content: Text,
    details: list[tuple[str, tuple[tuple[int, int], ...]]],
    available: int | None,
) -> None:
    """Append a dim, match-aware payload tail within the remaining row width."""
    if available is not None and available <= 3:
        return
    tail = Text("  ", style="dim")
    for index, (value, runs) in enumerate(details):
        if index:
            tail.append("  ·  ", style="dim")
        append_highlighted(tail, value, runs, base_style="dim")

    if available is None or tail.cell_len <= available:
        content.append_text(tail)
        return

    truncated = truncate_cell(tail.plain, available)
    if available <= 3:
        content.append(truncated, style="dim")
        return
    prefix_length = max(0, len(truncated) - 3)
    content.append_text(tail[:prefix_length])
    content.append("...", style="dim")


def artifact_ref_kind_label_width(rows: list[CompletionCandidate]) -> int:
    """Return the aligned kind-name width for visible ``@`` artifact rows."""
    return max(
        (
            len(metadata.kind)
            for candidate in rows
            if isinstance(
                (metadata := candidate.metadata),
                ArtifactRefKindCompletionMetadata,
            )
        ),
        default=0,
    )


def at_reference_directory_display(directory: str) -> str:
    """Shorten an already-resolved menu directory without filesystem I/O."""
    if not directory:
        return "."
    if directory == "~" or directory.startswith("~/"):
        return directory
    normalized = os.path.normpath(directory)
    home = os.path.normpath(os.path.expanduser("~"))
    if normalized == home:
        return "~"
    if normalized.startswith(home + os.sep):
        return "~" + normalized[len(home) :]
    return normalized


def append_at_reference_group_rule(
    content: Text,
    directory: str,
    inner_width: int,
) -> None:
    """Append the rendering-only rule that introduces local file rows."""
    label = f"── files · {at_reference_directory_display(directory)}"
    content.append(label, style="dim")
    remaining = max(0, inner_width - Text(label).cell_len)
    if remaining:
        content.append("─" * remaining, style="dim")
