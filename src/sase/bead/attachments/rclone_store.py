"""Rclone-backed blob store for the large-object attachment tier.

:class:`RcloneAttachmentStore` implements the :class:`BlobStore` protocol
over an rclone remote (``bead.attachments.large_store``). Objects live at
``<remote>/files/objects/sha256/<xx>/<sha>``, reusing the
``artifact_object_relpath`` layout, with tombstones beside them at
``files/tombstones/sha256/<xx>/<sha>.json``. A plain local path works as
the remote (the acceptance tests use one); SFTP and R2 remotes come from
the per-machine ``rclone.conf``.

Uploads stage to a ``.partial-<uuid>`` name, ``moveto`` into place, then
verify the remote size (and the SHA-256 when the backend reports one).
Downloads stream ``rclone cat`` into the local CAS with digest
verification. Every rclone invocation is bounded by a timeout and its
stderr is captured into errors. A missing ``rclone`` binary is a clear
non-transient error (and a doctor finding), never a traceback.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

from sase.bead.attachments.blob_store import BlobStoreError, ProgressCallback
from sase.bead.attachments.store import LocalAttachmentStore, validate_sha256

log = logging.getLogger(__name__)

_CHUNK_SIZE = 1 << 20
_RCLONE_TIMEOUT_SECONDS = 300.0


def rclone_binary(binary: str = "rclone") -> str | None:
    """Return the resolved rclone executable, or None when it is absent."""
    with contextlib.suppress(Exception):
        return shutil.which(binary)
    return None


def _object_relpath(sha256: str) -> str:
    """Return the canonical remote object path for *sha256*."""
    validate_sha256(sha256)
    return f"files/objects/sha256/{sha256[:2]}/{sha256}"


def _tombstone_relpath(sha256: str) -> str:
    """Return the canonical remote tombstone path for *sha256*."""
    validate_sha256(sha256)
    return f"files/tombstones/sha256/{sha256[:2]}/{sha256}.json"


class RcloneAttachmentStore:
    """A :class:`BlobStore` over an rclone remote destination."""

    def __init__(
        self,
        remote: str,
        label: str,
        *,
        max_bytes: int = 2147483648,
        rclone_binary_name: str = "rclone",
        timeout: float | None = None,
        config_path: str | Path | None = None,
    ) -> None:
        """Point at the rclone destination *remote*; *label* feeds describe.

        *remote* is ``<name>:<path>`` for a configured remote or a plain
        local path. *max_bytes* caps placement; *timeout* bounds every
        rclone invocation; *config_path* sets ``RCLONE_CONFIG`` for them.
        """
        cleaned = (remote or "").strip().rstrip("/")
        if not cleaned:
            raise BlobStoreError("rclone large store needs a remote destination")
        self._remote = cleaned
        self._label = label or cleaned
        self._max_bytes = max_bytes
        self._binary = rclone_binary_name
        self._timeout = (
            _RCLONE_TIMEOUT_SECONDS if timeout is None else max(1.0, timeout)
        )
        self._config_path = str(config_path) if config_path else None

    @property
    def name(self) -> str:
        """Short stable identifier used in logs, badges, and the outbox."""

        return "large"

    @property
    def max_bytes(self) -> int:
        """Largest single object this tier accepts, in bytes."""

        return self._max_bytes

    def describe(self) -> str:
        """Human-readable destination/visibility label for the write echo."""

        return self._label

    # -- subprocess ---------------------------------------------------

    def _env(self) -> dict[str, str] | None:
        if not self._config_path:
            return None
        env = dict(os.environ)
        env["RCLONE_CONFIG"] = self._config_path
        return env

    def _run(self, *args: str, what: str) -> subprocess.CompletedProcess[str]:
        binary = rclone_binary(self._binary)
        if binary is None:
            raise BlobStoreError(
                f"cannot reach {self._label}: the rclone binary "
                f"({self._binary!r}) is not installed; install rclone and "
                "configure the large-store remote "
                "(sase doctor reports the setup steps)."
            )
        try:
            return subprocess.run(
                [binary, *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env=self._env(),
            )
        except subprocess.TimeoutExpired as exc:
            raise BlobStoreError(
                f"timed out reaching {self._label} ({what})", transient=True
            ) from exc
        except OSError as exc:
            raise BlobStoreError(
                f"cannot run rclone for {self._label} ({what}): {exc}",
                transient=True,
            ) from exc

    def _remote_path(self, relpath: str) -> str:
        return f"{self._remote}/{relpath}"

    @staticmethod
    def _failure_detail(result: subprocess.CompletedProcess[str]) -> str:
        detail = ((result.stderr or result.stdout) or "unknown rclone error").strip()
        return detail.splitlines()[0] if detail else "unknown rclone error"

    # -- BlobStore ----------------------------------------------------

    def has(self, sha256: str) -> bool:
        """Return whether the object for *sha256* is present in this store."""
        validate_sha256(sha256)
        result = self._run(
            "lsjson",
            "--files-only",
            self._remote_path(_object_relpath(sha256)),
            what="has",
        )
        if result.returncode != 0:
            return False
        try:
            entries = json.loads(result.stdout or "[]")
        except ValueError:
            return False
        return bool(isinstance(entries, list) and entries)

    def has_tombstone(self, sha256: str) -> bool:
        """Return whether a purge tombstone for *sha256* is in this store."""
        validate_sha256(sha256)
        try:
            result = self._run(
                "lsjson",
                "--files-only",
                self._remote_path(_tombstone_relpath(sha256)),
                what="has_tombstone",
            )
        except BlobStoreError:
            return False
        if result.returncode != 0:
            return False
        try:
            entries = json.loads(result.stdout or "[]")
        except ValueError:
            return False
        return bool(isinstance(entries, list) and entries)

    def put(
        self,
        sha256: str,
        src: Path,
        size_bytes: int,
        progress: ProgressCallback | None = None,
    ) -> None:
        """Upload the local file *src* under digest *sha256*.

        The source is hashed first and a digest mismatch is refused before
        any upload. Bytes stage to a ``.partial-<uuid>`` name, ``moveto``
        into place, then the remote size is verified (and the SHA-256 when
        the backend reports one via ``hashsum``).
        """
        validate_sha256(sha256)
        source = Path(src)
        if not source.is_file() or source.is_symlink():
            raise BlobStoreError(f"cannot store {source}: not a regular file")
        actual = self._hash_file(source, size_bytes, progress)
        if actual != sha256:
            raise BlobStoreError(
                f"cannot store {source}: bytes hash to {actual[:16]}…, "
                f"not {sha256[:16]}…"
            )
        relpath = _object_relpath(sha256)
        partial_relpath = (
            f"files/objects/sha256/{sha256[:2]}/.partial-{uuid.uuid4().hex}"
        )
        copyto = self._run(
            "copyto",
            str(source),
            self._remote_path(partial_relpath),
            what="upload",
        )
        if copyto.returncode != 0:
            raise BlobStoreError(
                f"could not upload attachment {sha256[:16]}… to {self._label}: "
                f"{self._failure_detail(copyto)}",
                transient=True,
            )
        try:
            moveto = self._run(
                "moveto",
                self._remote_path(partial_relpath),
                self._remote_path(relpath),
                what="upload finalize",
            )
        except BlobStoreError:
            with contextlib.suppress(BlobStoreError):
                self._run(
                    "deletefile",
                    self._remote_path(partial_relpath),
                    what="upload cleanup",
                )
            raise
        if moveto.returncode != 0:
            with contextlib.suppress(BlobStoreError):
                self._run(
                    "deletefile",
                    self._remote_path(partial_relpath),
                    what="upload cleanup",
                )
            raise BlobStoreError(
                f"could not upload attachment {sha256[:16]}… to {self._label}: "
                f"{self._failure_detail(moveto)}",
                transient=True,
            )
        self._verify_remote(sha256, size_bytes)
        if progress is not None:
            with contextlib.suppress(Exception):
                progress(size_bytes, size_bytes)

    def get(
        self,
        sha256: str,
        dest: Path,
        progress: ProgressCallback | None = None,
    ) -> None:
        """Download digest *sha256* into the local CAS rooted at *dest*.

        ``rclone cat`` streams into a CAS temp file while its SHA-256 is
        verified; on mismatch nothing is installed and a durable error is
        raised. Success installs through the local store replace rules:
        same filesystem, per-digest flock, mode 0444.
        """
        validate_sha256(sha256)
        cas = LocalAttachmentStore(root=Path(dest))
        cas.ensure_dirs()
        target = cas.object_path(sha256)
        if target.is_file() and cas.verify(sha256):
            return
        if not self.has(sha256):
            raise BlobStoreError(
                f"attachment {sha256[:16]}… is not in {self._label}",
                missing=True,
            )
        size = self._remote_size(sha256)
        self._stream_remote(sha256, cas, target, size, progress)

    def write_tombstone(self, sha256: str, payload: bytes) -> None:
        """Record a purge tombstone for *sha256* and remove its object.

        The tombstone JSON uploads to
        ``files/tombstones/sha256/<xx>/<sha>.json`` (staged through a
        ``.partial-<uuid>`` name like every other upload), then the object
        is deleted. A repeated write succeeds without changing bytes.
        """

        from sase.bead.attachments.tombstones import parse_tombstone_bytes

        validate_sha256(sha256)
        if not isinstance(payload, (bytes, bytearray)) or not bytes(payload):
            raise BlobStoreError("cannot write an empty purge tombstone")
        parsed = parse_tombstone_bytes(bytes(payload))
        if parsed["sha256"] != sha256:
            raise BlobStoreError(
                f"purge tombstone is for {parsed['sha256'][:16]}…, not {sha256[:16]}…"
            )
        with tempfile.NamedTemporaryFile(
            prefix="sase-attachment-tombstone-", suffix=".json"
        ) as handle:
            handle.write(bytes(payload))
            handle.flush()
            partial_relpath = (
                f"files/tombstones/sha256/{sha256[:2]}/.partial-{uuid.uuid4().hex}"
            )
            copyto = self._run(
                "copyto",
                handle.name,
                self._remote_path(partial_relpath),
                what="purge tombstone upload",
            )
            if copyto.returncode != 0:
                raise BlobStoreError(
                    f"could not upload purge tombstone for {sha256[:16]}… "
                    f"to {self._label}: {self._failure_detail(copyto)}",
                    transient=True,
                )
            try:
                moveto = self._run(
                    "moveto",
                    self._remote_path(partial_relpath),
                    self._remote_path(_tombstone_relpath(sha256)),
                    what="purge tombstone finalize",
                )
            except BlobStoreError:
                with contextlib.suppress(BlobStoreError):
                    self._run(
                        "deletefile",
                        self._remote_path(partial_relpath),
                        what="purge tombstone cleanup",
                    )
                raise
            if moveto.returncode != 0:
                with contextlib.suppress(BlobStoreError):
                    self._run(
                        "deletefile",
                        self._remote_path(partial_relpath),
                        what="purge tombstone cleanup",
                    )
                raise BlobStoreError(
                    f"could not upload purge tombstone for {sha256[:16]}… "
                    f"to {self._label}: {self._failure_detail(moveto)}",
                    transient=True,
                )
        self.delete(sha256)

    def delete(self, sha256: str) -> None:
        """Remove digest *sha256*; a no-op when it is already absent."""
        validate_sha256(sha256)
        result = self._run(
            "deletefile",
            self._remote_path(_object_relpath(sha256)),
            what="delete",
        )
        if result.returncode != 0:
            detail = self._failure_detail(result).lower()
            if (
                "not found" in detail
                or "no such" in detail
                or "directory not found" in detail
            ):
                return
            if not self.has(sha256):
                return
            raise BlobStoreError(
                f"could not delete attachment {sha256[:16]}… from {self._label}: "
                f"{self._failure_detail(result)}",
                transient=True,
            )

    # -- verification -------------------------------------------------

    def _remote_size(self, sha256: str) -> int | None:
        """Return the remote object size, or None when it cannot be read."""
        result = self._run(
            "lsjson",
            "--files-only",
            "--stat",
            self._remote_path(_object_relpath(sha256)),
            what="stat",
        )
        if result.returncode != 0:
            return None
        try:
            payload = json.loads(result.stdout or "{}")
        except ValueError:
            return None
        if isinstance(payload, dict):
            size = payload.get("Size")
        elif isinstance(payload, list) and payload and isinstance(payload[0], dict):
            size = payload[0].get("Size")
        else:
            return None
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            return None
        return size

    def _remote_sha256(self, sha256: str) -> str | None:
        """Return the backend-reported SHA-256, or None when unsupported."""
        result = self._run(
            "hashsum",
            "sha256",
            self._remote_path(_object_relpath(sha256)),
            what="hashsum",
        )
        if result.returncode != 0:
            return None
        first = (result.stdout or "").strip().split()
        if not first:
            return None
        candidate = first[0].lower()
        if len(candidate) != 64 or any(c not in "0123456789abcdef" for c in candidate):
            return None
        return candidate

    def _verify_remote(self, sha256: str, size_bytes: int) -> None:
        """Verify the just-uploaded object; a mismatch deletes it and raises."""
        remote_size = self._remote_size(sha256)
        if remote_size is not None and remote_size != size_bytes:
            with contextlib.suppress(BlobStoreError):
                self.delete(sha256)
            raise BlobStoreError(
                f"uploaded attachment {sha256[:16]}… to {self._label} with "
                f"the wrong size (want {size_bytes}, got {remote_size})"
            )
        remote_sha = self._remote_sha256(sha256)
        if remote_sha is not None and remote_sha != sha256:
            with contextlib.suppress(BlobStoreError):
                self.delete(sha256)
            raise BlobStoreError(
                f"uploaded attachment {sha256[:16]}… to {self._label} with "
                "a digest mismatch"
            )

    def _stream_remote(
        self,
        sha256: str,
        cas: LocalAttachmentStore,
        target: Path,
        size: int | None,
        progress: ProgressCallback | None,
    ) -> None:
        """Stream ``rclone cat`` into the CAS, digest-verified."""
        deadline = time.monotonic() + self._timeout
        binary = rclone_binary(self._binary)
        if binary is None:  # pragma: no cover - has() above already required it
            raise BlobStoreError(
                f"cannot reach {self._label}: the rclone binary "
                f"({self._binary!r}) is not installed."
            )
        tmp_fd, tmp_name = tempfile.mkstemp(dir=cas.tmp_dir, prefix="rclone-fetch-")
        try:
            os.fchmod(tmp_fd, 0o600)
            digest = hashlib.sha256()
            done = 0
            try:
                proc = subprocess.Popen(
                    [binary, "cat", self._remote_path(_object_relpath(sha256))],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=self._env(),
                )
            except OSError as exc:
                raise BlobStoreError(
                    f"cannot reach {self._label}: {exc}", transient=True
                ) from exc
            try:
                stdout = proc.stdout
                if stdout is None:  # pragma: no cover - defensive
                    raise BlobStoreError("rclone cat produced no output stream")
                while True:
                    chunk = stdout.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    if time.monotonic() > deadline:
                        proc.kill()
                        raise BlobStoreError(
                            f"timed out fetching {sha256[:16]}… from {self._label}",
                            transient=True,
                        )
                    os.write(tmp_fd, chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if progress is not None:
                        with contextlib.suppress(Exception):
                            progress(done, size)
                _, stderr = proc.communicate(timeout=30)
            except BlobStoreError:
                raise
            except Exception as exc:
                proc.kill()
                raise BlobStoreError(
                    f"could not fetch attachment {sha256[:16]}… from "
                    f"{self._label}: {exc}",
                    transient=True,
                ) from exc
            if proc.returncode != 0:
                detail = (stderr or b"").decode("utf-8", "replace").strip()
                raise BlobStoreError(
                    f"could not fetch attachment {sha256[:16]}… from "
                    f"{self._label}: {detail or 'unknown rclone error'}",
                    transient=True,
                )
            os.ftruncate(tmp_fd, done)
            os.fsync(tmp_fd)
        except BaseException:
            with contextlib.suppress(OSError):
                os.close(tmp_fd)
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise
        else:
            os.close(tmp_fd)
        if digest.hexdigest() != sha256:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise BlobStoreError(
                f"attachment {sha256[:16]}… from {self._label} failed "
                "digest verification"
            )
        with _digest_lock(cas, sha256):
            if target.is_file() and cas.verify(sha256):
                with contextlib.suppress(OSError):
                    os.unlink(tmp_name)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(tmp_name, target)
                os.chmod(target, 0o444)
                _fsync_dir(target.parent)

    @staticmethod
    def _hash_file(
        source: Path, size_bytes: int, progress: ProgressCallback | None
    ) -> str:
        """Return the SHA-256 of *source*, reporting read progress."""
        digest = hashlib.sha256()
        done = 0
        try:
            with open(source, "rb") as handle:
                while True:
                    chunk = handle.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    digest.update(chunk)
                    done += len(chunk)
                    if progress is not None:
                        with contextlib.suppress(Exception):
                            progress(done, size_bytes or None)
        except OSError as exc:
            raise BlobStoreError(f"cannot read {source}: {exc}") from exc
        return digest.hexdigest()


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


__all__ = [
    "RcloneAttachmentStore",
    "rclone_binary",
]
