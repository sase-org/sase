"""Plain-text presentation for bead note attachments (beta).

One chip formatter shared by CLI, JSON, and history. This phase uses the
plain-text form only: prose replaces each ``@attachment:<name>`` token with
``[name]``, filenames are stripped of control and bidi characters, and an
``ATTACHMENTS`` block lists descriptors plus the local view path. No image
drawing, no bytes, no ANSI escapes in the data itself.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

_ATTACHMENT_TOKEN_RE = re.compile(r"@attachment:([^\s]+)")

# Trailing punctuation the scanner trims from a reference.
_TOKEN_TRAILING_CHARS = ".,;:!?)]" + "}>"


def strip_display_name(name: str) -> str:
    """Strip control and bidi characters from a filename for terminal display."""
    kept: list[str] = []
    for char in name:
        if unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"}:
            continue
        kept.append(char)
    return "".join(kept)


def _split_trailing(raw: str) -> tuple[str, str]:
    """Split scanner-trimmed trailing punctuation off a token name."""
    end = len(raw)
    while end > 0 and raw[end - 1] in _TOKEN_TRAILING_CHARS:
        end -= 1
    return raw[:end], raw[end:]


def prose_with_chips(text: str, names: Any = None) -> str:
    """Replace ``@attachment:<name>`` tokens with ``[name]`` chips."""
    known: set[str] = set(names or ())
    for name in sorted(known, key=len, reverse=True):
        if not name:
            continue
        text = text.replace(f"@attachment:{name}", f"[{strip_display_name(name)}]")

    def _repl(match: re.Match[str]) -> str:
        raw, trailing = _split_trailing(match.group(1))
        if not raw:
            return match.group(0)
        return f"[{strip_display_name(raw)}]{trailing}"

    return _ATTACHMENT_TOKEN_RE.sub(_repl, text)


def _format_attachment_size(size_bytes: int | None) -> str:
    """Format a byte count the way the write echo does."""
    from sase.bead.attachments.fetch import format_attachment_size

    return format_attachment_size(size_bytes)


def _format_attachment_dims(image: Any) -> str | None:
    """Return ``WxH`` for an image attachment, else ``None``."""
    if image is None:
        return None
    if isinstance(image, dict):
        width = image.get("width")
        height = image.get("height")
    elif isinstance(image, (list, tuple)) and len(image) == 2:
        width, height = image
    else:
        return None
    if (
        isinstance(width, bool)
        or not isinstance(width, int)
        or isinstance(height, bool)
        or not isinstance(height, int)
    ):
        return None
    if width <= 0 or height <= 0:
        return None
    return f"{width}\u00d7{height}"


def attachment_descriptor(
    *,
    name: str,
    mime_type: str,
    image: Any,
    size_bytes: int,
    sha256: str,
) -> str:
    """Return one ``name · mime · dims · size · sha256:<12>`` descriptor."""
    display = strip_display_name(name)
    dims = _format_attachment_dims(image)
    size = _format_attachment_size(size_bytes)
    parts = [display, mime_type]
    if dims is not None:
        parts.append(dims)
    parts.extend([size, f"sha256:{sha256[:12]}"])
    return " \u00b7 ".join(parts)


def attachment_availability(
    sha256: str,
    *,
    size_bytes: int | None = None,
    origin: str | None = None,
    name: str | None = None,
    visibility: str | None = None,
) -> str:
    """Return the availability state for one attachment digest.

    States are ``cached``, ``not_downloaded``, ``pending_upload``,
    ``local_only``, ``unavailable``, ``purged``, and ``corrupt``. With no
    shared ``attachments-private`` store the legacy two states hold: a
    verified local object is ``cached``, anything else ``unavailable``.
    ``remote`` is transient and never returned. Never raises.
    """
    try:
        from sase.bead.attachments.fetch import attachment_state

        if isinstance(size_bytes, bool):
            size_bytes = None
        if size_bytes is not None and (
            not isinstance(size_bytes, int) or size_bytes < 0
        ):
            size_bytes = None
        effective = visibility if visibility in ("public", "private") else "private"
        return attachment_state(
            sha256,
            size_bytes=size_bytes,
            origin=origin,
            name=name,
            visibility=effective,
        )
    except Exception:
        pass
    try:
        from sase.bead.attachments.store import LocalAttachmentStore

        if LocalAttachmentStore().has(sha256):
            return "cached"
    except Exception:
        pass
    return "unavailable"


def attachment_status_lines(
    *,
    bead_id: str | None,
    name: str,
    sha256: str,
    size_bytes: int | None = None,
    origin: str | None = None,
    visibility: str | None = None,
) -> list[str]:
    """Return view-path plus badge lines for one attachment in text output.

    ``cached`` renders the extension-preserving view path. ``pending_upload``
    and ``local_only`` render the view path (the bytes are local) plus the
    badge. Every other state renders only its badge.
    """
    from sase.bead.attachments.fetch import attachment_badge, resolve_badge_origin

    state = attachment_availability(
        sha256,
        size_bytes=size_bytes,
        origin=origin,
        name=name,
        visibility=visibility,
    )
    lines: list[str] = []
    if state == "cached":
        view = attachment_view_path(sha256, name)
        if view is not None:
            lines.append(view)
        else:
            badge = attachment_badge("unavailable")
            if badge is not None:
                lines.append(badge)
        return lines
    if state in ("pending_upload", "local_only"):
        view = attachment_view_path(sha256, name)
        if view is not None:
            lines.append(view)
    badge = attachment_badge(
        state,
        size_bytes=size_bytes if isinstance(size_bytes, int) else None,
        bead_id=bead_id,
        name=name,
        origin=resolve_badge_origin(sha256, origin),
    )
    if badge is not None:
        lines.append(badge)
    return lines


def attachment_page_line(
    *,
    name: str,
    mime_type: str,
    image: Any,
    size_bytes: int,
) -> str:
    """Return one public bead-page line for an attachment.

    Bead pages are public artifacts, so the line names the file, its media
    type, and its size with a private-attachment marker — and never a path,
    a link, or a digest.
    """
    display = strip_display_name(name)
    dims = _format_attachment_dims(image)
    size = _format_attachment_size(size_bytes)
    parts = [display, mime_type]
    if dims is not None:
        parts.append(dims)
    parts.append(size)
    return "🔒 " + " · ".join(parts) + " (private attachment)"


def attachment_view_path(sha256: str, name: str) -> str | None:
    """Materialize the extension-preserving view path, or ``None`` when missing."""
    try:
        from sase.bead.attachments.store import LocalAttachmentStore

        return str(LocalAttachmentStore().materialize_view(sha256, name))
    except Exception:
        return None


def _total_attachment_count(notes: Any) -> int:
    """Count manifests already stored on ``BeadNote`` records."""
    return sum(len(getattr(note, "attachments", ())) for note in notes)


def _issue_attachment_count(issue: Any) -> int:
    """Count note plus +1 evidence attachments on one bead."""
    notes = getattr(issue, "notes", ())
    evidence = getattr(issue, "plus_one_evidence", ())
    return _total_attachment_count(notes) + sum(
        len(getattr(entry, "attachments", ())) for entry in evidence
    )


def compact_attachment_suffix(notes: Any) -> str:
    """Return `` 📎N`` when the total attachment count is non-zero, else ````."""
    if hasattr(notes, "notes") and hasattr(notes, "plus_one_evidence"):
        total = _issue_attachment_count(notes)
    else:
        total = _total_attachment_count(notes)
    return f" \U0001f4ce{total}" if total else ""


def extract_attachment_tokens(text: str) -> list[str]:
    """Return unique ``@attachment:<name>`` names in first-seen order."""
    seen: list[str] = []
    for match in _ATTACHMENT_TOKEN_RE.finditer(text or ""):
        name, _trailing = _split_trailing(match.group(1))
        if name and name not in seen:
            seen.append(name)
    return seen


__all__ = [
    "attachment_availability",
    "attachment_descriptor",
    "attachment_page_line",
    "attachment_status_lines",
    "attachment_view_path",
    "compact_attachment_suffix",
    "extract_attachment_tokens",
    "prose_with_chips",
    "strip_display_name",
]
