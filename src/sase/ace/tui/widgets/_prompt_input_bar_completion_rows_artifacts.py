"""Artifact-reference rows for the prompt input completion panel."""

from __future__ import annotations

import os

from rich.text import Text

from sase.ace.tui.widgets.artifact_ref_completion import (
    ArtifactRefKindCompletionMetadata,
    ArtifactRefPayloadCompletionMetadata,
    AtReferenceFileCompletionMetadata,
    AtReferenceLoadingCompletionMetadata,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate

_ARTIFACT_SOURCE_BADGES = {
    "document": ("[D] ", "bold #87D7FF"),
    "file": ("[F] ", "bold #D7AF5F"),
    "chat": ("[C] ", "bold #5FD7AF"),
    "commit": ("[G] ", "bold #AF87FF"),
    "bug": ("[B] ", "bold #FF875F"),
}


def append_artifact_ref_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
    kind_width: int = 0,
) -> None:
    """Append one kind, local-file, or provider-specific payload row."""
    metadata = candidate.metadata
    if isinstance(metadata, AtReferenceLoadingCompletionMetadata):
        content.append(candidate.display, style="dim")
        return
    if isinstance(metadata, ArtifactRefKindCompletionMetadata):
        content.append("@  ", style="bold #5FD7AF")
        content.append(
            metadata.kind.ljust(max(kind_width, len(metadata.kind))),
            style="bold green" if is_selected else "green",
        )
        content.append(f"  {metadata.source_label}", style="dim")
        return
    if isinstance(metadata, AtReferenceFileCompletionMetadata):
        if metadata.is_dir:
            content.append("\U0001f4c1 ")
            content.append(
                candidate.display,
                style="bold cyan" if is_selected else "cyan",
            )
        else:
            content.append("\U0001f4c4 ")
            content.append(candidate.display, style="bold" if is_selected else "")
        return
    if not isinstance(metadata, ArtifactRefPayloadCompletionMetadata):
        content.append(candidate.display, style="bold" if is_selected else "")
        return

    badge, badge_style = _ARTIFACT_SOURCE_BADGES[metadata.source]
    content.append(badge, style=badge_style)
    content.append(
        candidate.display,
        style="bold" if is_selected else "",
    )
    details = [
        value
        for value in (metadata.label, metadata.detail, metadata.age)
        if value and value != candidate.display
    ]
    if details:
        content.append(f"  {'  ·  '.join(details)}", style="dim")


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
