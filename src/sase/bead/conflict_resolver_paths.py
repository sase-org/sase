"""Bead-store path and conflict-shape classification helpers."""

from __future__ import annotations

from pathlib import Path

from sase.bead.project import (
    BEADS_DIRNAME,
    BEADS_DIRNAME_NON_VC,
    BEADS_DIRNAME_ROOT,
)
from sase.bead_pages.paths import BEAD_PAGES_DIRNAME

_BEAD_STORE_ENTRIES = frozenset(
    {"events", "issues.jsonl", "metadata.json", "config.json"}
)


def resolve_beads_dir(
    repo_root: Path, beads_dir: str | Path | None = None
) -> Path | None:
    root = repo_root.expanduser().resolve()
    canonical_relpaths = {
        BEADS_DIRNAME,
        BEADS_DIRNAME_NON_VC,
        BEADS_DIRNAME_ROOT,
    }
    if beads_dir is not None:
        resolved = Path(beads_dir).expanduser().resolve()
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError:
            return None
        if relative not in canonical_relpaths or not resolved.is_dir():
            return None
        return resolved
    candidates = [
        (root / dirname).resolve()
        for dirname in (BEADS_DIRNAME, BEADS_DIRNAME_NON_VC)
        if (root / dirname).is_dir()
    ]
    if (root / "config.json").is_file():
        candidates.append(root)
    return candidates[0] if len(set(candidates)) == 1 else None


def is_bead_path(path: str, bead_prefix: str) -> bool:
    if not bead_prefix:
        return bool(Path(path).parts) and (
            Path(path).parts[0] in _BEAD_STORE_ENTRIES
            or is_regenerable_bead_path(path, bead_prefix)
        )
    return path == bead_prefix or path.startswith(f"{bead_prefix}/")


def is_regenerable_bead_path(path: str, bead_prefix: str) -> bool:
    parts = Path(path).parts
    return not bead_prefix and len(parts) > 1 and parts[0] == BEAD_PAGES_DIRNAME


def is_event_stream_path(path: str, bead_prefix: str) -> bool:
    prefix = f"{store_path(bead_prefix, 'events/streams')}/"
    return path.startswith(prefix) and path.endswith(".jsonl")


def is_mergeable_bead_path(path: str, bead_prefix: str) -> bool:
    return path in {
        store_path(bead_prefix, "issues.jsonl"),
        store_path(bead_prefix, "events/manifest.json"),
        store_path(bead_prefix, "config.json"),
    } or is_event_stream_path(path, bead_prefix)


def store_path(prefix: str, rest: str) -> str:
    """Join one store-relative path without a leading slash at repo root."""

    return f"{prefix}/{rest}" if prefix else rest
