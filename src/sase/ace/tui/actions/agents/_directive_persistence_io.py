"""Shared disk helpers for worker-safe agent directive persistence."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path


def read_json_object(path: Path) -> dict[str, object]:
    """Read a JSON object from *path*, returning ``{}`` when unavailable."""
    try:
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def write_json_file(path: Path, data: Mapping[str, object]) -> None:
    """Atomically write *data* as JSON to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=f".{os.getpid()}.tmp",
        dir=path.parent,
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dict(data), f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise


@contextmanager
def agent_directive_lock(artifacts_path: Path) -> Iterator[None]:
    """Hold the per-agent directive lock for *artifacts_path*."""
    from sase.core.agent_directive_lock import (
        agent_directive_lock as acquire_lock,
    )

    with acquire_lock(artifacts_path):
        yield


__all__ = [
    "agent_directive_lock",
    "read_json_object",
    "write_json_file",
]
