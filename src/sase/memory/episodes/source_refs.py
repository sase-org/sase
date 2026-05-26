"""Source reference fingerprinting for deterministic episode drafts."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

from sase.core.episode_facade import generate_source_id
from sase.core.episode_wire import EpisodeSourceRefWire


def build_source_ref(
    path: Path | str,
    kind: str,
    *,
    label: str | None = None,
) -> EpisodeSourceRefWire:
    """Return an episode source ref with stable path, existence, size, and hash."""

    normalized = normalize_source_path(path)
    source_path = Path(normalized)
    exists = source_path.exists()
    size_bytes: int | None = None
    sha256: str | None = None
    if exists:
        try:
            stat = source_path.stat()
        except OSError:
            exists = False
        else:
            size_bytes = stat.st_size
            if source_path.is_file():
                sha256 = hash_file(source_path)

    provisional = EpisodeSourceRefWire(
        id="",
        kind=kind,
        path=normalized,
        label=label,
        exists=exists,
        size_bytes=size_bytes,
        sha256=sha256,
    )
    return replace(provisional, id=generate_source_id(provisional))


def normalize_source_path(path: Path | str) -> str:
    """Normalize source paths for repeatable source IDs without requiring existence."""

    return str(Path(path).expanduser().resolve(strict=False))


def hash_file(path: Path) -> str:
    """Hash a file in chunks with SHA-256."""

    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def sort_source_refs(
    source_refs: list[EpisodeSourceRefWire],
) -> list[EpisodeSourceRefWire]:
    """Return refs sorted by the same stable key used by the Rust canonicalizer."""

    return sorted(
        source_refs,
        key=lambda ref: (
            ref.id,
            ref.kind,
            ref.path,
            ref.sha256 or "",
            -1 if ref.size_bytes is None else ref.size_bytes,
            ref.exists,
        ),
    )


__all__ = [
    "build_source_ref",
    "hash_file",
    "normalize_source_path",
    "sort_source_refs",
]
