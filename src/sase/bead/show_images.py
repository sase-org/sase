"""Bead show image-mode resolution and attachment previews (show_images).

Thin CLI/pager integration for ``sase bead show -i/--images``. Core grammar,
classification, and wire stay in sase-core; Pillow/git stay lazy so beads
without attachments pay zero cost.
"""

from __future__ import annotations

import base64
import io
import os
import shutil
from pathlib import Path

SHOW_IMAGE_MODES = ("auto", "cells", "kitty", "never")
DEFAULT_SHOW_IMAGES = "auto"

MAX_PREVIEW_ROWS = 10
MAX_THUMBS_PER_NOTE = 4
TEXT_PREVIEW_LINES = 5
TEXT_PREVIEW_MAX_BYTES = 1 << 20

_SVG_EPS_SUFFIXES = frozenset({".svg", ".svgz", ".eps", ".epsi"})
_KITTY_CHUNK_SIZE = 4096


def get_show_images_config() -> str:
    """Return ``bead.show.images`` or ``auto`` when missing/malformed."""
    try:
        from sase.config import load_merged_config

        merged = load_merged_config()
    except Exception:
        return DEFAULT_SHOW_IMAGES
    if not isinstance(merged, dict):
        return DEFAULT_SHOW_IMAGES
    bead = merged.get("bead", {})
    if not isinstance(bead, dict):
        return DEFAULT_SHOW_IMAGES
    show = bead.get("show", {})
    if not isinstance(show, dict):
        return DEFAULT_SHOW_IMAGES
    value = show.get("images", DEFAULT_SHOW_IMAGES)
    if not isinstance(value, str):
        return DEFAULT_SHOW_IMAGES
    normalized = value.strip().lower()
    return normalized if normalized in SHOW_IMAGE_MODES else DEFAULT_SHOW_IMAGES


def kitty_graphics_supported(env: dict[str, str] | None = None) -> bool:
    """Return whether the terminal advertises kitty-graphics support."""
    try:
        from sase.doctor.checks_deep_terminal import _kitty_graphics_support

        source = dict(os.environ) if env is None else dict(env)
        support = _kitty_graphics_support(source)
        return bool(support.get("supported"))
    except Exception:
        return False


def resolve_images_mode(
    cli_value: str | None,
    *,
    is_tty: bool,
    env: dict[str, str] | None = None,
) -> tuple[str, str | None]:
    """Resolve the effective ``cells|kitty|never`` mode plus an optional hint.

    ``cli_value`` is the ``-i/--images`` override (``None`` means config).
    Piped output, ``NO_COLOR``, and agent runs always resolve to ``never``
    so ``read``, JSON, and piped ``show`` stay free of escapes and bytes.
    """
    source = dict(os.environ) if env is None else dict(env)
    raw = cli_value if cli_value is not None else get_show_images_config()
    effective = str(raw or DEFAULT_SHOW_IMAGES).strip().lower()
    if effective not in SHOW_IMAGE_MODES:
        effective = DEFAULT_SHOW_IMAGES
    if not is_tty:
        return "never", None
    if source.get("NO_COLOR") not in (None, ""):
        return "never", None
    if source.get("SASE_AGENT") is not None:
        return "never", None
    if effective == "never":
        return "never", None
    if effective == "cells":
        return "cells", None
    inside_tmux = bool(source.get("TMUX"))
    supported = kitty_graphics_supported(source)
    if effective == "kitty":
        if supported and not inside_tmux:
            return "kitty", None
        reason = "inside tmux" if inside_tmux else "terminal lacks kitty support"
        return (
            "cells",
            f"kitty graphics unavailable ({reason}); showing cell previews instead.",
        )
    if supported and not inside_tmux:
        return "kitty", None
    return "cells", None


def previews_enabled(mode: str) -> bool:
    """Return whether attachment previews render for *mode*."""
    return mode in ("cells", "kitty")


def thumbnail_size(
    image_width: int, image_height: int, term_columns: int
) -> tuple[int, int]:
    """Return ``(columns, rows)`` preserving aspect ratio, capped at 10 rows."""
    columns = max(8, min(int(term_columns) - 10 if term_columns > 20 else 40, 60))
    if image_width <= 0 or image_height <= 0:
        return columns, min(MAX_PREVIEW_ROWS, 6)
    rows = max(1, round(columns * image_height / max(1, image_width) / 2))
    return columns, min(MAX_PREVIEW_ROWS, rows)


def _terminal_width() -> int:
    try:
        return max(20, shutil.get_terminal_size(fallback=(80, 24)).columns)
    except Exception:
        return 80


def _truecolor(env: dict[str, str] | None = None) -> bool:
    try:
        from sase.ace.tui.graphics.capability import has_truecolor

        return bool(has_truecolor(env))
    except Exception:
        return False


def is_previewable_raster(name: str, mime_type: str) -> bool:
    """Return whether *name*/*mime* is a decodable raster preview candidate."""
    suffix = Path(name).suffix.lower()
    if suffix in _SVG_EPS_SUFFIXES:
        return False
    if mime_type.lower() in ("image/svg+xml", "application/postscript"):
        return False
    return mime_type.lower().startswith("image/") or suffix in {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".bmp",
        ".tiff",
        ".tif",
    }


def render_cell_thumbnail(view_path: str, *, columns: int, rows: int) -> str | None:
    """Render one cached image to ANSI, or ``None`` when undecodable."""
    try:
        from rich.console import Console

        from sase.ace.tui.graphics.cell import CellImageRenderable

        renderable = CellImageRenderable.from_path(
            view_path,
            columns=max(1, columns),
            rows=max(1, rows),
            truecolor=_truecolor(),
        )
        console = Console(
            force_terminal=True,
            color_system="truecolor" if _truecolor() else "256",
            width=max(10, columns),
        )
        with console.capture() as capture:
            console.print(renderable, end="")
        return capture.get()
    except Exception:
        return None


