"""Durable JSON, hashing, locking, and resource-copy primitives."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sase.core.atomic_temp import reap_stale_atomic_temps
from sase.notification_gates.models import GateError, GateResource
from sase.notification_gates.paths import open_regular_nofollow, owned_resource_path


def canonical_json_bytes(value: object) -> bytes:
    """Serialize a JSON value canonically for hashing."""
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise GateError(
            "invalid_json", "request", f"value is not valid JSON: {exc}"
        ) from exc


def sha256_bytes(value: bytes) -> str:
    """Return the lowercase SHA-256 digest for *value*."""
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    """Hash a regular file without following its final symlink."""
    fd = open_regular_nofollow(path)
    digest = hashlib.sha256()
    try:
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            digest.update(block)
    finally:
        os.close(fd)
    return digest.hexdigest()


def request_sha256(envelope: Mapping[str, Any]) -> str:
    """Hash an envelope while excluding its self-referential request digest."""
    data = dict(envelope)
    hashes = dict(data.get("hashes") or {})
    hashes.pop("request", None)
    data["hashes"] = hashes
    return sha256_bytes(canonical_json_bytes(data))


def atomic_write_json(path: Path, value: object, *, exclusive: bool = False) -> None:
    """Atomically write and fsync a JSON value and its parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive and path.exists():
        raise FileExistsError(path)
    reap_stale_atomic_temps(path)
    fd, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical_json_bytes(value))
            stream.write(b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            os.link(temporary_path, path)
            temporary_path.unlink()
        else:
            os.replace(temporary_path, path)
        fsync_dir(path.parent)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def read_json_object(path: Path) -> dict[str, Any]:
    """Read a required JSON object from *path*."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GateError(
            "missing_file", str(path), f"missing gate file: {path}"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError("invalid_json", str(path), f"invalid gate JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise GateError("invalid_json", str(path), "gate JSON must be an object")
    return value


def materialize_resource(bundle_root: Path, resource: GateResource) -> Path:
    """Create one resource without following source or destination symlinks."""
    target = owned_resource_path(bundle_root, resource.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    _reject_existing_symlink(target)
    if target.exists():
        raise GateError("resource_exists", resource.path, "resource already exists")
    if resource.content is not None:
        content = resource.content.encode("utf-8")
    else:
        assert resource.source is not None
        content = _read_source(resource.source)
    mode = 0o700 if resource.executable else 0o600
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.fchmod(fd, mode)
    finally:
        os.close(fd)
    fsync_dir(target.parent)
    return target


def _read_source(path: Path) -> bytes:
    fd = open_regular_nofollow(path)
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _reject_existing_symlink(path: Path) -> None:
    current = path.parent
    while current != current.parent:
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise GateError(
                    "unsafe_path",
                    str(current),
                    "resource parent is not a real directory",
                )
            break
        current = current.parent
    if path.is_symlink():
        raise GateError("unsafe_path", str(path), "resource target is a symlink")


def fsync_dir(path: Path) -> None:
    """Best-effort fsync of a directory after an atomic namespace mutation."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Hold an exclusive advisory lock for the duration of the context."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def verify_mode(path: Path, *, executable: bool) -> None:
    """Reject non-regular, symlinked, or unexpectedly executable resources."""
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise GateError(
            "missing_resource", str(path), f"cannot stat resource: {exc}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise GateError("unsafe_resource", str(path), "resource must be a regular file")
    has_execute = bool(metadata.st_mode & 0o111)
    if executable != has_execute:
        expectation = "executable" if executable else "non-executable"
        raise GateError(
            "resource_mode_mismatch", str(path), f"resource must remain {expectation}"
        )


__all__ = [
    "atomic_write_json",
    "canonical_json_bytes",
    "file_lock",
    "fsync_dir",
    "materialize_resource",
    "read_json_object",
    "request_sha256",
    "sha256_bytes",
    "sha256_file",
    "verify_mode",
]
