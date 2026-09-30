"""Audience-aware presentation for bead note attachments.

One chip formatter shared by CLI, JSON, history, and bead pages. CLI prose
replaces each ``@attachment:<name>`` token with ``[name]``, filenames are
stripped of control and bidi characters, and an ``ATTACHMENTS`` block lists
descriptors plus the local view path. Every descriptor line carries an
audience badge (``🌐`` public, ``🔒`` private or absent). Bead-page helpers
render public files as links, embed public images, and never emit private
digests or local reasons. No image drawing, no bytes, no ANSI escapes in
the data itself.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any

_ATTACHMENT_TOKEN_RE = re.compile(r"@attachment:([^\s]+)")

PUBLIC_BADGE = "🌐"
PRIVATE_BADGE = "🔒"


def _audience_badge(visibility: str | None) -> str:
    """Return ``🌐`` for explicit public, else ``🔒`` (private or absent)."""
    return PUBLIC_BADGE if visibility == "public" else PRIVATE_BADGE


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
    visibility: str | None = None,
) -> str:
    """Return one ``🌐/🔒 name · mime · dims · size · sha256:<12>`` descriptor.

    The badge is ``🌐`` for explicit public, else ``🔒`` (private or
    absent visibility).
    """
    display = strip_display_name(name)
    dims = _format_attachment_dims(image)
    size = _format_attachment_size(size_bytes)
    parts = [display, mime_type]
    if dims is not None:
        parts.append(dims)
    parts.extend([size, f"sha256:{sha256[:12]}"])
    return f"{_audience_badge(visibility)} " + " \u00b7 ".join(parts)


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


def dispatch_fetch_hint(origin: str | None) -> str | None:
    """Return the ``%dispatch`` hint for an origin-only object, if known."""
    if not isinstance(origin, str) or not origin.strip():
        return None
    machine = origin.strip()
    return f"fetch via %dispatch:{machine} from {machine}"


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

    ``cached`` renders the extension-preserving view path. ``pending_upload``,
    ``local_only``, ``origin_only``, and ``blocked`` render the view path
    (the bytes are local) plus the badge; ``origin_only`` appends the
    ``%dispatch`` fetch hint. Every other state renders only its badge.
    """
    from sase.bead.attachments.fetch import (
        attachment_badge,
        resolve_badge_origin,
        resolve_badge_repo,
    )

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
    resolved_origin = resolve_badge_origin(sha256, origin)
    if state in ("pending_upload", "local_only", "origin_only", "blocked"):
        view = attachment_view_path(sha256, name)
        if view is not None:
            lines.append(view)
    badge = attachment_badge(
        state,
        size_bytes=size_bytes if isinstance(size_bytes, int) else None,
        bead_id=bead_id,
        name=name,
        origin=resolved_origin,
        repo=resolve_badge_repo(sha256),
    )
    if badge is not None:
        lines.append(badge)
    if state == "origin_only":
        hint = dispatch_fetch_hint(resolved_origin)
        if hint is not None:
            lines.append(hint)
    return lines


def attachment_page_line(
    *,
    name: str,
    mime_type: str,
    image: Any,
    size_bytes: int,
    visibility: str | None = None,
    url: str | None = None,
) -> str:
    """Return one bead-page line for an attachment.

    Bead pages are public artifacts, so the line names the file, its media
    type, and its size — and never a path, a local reason, or (for private
    files) a digest. Public files render as ``🌐 [name](url)`` when a hosted
    URL is available, else as a badged plain name; private files render as
    ``🔒 name · mime · size (private attachment)``.
    """
    from sase.agents_sync.rendering_markdown import md_escape

    display = md_escape(strip_display_name(name))
    dims = _format_attachment_dims(image)
    size = _format_attachment_size(size_bytes)
    if visibility == "public":
        labeled = f"[{display}]({url})" if url else display
        parts = [labeled, mime_type]
        if dims is not None:
            parts.append(dims)
        parts.append(size)
        return f"{PUBLIC_BADGE} " + " · ".join(parts)
    parts = [display, mime_type]
    if dims is not None:
        parts.append(dims)
    parts.append(size)
    return f"{PRIVATE_BADGE} " + " · ".join(parts) + " (private attachment)"


def page_prose_with_attachments(
    text: str,
    entries: Mapping[str, tuple[str | None, str | None]] | None,
) -> str:
    """Replace ``@attachment:<name>`` tokens with page links or chips.

    *entries* maps an attachment name to its ``(visibility, url)`` pair.
    Public names render as ``[name](url)`` (or ``[name]`` without a URL);
    private and absent-visibility names render as ``🔒 name``; names absent
    from *entries* render as ``[name]`` — never as the raw token. Display
    names are markdown-escaped; local reasons and digests never appear.
    """
    from sase.agents_sync.rendering_markdown import md_escape

    known: dict[str, tuple[str | None, str | None]] = dict(entries or {})

    def _render_token(raw: str, trailing: str) -> str:
        display = md_escape(strip_display_name(raw))
        if not display:
            return f"@attachment:{raw}{trailing}"
        visibility, url = known.get(raw, (None, None))
        if visibility == "public":
            if url:
                return f"[{display}]({url}){trailing}"
            return f"[{display}]{trailing}"
        if raw in known:
            return f"{PRIVATE_BADGE} {display}{trailing}"
        return f"[{display}]{trailing}"

    for token_name in sorted(known, key=len, reverse=True):
        if not token_name:
            continue
        rendered = _render_token(token_name, "")
        # Re-render without trailing handling: exact tokens carry none.
        text = text.replace(f"@attachment:{token_name}", rendered)

    def _repl(match: re.Match[str]) -> str:
        raw, trailing = _split_trailing(match.group(1))
        if not raw:
            return match.group(0)
        return _render_token(raw, trailing)

    return _ATTACHMENT_TOKEN_RE.sub(_repl, text)


def page_image_embed(
    *,
    name: str,
    mime_type: str,
    size_bytes: int,
    visibility: str | None,
    url: str | None,
) -> str | None:
    """Return a ``![name](url)`` embed line, or ``None`` when not embeddable.

    Only public images with a hosted URL and at most the auto-fetch cap
    embed; extensionless objects and non-images link instead of embedding.
    """
    if visibility != "public" or not url:
        return None
    if not isinstance(mime_type, str) or not mime_type.startswith("image/"):
        return None
    try:
        from sase.bead.config import get_attachment_auto_fetch_max_bytes

        cap = get_attachment_auto_fetch_max_bytes()
    except Exception:
        cap = 26214400
    if not isinstance(size_bytes, int) or size_bytes < 0 or size_bytes > cap:
        return None
    from sase.agents_sync.rendering_markdown import md_escape

    return f"![{md_escape(strip_display_name(name))}]({url})"


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
    "PRIVATE_BADGE",
    "PUBLIC_BADGE",
    "attachment_availability",
    "attachment_descriptor",
    "attachment_page_line",
    "attachment_status_lines",
    "attachment_view_path",
    "compact_attachment_suffix",
    "dispatch_fetch_hint",
    "extract_attachment_tokens",
    "page_image_embed",
    "page_prose_with_attachments",
    "prose_with_chips",
    "strip_display_name",
]
