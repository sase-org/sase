"""Resolve ``attachment:<bead-id>/<name>`` refs to local views and pager targets."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.bead.model import BeadNoteAttachment, Issue


def split_attachment_ref(ref: str) -> tuple[str, str] | None:
    """Split ``attachment:<bead-id>/<name>`` into ``(bead_id, name)``."""
    try:
        from sase.artifact_ref_operations import parse_artifact_ref
    except Exception:
        return None
    try:
        parsed = parse_artifact_ref(ref.strip())
    except Exception:
        return None
    if parsed.kind != "attachment":
        return None
    payload_path = getattr(parsed.payload, "path", None)
    if not payload_path or "/" not in payload_path:
        return None
    bead_id, name = payload_path.split("/", 1)
    bead_id, name = bead_id.strip(), name.strip()
    if not bead_id or not name or "/" in name:
        return None
    return bead_id, name


def roster_for_bead_id(bead_id: str) -> tuple[Issue, dict[str, BeadNoteAttachment]]:
    """Return ``(issue, roster)`` for *bead_id* or raise ``KeyError``/``ValueError``."""
    from sase.bead.attachments.lifecycle import roster_for_issue
    from sase.bead.cli_common import get_read_view, resolve_bead_operation_context

    bead_context = resolve_bead_operation_context([bead_id], exit_on_error=False)
    resolved_id = bead_context.resolved_ids[0]
    with get_read_view(bead_context=bead_context) as view:
        issue = view.show(resolved_id)
    roster = roster_for_issue(issue)
    return issue, roster


def materialize_attachment_view(bead_id: str, name: str) -> Path:
    """Materialize the extension-preserving view path, fetching if needed.

    Explicit user actions (``artifact path|open|read attachment:…`` and pager
    link activation) always fetch from the shared store when needed.
    Raises ``KeyError`` when the bead/attachment is unknown and ``FileNotFoundError``
    when no local or shared copy exists.
    """
    from sase.bead.attachments.fetch import fetch_context

    _issue, roster = roster_for_bead_id(bead_id)
    attachment = roster.get(name)
    if attachment is None:
        raise KeyError(f"attachment not found: {name} on {bead_id}")
    sha256 = str(getattr(attachment, "sha256", ""))
    attachment_name = str(getattr(attachment, "name", name))
    size_bytes = getattr(attachment, "size_bytes", None)
    origin = getattr(attachment, "origin", None)
    try:
        from sase.bead.attachment_presentation import (
            attachment_availability,
            attachment_view_path,
        )
    except Exception as exc:
        raise FileNotFoundError(f"attachment unavailable: {name}") from exc
    with fetch_context(mode="force"):
        state = attachment_availability(
            sha256,
            size_bytes=size_bytes if isinstance(size_bytes, int) else None,
            origin=origin if isinstance(origin, str) else None,
            name=attachment_name,
        )
        if state != "cached":
            raise FileNotFoundError(
                f"attachment {name} is ✕ unavailable offline on this machine"
            )
        view = attachment_view_path(sha256, attachment_name)
    if view is None:
        raise FileNotFoundError(
            f"attachment {name} is ✕ unavailable offline on this machine"
        )
    return Path(view)


def viewable_media_specs(issue: object, current_name: str) -> tuple[object, ...]:
    """Return ordered viewer specs for all cached media attachments, current first."""
    try:
        from sase.ace.tui.graphics import ArtifactFileViewSpec, artifact_file_view_mode
        from sase.bead.attachment_presentation import (
            attachment_availability,
            attachment_view_path,
        )
    except Exception:
        return ()
    ordered: list[tuple[str, Path, str]] = []
    for note in getattr(issue, "notes", ()):
        for attachment in getattr(note, "attachments", ()):
            name = str(getattr(attachment, "name", ""))
            sha256 = str(getattr(attachment, "sha256", ""))
            if not name or not sha256:
                continue
            if attachment_availability(sha256) != "cached":
                continue
            try:
                view = attachment_view_path(sha256, name)
            except Exception:
                continue
            if view is None:
                continue
            try:
                mode = artifact_file_view_mode(Path(view))
            except Exception:
                continue
            if mode != "image" and mode != "video" and mode != "pdf":
                continue
            ordered.append((name, Path(view), mode))
    for evidence in getattr(issue, "plus_one_evidence", ()):
        for attachment in getattr(evidence, "attachments", ()):
            name = str(getattr(attachment, "name", ""))
            sha256 = str(getattr(attachment, "sha256", ""))
            if not name or not sha256:
                continue
            if attachment_availability(sha256) != "cached":
                continue
            try:
                view = attachment_view_path(sha256, name)
            except Exception:
                continue
            if view is None:
                continue
            try:
                mode = artifact_file_view_mode(Path(view))
            except Exception:
                continue
            if mode != "image" and mode != "video" and mode != "pdf":
                continue
            ordered.append((name, Path(view), mode))
    seen: dict[str, tuple[Path, str]] = {}
    for seen_name, seen_path, seen_mode in ordered:
        seen.setdefault(seen_name, (seen_path, seen_mode))
    if current_name not in seen:
        return ()
    from sase.ace.tui.graphics import ArtifactFileViewSpec as _Spec

    current_path, current_mode = seen[current_name]
    specs: list[object] = [_Spec(current_path, kind=current_mode)]
    for other_name, (other_path, other_mode) in seen.items():
        if other_name == current_name:
            continue
        specs.append(_Spec(other_path, kind=other_mode))
    return tuple(specs)


__all__ = [
    "materialize_attachment_view",
    "roster_for_bead_id",
    "split_attachment_ref",
    "viewable_media_specs",
]
