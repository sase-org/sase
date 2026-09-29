"""Local content-addressed attachment store.

Layout under ``<sase home>/attachments/`` (``SASE_HOME`` honored)::

    objects/sha256/<xx>/<sha256>   read-only object bytes, mode 0444
    views/<sha256[:16]>/<name>      relative symlinks, extension-preserving
    tmp/                           ingest staging (same filesystem)
    locks/                         per-digest install locks
    tombstones/                    locally recorded purge markers

The store doubles as the read cache: every fetch path materializes through
here, so beads without attachments never touch it and beads with attachments
pay at most one digest verification per object.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path

from sase.bead.attachments.blob_store import BlobStoreError
from sase.core.paths import sase_home

ATTACHMENTS_DIRNAME = "attachments"
OBJECTS_DIRNAME = "objects/sha256"
VIEWS_DIRNAME = "views"
TMP_DIRNAME = "tmp"
LOCKS_DIRNAME = "locks"
TOMBSTONES_DIRNAME = "tombstones"

_CHUNK_SIZE = 1 << 20

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def validate_sha256(value: str) -> str:
    """Return *value* if it is a lowercase hex SHA-256, else raise ValueError."""
    if not _SHA256_RE.match(value):
        raise ValueError(f"invalid sha256 digest: {value!r}")
    return value


def default_store_root() -> Path:
    """Return ``<sase home>/attachments`` honoring ``SASE_HOME``."""
    return sase_home() / ATTACHMENTS_DIRNAME


class LocalAttachmentStore:
    """Content-addressed object store with extension-preserving views."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = (
            Path(root).expanduser() if root is not None else default_store_root()
        )

    @property
    def name(self) -> str:
        return "local"

    def describe(self) -> str:
        return f"local cache ({self.root})"

    # -- layout ---------------------------------------------------------

    @property
    def objects_dir(self) -> Path:
        return self.root / OBJECTS_DIRNAME

    @property
    def views_dir(self) -> Path:
        return self.root / VIEWS_DIRNAME

    @property
    def tmp_dir(self) -> Path:
        return self.root / TMP_DIRNAME

    @property
    def locks_dir(self) -> Path:
        return self.root / LOCKS_DIRNAME

    @property
    def tombstones_dir(self) -> Path:
        return self.root / TOMBSTONES_DIRNAME

    def ensure_dirs(self) -> None:
        """Create the store directories (idempotent)."""
        for path in (
            self.objects_dir,
            self.views_dir,
            self.tmp_dir,
            self.locks_dir,
            self.tombstones_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    # -- objects --------------------------------------------------------

    def object_path(self, sha256: str) -> Path:
        """Return the canonical object path for digest *sha256*."""
        validate_sha256(sha256)
        return self.objects_dir / sha256[:2] / sha256

    def has(self, sha256: str) -> bool:
        """Return whether the object for *sha256* exists locally."""
        return self.object_path(sha256).is_file()

    def verify(self, sha256: str) -> bool:
        """Rehash the stored object; False when missing or mismatched."""
        path = self.object_path(sha256)
        if not path.is_file():
            return False
        digest = hashlib.sha256()
        try:
            with open(path, "rb") as handle:
                while True:
                    chunk = handle.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    digest.update(chunk)
        except OSError:
            return False
        return digest.hexdigest() == sha256

    def remove(self, sha256: str) -> bool:
        """Delete the object and its views; return True when anything was removed."""
        validate_sha256(sha256)
        removed = False
        path = self.object_path(sha256)
        try:
            path.unlink()
            removed = True
        except FileNotFoundError:
            pass
        views = self.views_dir / sha256[:16]
        if views.is_dir() and not views.is_symlink():
            shutil.rmtree(views, ignore_errors=True)
            removed = True
        return removed

    # -- views ----------------------------------------------------------

    def materialize_view(self, sha256: str, name: str) -> Path:
        """Return the extension-preserving view path for an object.

        The view is a relative symlink, so every path shown to a human, the
        viewer, or an agent ends in the real filename. Idempotent: an existing
        correct symlink is reused, a stale one is replaced.
        """
        validate_sha256(sha256)
        if not name or name in {".", ".."} or "/" in name or "\x00" in name:
            raise ValueError(f"invalid attachment view name: {name!r}")
        object_path = self.object_path(sha256)
        if not object_path.is_file():
            raise BlobStoreError(f"attachment object not cached: {sha256[:16]}…")
        views = self.views_dir / sha256[:16]
        views.mkdir(parents=True, exist_ok=True)
        link = views / name
        target = os.path.relpath(object_path, views)
        try:
            if link.is_symlink() and os.readlink(link) == target:
                return link
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(target)
        except OSError as exc:
            raise BlobStoreError(
                f"cannot materialize view for {name!r}: {exc}"
            ) from exc
        return link
