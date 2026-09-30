"""Shared blob-store contract for bead attachment bytes.

The local content-addressed store (:mod:`sase.bead.attachments.store`) is one
implementation; the git and rclone tiers from later phases implement the same
protocol so placement, upload, and fetch code never branches on backend type.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

ProgressCallback = Callable[[int, int | None], None]
"""Called as ``progress(bytes_done, total_bytes_or_None)`` during transfers."""


class BlobStoreError(Exception):
    """A blob-store operation failed.

    ``transient=True`` means retrying later may succeed (network or remote
    unavailable); ``False`` means the request itself is bad (unknown digest,
    store misconfiguration) or the failure already proved durable.
    ``missing=True`` marks a plain miss (object absent, no corruption);
    ``secret_scan=True`` marks a permanent secret-scanning push rejection.
    """

    def __init__(
        self,
        message: str,
        *,
        transient: bool = False,
        missing: bool = False,
        secret_scan: bool = False,
    ) -> None:
        super().__init__(message)
        self.transient = transient
        self.missing = missing
        self.secret_scan = secret_scan


@runtime_checkable
class BlobStore(Protocol):
    """Digest-addressed byte storage for attachment objects."""

    @property
    def name(self) -> str:
        """Short stable identifier used in logs, badges, and the outbox."""
        ...

    def describe(self) -> str:
        """Human-readable destination/visibility label for the write echo."""
        ...

    def has(self, sha256: str) -> bool:
        """Return whether the object for *sha256* is present in this store."""
        ...

    def put(
        self,
        sha256: str,
        src: Path,
        size_bytes: int,
        progress: ProgressCallback | None = None,
    ) -> None:
        """Upload the local file *src* under digest *sha256*.

        Raises :class:`BlobStoreError` on failure.
        """
        ...

    def get(
        self,
        sha256: str,
        dest: Path,
        progress: ProgressCallback | None = None,
    ) -> None:
        """Download digest *sha256* to *dest*, digest-verified by the caller.

        Raises :class:`BlobStoreError` on failure.
        """
        ...

    def delete(self, sha256: str) -> None:
        """Remove digest *sha256*; a no-op when it is already absent."""
        ...
