"""Shared wire and hint composition for note attachment authoring."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._authoring_models import HINT_ROW_PREFIX

if TYPE_CHECKING:
    from collections.abc import Mapping

_EPS_SUFFIXES = frozenset({".eps", ".epsi", ".epsf"})


def finish_wire(
    *,
    name: str,
    sanitized: str,
    sha256: str,
    size_bytes: int,
    head: bytes,
    object_path: object,
    origin: str | None,
    visibility: str | None = None,
    reason: str | None = None,
    outcome: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Build one wire dict and its stderr echo row from an ingested blob."""
    from sase.core.rust import require_rust_binding

    classify_binding = require_rust_binding("classify_attachment")
    classified: dict[str, Any] = dict(classify_binding(name, bytes(head)))
    wire: dict[str, Any] = {
        "name": name,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "mime_type": str(classified.get("mime_type") or ""),
    }
    dims = _probe_image_dims(name, object_path)
    if dims is not None:
        wire["image"] = {"width": dims[0], "height": dims[1]}
    if origin:
        wire["origin"] = origin
    if visibility in ("public", "private"):
        from sase.bead.attachments import audience as _audience

        if _audience.audience_enabled():
            wire["visibility"] = visibility
    size = _format_size(size_bytes)
    descriptor = wire["mime_type"]
    if dims is not None:
        descriptor += f" · {dims[0]}×{dims[1]}"
    badge = ""
    if visibility == "public":
        badge = " · 🌐 public"
    elif visibility == "private":
        badge = f" · 🔒 private ({reason})" if reason else " · 🔒 private"
        if outcome == "local_only":
            badge = f" · 🔒 private ({reason})" if reason else " · 🔒 private"
    if name == sanitized:
        echo_row = f"attached {name} · {descriptor} · {size}{badge or ' · local'}"
    else:
        echo_row = (
            f"{sanitized} stored as {name} · {descriptor} · {size}{badge or ' · local'}"
        )
    return wire, echo_row


def bare_word_hints(
    scan: Mapping[str, Any],
    base_dir: Path,
) -> list[str]:
    """Dim hints for bare-word mentions whose ``./word`` file exists."""
    hints: list[str] = []
    bare_words = scan.get("bare_words") or []
    for entry in bare_words:
        if not isinstance(entry, dict):
            continue
        word = str(entry.get("word") or "")
        if not word:
            continue
        try:
            is_file = (base_dir / word).is_file()
        except OSError:
            continue
        if not is_file:
            continue
        hints.append(
            f"{HINT_ROW_PREFIX}@{word} looks like text, but ./{word} "
            f"exists — write @./{word} to attach it"
        )
    return hints


def _probe_image_dims(name: str, object_path: object) -> tuple[int, int] | None:
    """Probe pixel dimensions, never raising and never for SVG/EPS."""
    if Path(name).suffix.lower() in _EPS_SUFFIXES:
        return None
    from sase.bead.attachments.images import probe_image

    dims = probe_image(object_path)  # type: ignore[arg-type]
    if dims is None:
        return None
    return (dims.width, dims.height)


def _format_size(size_bytes: int) -> str:
    """Format a byte count the way the write echo does."""
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:g} KiB"
    return f"{size_bytes / (1024 * 1024):g} MiB"
