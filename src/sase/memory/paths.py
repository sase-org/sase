"""Canonical and compatibility paths for project and home memory content."""

from __future__ import annotations

from pathlib import Path

from sase.content_layout import CompatibleLayoutPath, resolve_project_layout

CANONICAL_MEMORY_RELATIVE_ROOT = Path("sase") / "memory"
LEGACY_MEMORY_RELATIVE_ROOT = Path("memory")


def memory_layout(root: Path | str) -> CompatibleLayoutPath:
    """Return the shared canonical/legacy memory contract for ``root``."""
    return resolve_project_layout(Path(root)).memory


def memory_write_root(root: Path | str) -> Path:
    """Return the canonical destination for all new memory content."""
    return memory_layout(root).write_path


def memory_read_root(root: Path | str, *, label: str = "memory") -> Path | None:
    """Return the selected compatibility read root or report a collision."""
    return memory_layout(root).resolve_read(label)


def canonical_memory_reference(path: Path | str) -> Path:
    """Return a root-relative memory path in canonical ``sase/memory`` form."""
    candidate = Path(path)
    relative = _relative_memory_path(candidate)
    if relative is None:
        return candidate
    return CANONICAL_MEMORY_RELATIVE_ROOT / relative


def memory_note_relative_path(path: Path | str) -> Path | None:
    """Return the portion of a canonical or legacy path below its memory root."""
    return _relative_memory_path(Path(path))


def _relative_memory_path(path: Path) -> Path | None:
    for prefix in (CANONICAL_MEMORY_RELATIVE_ROOT, LEGACY_MEMORY_RELATIVE_ROOT):
        try:
            return path.relative_to(prefix)
        except ValueError:
            continue
    return None


__all__ = [
    "CANONICAL_MEMORY_RELATIVE_ROOT",
    "LEGACY_MEMORY_RELATIVE_ROOT",
    "canonical_memory_reference",
    "memory_layout",
    "memory_note_relative_path",
    "memory_read_root",
    "memory_write_root",
]
