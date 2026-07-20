"""Concurrency-safe bounded append primitives for durable log files."""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

DEFAULT_MAX_BYTES = 2 * 1024 * 1024


def max_bytes_from_env(name: str, default: int = DEFAULT_MAX_BYTES) -> int:
    """Return a non-negative byte limit from *name*, falling back to *default*."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def encode_jsonl_record(
    record: Mapping[str, Any],
    *,
    json_default: Callable[[Any], Any] | None = None,
    ensure_ascii: bool = True,
    sort_keys: bool = False,
) -> bytes:
    """Serialize one complete JSONL record before any filesystem lock is taken."""
    return (
        json.dumps(
            record,
            default=json_default,
            ensure_ascii=ensure_ascii,
            sort_keys=sort_keys,
        )
        + "\n"
    ).encode("utf-8")


def append_jsonl_record(
    path: Path,
    record: Mapping[str, Any],
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    json_default: Callable[[Any], Any] | None = None,
    ensure_ascii: bool = True,
    sort_keys: bool = False,
) -> None:
    """Serialize and append one JSONL record through the bounded log contract."""
    encoded = encode_jsonl_record(
        record,
        json_default=json_default,
        ensure_ascii=ensure_ascii,
        sort_keys=sort_keys,
    )
    with log_file_lock(path):
        append_encoded_line_locked(path, encoded, max_bytes=max_bytes)


@contextmanager
def log_file_lock(path: Path) -> Iterator[None]:
    """Hold the dedicated sibling lock that coordinates appends and rotation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def append_encoded_line_locked(
    path: Path,
    encoded: bytes,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> None:
    """Append *encoded* with one ``O_APPEND`` write while the sibling lock is held."""
    if not encoded.endswith(b"\n"):
        raise ValueError("durable log records must end with a newline")
    _rotate_if_needed_locked(path, incoming_bytes=len(encoded), max_bytes=max_bytes)
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
    try:
        written = os.write(fd, encoded)
    finally:
        os.close(fd)
    if written != len(encoded):
        raise OSError(
            f"short durable-log write for {path}: {written}/{len(encoded)} bytes"
        )


def _rotate_if_needed_locked(
    path: Path,
    *,
    incoming_bytes: int,
    max_bytes: int,
) -> None:
    if max_bytes <= 0:
        return
    try:
        current_bytes = path.stat().st_size
    except FileNotFoundError:
        return
    if current_bytes <= 0 or current_bytes + incoming_bytes <= max_bytes:
        return
    rotated = path.with_name(f"{path.name}.1")
    try:
        rotated.unlink()
    except FileNotFoundError:
        pass
    os.replace(path, rotated)


__all__ = [
    "DEFAULT_MAX_BYTES",
    "append_encoded_line_locked",
    "append_jsonl_record",
    "encode_jsonl_record",
    "log_file_lock",
    "max_bytes_from_env",
]
