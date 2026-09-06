"""Content hashing helpers for the migration kit's backup engine.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    """Return the lowercase hex sha256 digest of a regular file's bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    """Return the lowercase hex sha256 digest of *payload*."""
    return hashlib.sha256(payload).hexdigest()


def directory_total_size(root: Path) -> int:
    """Return the total apparent byte size of every regular file under root.

    Symlinks are not dereferenced and contribute nothing to the total, since
    the backup engine stores the link target rather than the pointee's bytes.
    """
    total = 0
    for entry in root.rglob("*"):
        if entry.is_symlink():
            continue
        if entry.is_file():
            total += entry.stat().st_size
    return total
