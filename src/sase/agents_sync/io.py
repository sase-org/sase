"""Strict validation, stable JSON, and atomic files for agent synchronization."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile


class AgentsSyncFormatError(ValueError):
    """Raised when untrusted sidecar data violates a persisted contract."""


def canonical_json_bytes(value: object) -> bytes:
    """Return the canonical UTF-8 JSON representation used for digests."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def atomic_write_json(path: Path, value: object) -> None:
    payload = (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    atomic_write_bytes(path, payload)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Write bytes through a same-directory temporary file and ``os.replace``."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    replaced = False
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temp_path = Path(temp_name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        replaced = True
    finally:
        if temp_path is not None and not replaced:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


__all__ = [
    "AgentsSyncFormatError",
    "atomic_write_bytes",
    "atomic_write_json",
    "canonical_json_bytes",
]