def sanitize_text_line(line: str, *, width: int = 120) -> str:
    """Strip control/bidi/ANSI carriers from one preview line."""
    cleaned: list[str] = []
    for char in line:
        if char in {"\n", "\t"}:
            cleaned.append(" " if char == "\t" else "")
            continue
        code = ord(char)
        if code < 32 or code == 127:
            continue
        if 0x202A <= code <= 0x202E or 0x2066 <= code <= 0x2069:
            continue
        if char in {"\u200e", "\u200f", "\u061c", "\x1b"}:
            continue
        cleaned.append(char)
    text = "".join(cleaned).rstrip()
    if len(text) > width:
        text = text[: max(0, width - 1)] + "…"
    return text


def preview_text_attachment(view_path: str) -> list[str] | None:
    """Return up to 5 sanitized dim lines, or ``None`` when not previewable."""
    try:
        size = os.path.getsize(view_path)
    except OSError:
        return None
    if size > TEXT_PREVIEW_MAX_BYTES:
        return None
    try:
        with open(view_path, "rb") as handle:
            head = handle.read(TEXT_PREVIEW_MAX_BYTES + 1)
    except OSError:
        return None
    if b"\x00" in head[:8192]:
        return None
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        return None
    lines = [
        sanitize_text_line(line)
        for line in text.splitlines()[:TEXT_PREVIEW_LINES]
        if sanitize_text_line(line).strip()
    ]
    return lines[:TEXT_PREVIEW_LINES] if lines else []


def kitty_escape_for_png(png_bytes: bytes) -> str:
    """Return chunked kitty-graphics escapes transmitting *png_bytes*."""
    encoded = base64.b64encode(bytes(png_bytes)).decode("ascii")
    chunks = [
        encoded[i : i + _KITTY_CHUNK_SIZE]
        for i in range(0, len(encoded), _KITTY_CHUNK_SIZE)
    ] or [""]
    parts: list[str] = []
    for index, chunk in enumerate(chunks):
        more = 1 if index < len(chunks) - 1 else 0
        parts.append(f"\x1b_Ga=T,f=100,m={more};{chunk}\x1b\\")
    return "".join(parts)


def attachment_names_for_issue(issue: object) -> list[str]:
    """Return attachment names from note plus +1-evidence manifests, in order."""
    names: list[str] = []
    for note in getattr(issue, "notes", ()):
        names.extend(attachment.name for attachment in note.attachments)
    for evidence in getattr(issue, "plus_one_evidence", ()):
        names.extend(
            attachment.name for attachment in getattr(evidence, "attachments", ())
        )
    return names


def attachment_targets_for_body(
    bead_id: str, body_plain: str, names: list[str] | tuple[str, ...]
) -> tuple[object, ...]:
    """Return ``AttachedTarget`` spans for chips and descriptor rows.

    ``body_plain`` must be ANSI-free: the owning ``PagerSection.plain_text``.
    The returned offsets are validated against that text, so callers must not
    pass a string containing ANSI SGR escapes. No stripping happens here; the
    caller owns the coordinate space.
    """
    from sase.pager.document import AttachedTarget

    ordered = sorted({name for name in names if name}, key=len, reverse=True)
    spans: list[tuple[int, int, str]] = []
    for name in ordered:
        chip = f"[{name}]"
        start = 0
        while True:
            index = body_plain.find(chip, start)
            if index < 0:
                break
            spans.append((index, index + len(chip), name))
            start = index + len(chip)
        marker = f"       {name}"
        start = 0
        while True:
            index = body_plain.find(marker, start)
            if index < 0:
                break
            name_start = index + len("       ")
            spans.append((name_start, name_start + len(name), name))
            start = name_start + len(name)
    spans.sort()
    filtered: list[tuple[int, int, str]] = []
    last_end = -1
    for start, end, name in spans:
        if start < last_end:
            continue
        filtered.append((start, end, name))
        last_end = end
    targets: list[AttachedTarget] = []
    for start, end, name in filtered:
        targets.append(
            AttachedTarget(
                kind="artifact_ref",
                target=f"attachment:{bead_id}/{name}",
                start=start,
                end=end,
            )
        )
    return tuple(targets)


def kitty_escape_for_path(view_path: str) -> str | None:
    """Return kitty escapes for one cached image, or ``None`` on failure."""
    try:
        suffix = Path(view_path).suffix.lower()
        if suffix in _SVG_EPS_SUFFIXES:
            return None
        with open(view_path, "rb") as handle:
            raw = handle.read(25 * 1024 * 1024 + 1)
    except OSError:
        return None
    if not raw:
        return None
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return kitty_escape_for_png(raw)
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(io.BytesIO(raw)) as image:
            converted = image.convert("RGB")
            buffer = io.BytesIO()
            converted.save(buffer, format="PNG")
            return kitty_escape_for_png(buffer.getvalue())
    except Exception:
        return None


__all__ = [
    "DEFAULT_SHOW_IMAGES",
    "MAX_PREVIEW_ROWS",
    "MAX_THUMBS_PER_NOTE",
    "SHOW_IMAGE_MODES",
    "TEXT_PREVIEW_LINES",
    "TEXT_PREVIEW_MAX_BYTES",
    "attachment_names_for_issue",
    "attachment_targets_for_body",
    "get_show_images_config",
    "is_previewable_raster",
    "kitty_escape_for_path",
    "kitty_escape_for_png",
    "kitty_graphics_supported",
    "preview_text_attachment",
    "previews_enabled",
    "render_cell_thumbnail",
    "resolve_images_mode",
    "sanitize_text_line",
    "thumbnail_size",
]
