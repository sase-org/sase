"""Cached attachment views for the Beads pane open-attachments key."""

from __future__ import annotations

from pathlib import Path


def cached_attachment_view_paths(issue: object) -> tuple[Path, ...]:
    """Return extension-preserving view paths for cached attachments.

    Iterates notes then +1 evidence in display order, deduplicating by
    attachment name (first occurrence wins, matching the roster's latest-wins
    rule in reverse). Only the local content-addressed store is consulted:
    no network fetch, no decode. Missing or uncached attachments are
    skipped, so a bead without local bytes yields ``()`` and the caller can
    show an honest badge instead of failing.
    """
    try:
        from sase.bead.attachment_presentation import (
            attachment_availability,
            attachment_view_path,
        )
    except Exception:
        return ()
    ordered: list[tuple[str, str]] = []
    for note in getattr(issue, "notes", ()):
        for attachment in getattr(note, "attachments", ()):
            name = str(getattr(attachment, "name", ""))
            sha256 = str(getattr(attachment, "sha256", ""))
            if name and sha256:
                ordered.append((name, sha256))
    for evidence in getattr(issue, "plus_one_evidence", ()):
        for attachment in getattr(evidence, "attachments", ()):
            name = str(getattr(attachment, "name", ""))
            sha256 = str(getattr(attachment, "sha256", ""))
            if name and sha256:
                ordered.append((name, sha256))
    seen: set[str] = set()
    paths: list[Path] = []
    for name, sha256 in ordered:
        if name in seen:
            continue
        seen.add(name)
        try:
            if attachment_availability(sha256) != "cached":
                continue
        except Exception:
            continue
        try:
            view = attachment_view_path(sha256, name)
        except Exception:
            continue
        if view is None:
            continue
        try:
            candidate = Path(view)
        except Exception:
            continue
        paths.append(candidate)
    return tuple(paths)


__all__ = ["cached_attachment_view_paths"]
