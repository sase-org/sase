"""Shared atomic JSON marker writes for launch admission and monitor coordination."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


def write_json_marker_atomic(marker_path: Path, payload: dict[str, object]) -> None:
    """Write *payload* as JSON to *marker_path* without exposing partial content.

    A temp file is written next to *marker_path*, fsynced, then ``os.replace``d
    into place for readers of monitor, launch-admission, and condition-workspace
    markers.
    """
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = marker_path.with_name(
        f".{marker_path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    try:
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, marker_path)
    except OSError:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


__all__ = ["write_json_marker_atomic"]
