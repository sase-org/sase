"""Small atomic JSON writer shared by history stores."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path


def atomic_write_json(path: Path, data: Mapping[str, object]) -> bool:
    """Replace *path* with JSON without exposing a partially written file.

    Returns ``False`` on filesystem errors, matching the history stores'
    best-effort persistence behavior. Serialization errors still propagate.
    """
    fd: int | None = None
    temporary_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True
        )
        temporary_path = Path(temporary_name)
        handle = os.fdopen(fd, "w", encoding="utf-8")
        fd = None
        with handle:
            json.dump(data, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        return True
    except OSError:
        return False
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass
