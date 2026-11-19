"""Shared atomic JSON marker writes for launch admission and monitor coordination."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def _atomic_tmp_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")


def write_text_atomic(path: Path, text: str) -> None:
    """Write *text* to *path* without exposing partial content.

    A temp file is written next to *path*, fsynced, then ``os.replace``d into
    place. Every failure raises (after removing the temp file) so callers can
    count and log it instead of dropping it silently.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _atomic_tmp_path(path)
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def write_json_value_atomic(marker_path: Path, value: object) -> None:
    """Write any JSON value to *marker_path* without exposing partial content.

    A temp file is written next to *marker_path*, fsynced, then ``os.replace``d
    into place. Every failure raises (after removing the temp file) so
    callers can count and log it instead of dropping it silently.
    """
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _atomic_tmp_path(marker_path)
    try:
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, marker_path)
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def write_json_marker_atomic(marker_path: Path, payload: Mapping[str, Any]) -> None:
    """Write *payload* as JSON to *marker_path* without exposing partial content.

    A temp file is written next to *marker_path*, fsynced, then ``os.replace``d
    into place for readers of monitor, launch-admission, staged-handoff, and
    condition-workspace markers.
    """
    write_json_value_atomic(marker_path, dict(payload))


__all__ = ["write_json_marker_atomic", "write_json_value_atomic", "write_text_atomic"]
