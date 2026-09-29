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


def format_attachment_size(size_bytes: int) -> str:
    """Format a byte count the way the write echo does."""
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:g} KiB"
    return f"{size_bytes / (1024 * 1024):g} MiB"


def format_attachment_dims(image: Any) -> str | None:
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
    dims = format_attachment_dims(image)
    size = format_attachment_size(size_bytes)
    parts = [display, mime_type]
    if dims is not None:
        parts.append(dims)
    parts.extend([size, f"sha256:{sha256[:12]}"])
    return " \u00b7 ".join(parts)


def attachment_availability(sha256: str) -> str:
    """Return ``cached`` when the local CAS holds the object, else ``unavailable``."""
    try:
        from sase.bead.attachments.store import LocalAttachmentStore

        if LocalAttachmentStore().has(sha256):
            return "cached"
    except Exception:
        pass
    return "unavailable"


def attachment_view_path(sha256: str, name: str) -> str | None:
    """Materialize the extension-preserving view path, or ``None`` when missing."""
    try:
        from sase.bead.attachments.store import LocalAttachmentStore

        return str(LocalAttachmentStore().materialize_view(sha256, name))
    except Exception:
        return None


def total_attachment_count(notes: Any) -> int:
    """Count manifests already stored on ``BeadNote`` records."""
    return sum(len(getattr(note, "attachments", ())) for note in notes)


def compact_attachment_suffix(notes: Any) -> str:
    """Return `` 📎N`` when the total attachment count is non-zero, else ````."""
    total = total_attachment_count(notes)
    return f" \U0001f4ce{total}" if total else ""


def note_label_attachment_suffix(attachment_count: int) -> str:
    """Return `` · 📎 N`` for a note label, or ```` when there are none."""
    return f" \u00b7 \U0001f4ce {attachment_count}" if attachment_count else ""


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
    "attachment_view_path",
    "compact_attachment_suffix",
    "extract_attachment_tokens",
    "format_attachment_dims",
    "format_attachment_size",
    "note_label_attachment_suffix",
    "prose_with_chips",
    "strip_display_name",
    "total_attachment_count",
]
