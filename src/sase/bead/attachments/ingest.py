"""One-pass streaming ingest into the local attachment store.

Both entry points read the source exactly once in bounded (1 MiB) memory::

    ingest_path(path, progress=None)
    ingest_stream(fileobj, progress=None)

They return :class:`IngestedBlob` and leave a read-only (0444) object in the
store, installed under a per-digest ``flock`` so concurrent ingests of the
same bytes produce one object. All-zero chunks are written as holes, so
sparse sources stay sparse on disk.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import shutil
import stat
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from sase.bead.attachments.blob_store import BlobStoreError, ProgressCallback
from sase.bead.attachments.store import LocalAttachmentStore

IngestProgress = ProgressCallback

_CHUNK_SIZE = 1 << 20
_HEAD_SIZE = 4096


class IngestError(BlobStoreError):
    """A file could not be ingested (refused kind, change, or I/O failure)."""


@dataclass(frozen=True)
class IngestedBlob:
    """Result of a successful ingest."""

    sha256: str
    size_bytes: int
    head: bytes
    object_path: Path


def ingest_path(
    path: str | os.PathLike[str],
    progress: IngestProgress | None = None,
    *,
    store: LocalAttachmentStore | None = None,
) -> IngestedBlob:
    """Ingest the regular file at *path* into the store in one pass."""
    active = store or LocalAttachmentStore()
    try:
        # O_NONBLOCK so opening a FIFO never waits for a writer; the
        # kind check below refuses it before any read. Regular-file
        # reads are unaffected by non-blocking mode.
        src_fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        raise IngestError(f"cannot attach {path}: file not found") from None
    except OSError as exc:
        raise IngestError(f"cannot attach {path}: {exc.strerror or exc}") from exc
    try:
        with os.fdopen(src_fd, "rb", buffering=0) as src:
            return _ingest_fd(
                src, active, progress, display_name=str(path), check_change=True
            )
    except IngestError:
        raise
    except OSError as exc:
        raise IngestError(f"cannot attach {path}: {exc.strerror or exc}") from exc


def ingest_stream(
    fileobj: BinaryIO,
    progress: IngestProgress | None = None,
    *,
    store: LocalAttachmentStore | None = None,
    display_name: str = "<stdin>",
) -> IngestedBlob:
    """Ingest bytes from an already-open binary stream in one pass."""
    active = store or LocalAttachmentStore()
    try:
        return _ingest_fd(
            fileobj, active, progress, display_name=display_name, check_change=False
        )
    except IngestError:
        raise
    except OSError as exc:
        raise IngestError(
            f"cannot attach {display_name}: {exc.strerror or exc}"
        ) from exc


def _refused_kind_message(display_name: str, mode: int) -> str:
    if stat.S_ISDIR(mode):
        return (
            f"cannot attach {display_name}: it is a directory "
            "(hint: `tar czf dir.tar.gz dir/` then attach the archive)"
        )
    if stat.S_ISFIFO(mode):
        return f"cannot attach {display_name}: it is a named pipe (FIFO)"
    if stat.S_ISSOCK(mode):
        return f"cannot attach {display_name}: it is a socket"
    if stat.S_ISCHR(mode):
        return f"cannot attach {display_name}: it is a character device"
    if stat.S_ISBLK(mode):
        return f"cannot attach {display_name}: it is a block device"
    return f"cannot attach {display_name}: not a regular file"


def _ingest_fd(
    src: BinaryIO,
    store: LocalAttachmentStore,
    progress: IngestProgress | None,
    *,
    display_name: str,
    check_change: bool,
) -> IngestedBlob:
    fileno: int | None = None
    before: os.stat_result | None = None
    get_fileno: Callable[[], int] | None = getattr(src, "fileno", None)
    if get_fileno is not None:
        with contextlib.suppress(Exception):
            fileno = get_fileno()
    if fileno is not None:
        with contextlib.suppress(OSError):
            before = os.fstat(fileno)
    if check_change and before is not None and not stat.S_ISREG(before.st_mode):
        raise IngestError(_refused_kind_message(display_name, before.st_mode))

    store.ensure_dirs()
    if before is not None and stat.S_ISREG(before.st_mode):
        _check_free_space(store, before.st_size, display_name)

    digest = hashlib.sha256()
    head = bytearray()
    bytes_read = 0

    tmp_fd, tmp_name = tempfile.mkstemp(dir=store.tmp_dir, prefix="ingest-")
    try:
        os.fchmod(tmp_fd, 0o600)
        while True:
            chunk = src.read(_CHUNK_SIZE)
            if chunk is None:
                continue
            if not chunk:
                break
            if isinstance(chunk, str):  # pragma: no cover - defensive
                raise IngestError(
                    f"cannot attach {display_name}: stream must be binary"
                )
            chunk = bytes(chunk)
            digest.update(chunk)
            if len(head) < _HEAD_SIZE:
                head += chunk[: _HEAD_SIZE - len(head)]
            if chunk.count(0) == len(chunk):
                os.lseek(tmp_fd, len(chunk), os.SEEK_CUR)
            else:
                os.write(tmp_fd, chunk)
            bytes_read += len(chunk)
            if progress is not None:
                expected = before.st_size if before is not None else None
                progress(bytes_read, expected)
        os.ftruncate(tmp_fd, bytes_read)
        os.fsync(tmp_fd)
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(tmp_fd)
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
    else:
        os.close(tmp_fd)

    if before is not None and stat.S_ISREG(before.st_mode):
        try:
            after = os.fstat(fileno) if fileno is not None else None
        except OSError:
            after = None
        if (
            after is None
            or after.st_size != before.st_size
            or after.st_mtime_ns != before.st_mtime_ns
            or bytes_read != before.st_size
        ):
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise IngestError(
                f"cannot attach {display_name}: file changed while attaching"
            )

    sha = digest.hexdigest()
    object_path = store.object_path(sha)
    with _digest_lock(store, sha):
        if object_path.is_file():
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
        else:
            object_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(tmp_name, object_path)
            os.chmod(object_path, 0o444)
            _fsync_dir(object_path.parent)
    return IngestedBlob(
        sha256=sha,
        size_bytes=bytes_read,
        head=bytes(head),
        object_path=object_path,
    )


@contextlib.contextmanager
def _digest_lock(store: LocalAttachmentStore, sha256: str) -> Iterator[None]:
    """Hold an exclusive per-digest lock for object installation."""
    store.locks_dir.mkdir(parents=True, exist_ok=True)
    lock_path = store.locks_dir / f"{sha256}.lock"
    with open(lock_path, "ab") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _check_free_space(
    store: LocalAttachmentStore, size_bytes: int, display_name: str
) -> None:
    try:
        free = shutil.disk_usage(store.tmp_dir).free
    except OSError:
        return
    if free < size_bytes:
        raise IngestError(
            f"cannot attach {display_name}: not enough free space "
            f"(need {size_bytes} bytes, have {free})"
        )


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        with contextlib.suppress(OSError):
            os.fsync(fd)
    finally:
        os.close(fd)
