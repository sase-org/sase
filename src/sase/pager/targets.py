"""Resolved press destinations shared by pager resolve and landing adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from sase.ace.tui.graphics import ArtifactFileViewSpec
from sase.pager.document import PagerDocument


class LinkTargetKind(StrEnum):
    """What kind of thing a press should do (design doc section D6)."""

    DOCUMENT = "document"
    MEDIA = "media"


@dataclass(frozen=True, slots=True)
class LinkTarget:
    """One resolved press destination.

    ``edit_path``/``edit_line``/``edit_column`` are populated whenever a real
    file backs the target, independent of ``kind`` — this is what lets the
    one-shot ``E`` prefix (design doc D8) reuse the same resolution as a
    normal follow.
    """

    kind: LinkTargetKind
    document: PagerDocument | None = None
    scroll_line: int | None = None
    media_specs: tuple[ArtifactFileViewSpec, ...] = ()
    edit_path: Path | None = None
    edit_line: int | None = None
    edit_column: int | None = None


@dataclass(frozen=True, slots=True)
class LinkResolution:
    """One background resolution attempt and any UI-ready dead-end copy.

    The pager apply path must consume this object as-is: it must not search,
    stat, or talk to Git again to rebuild a toast. ``resolve_ref`` is the
    convenience wrapper that returns only ``target``.
    """

    target: LinkTarget | None = None
    unresolved_message: str | None = None
    retryable: bool = False


__all__ = ["LinkResolution", "LinkTarget", "LinkTargetKind"]
