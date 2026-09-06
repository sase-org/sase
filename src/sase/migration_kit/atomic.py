"""Atomic write and archive helpers for the temporary migration kit.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

import os
from pathlib import Path
import secrets
import shutil

from sase.migration_kit.core_contract import tree_digest


class MigrationAtomicError(RuntimeError):
    """Raised when a migration filesystem operation cannot be made atomic."""


def atomic_write_text(path: Path, text: str) -> None:
    """Write *text* via same-directory temp file, ``os.replace``, and fsync."""
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Write *payload* via same-directory temp file, ``os.replace``, and fsync."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path(path)
    try:
        with tmp.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        _replace_same_filesystem(tmp, path)
        _fsync_dir(path.parent)
    finally:
        _remove_path(tmp)


def copy_path_atomic(source: Path, destination: Path) -> str:
    """Copy *source* to *destination* atomically and return the copied digest.

    The copy is staged in ``destination.parent`` so the final ``os.replace`` is
    same-filesystem. The source and staged tree digests must match before the
    staged copy is promoted.
    """
    if not (source.exists() or source.is_symlink()):
        raise MigrationAtomicError(f"archive source does not exist: {source}")
    if destination.exists() or destination.is_symlink():
        raise MigrationAtomicError(f"archive destination already exists: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path(destination)
    source_digest = str(tree_digest(source)["digest"])
    try:
        _copy_path(source, tmp)
        copied_digest = str(tree_digest(tmp)["digest"])
        if copied_digest != source_digest:
            raise MigrationAtomicError(
                f"archive checksum mismatch for {source}: "
                f"expected {source_digest}, got {copied_digest}"
            )
        _replace_same_filesystem(tmp, destination)
        _fsync_dir(destination.parent)
    finally:
        _remove_path(tmp)

    return source_digest


def remove_path(path: Path) -> None:
    """Remove a file, symlink, or directory tree without following symlinks."""
    if path.is_symlink() or path.is_file():
        path.unlink()
        _fsync_dir(path.parent)
        return
    if path.is_dir():
        shutil.rmtree(path)
        _fsync_dir(path.parent)


def _copy_path(source: Path, destination: Path) -> None:
    if source.is_symlink():
        os.symlink(os.readlink(source), destination)
    elif source.is_dir():
        shutil.copytree(source, destination, symlinks=True)
    elif source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    else:
        raise MigrationAtomicError(f"unsupported archive source kind: {source}")


def _replace_same_filesystem(source: Path, destination: Path) -> None:
    try:
        if (
            source.stat(follow_symlinks=False).st_dev
            != destination.parent.stat().st_dev
        ):
            raise MigrationAtomicError(
                f"cross-device migration write refused: {source} -> {destination}"
            )
    except FileNotFoundError as exc:
        raise MigrationAtomicError(str(exc)) from exc
    os.replace(source, destination)


def _tmp_path(path: Path) -> Path:
    return path.parent / f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(4)}"


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


__all__ = [
    "MigrationAtomicError",
    "atomic_write_bytes",
    "atomic_write_text",
    "copy_path_atomic",
    "remove_path",
]
