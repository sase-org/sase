"""Artifact helpers for host-owned finalizer execution."""

from __future__ import annotations

from collections.abc import Mapping
import fcntl
import json
import os
from pathlib import Path
from typing import Any

from sase.memory.locks import locked_file


FINALIZER_RESULT_FILENAME = "finalizer_result.json"
FINALIZER_RUNS_DIRNAME = "finalizers"


def finalizer_runs_dir(artifacts_dir: str | None) -> Path | None:
    """Return the per-instance finalizer artifact directory, if available."""

    if not artifacts_dir:
        return None
    root = Path(artifacts_dir).expanduser().resolve(strict=False)
    path = root / FINALIZER_RUNS_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def instance_artifact_dir(
    artifacts_dir: str | None,
    instance_id: str,
) -> Path | None:
    """Return the directory for one finalizer instance's attempt artifacts."""

    root = finalizer_runs_dir(artifacts_dir)
    if root is None:
        return None
    path = root / instance_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_finalizer_result(
    artifacts_dir: str | None,
    payload: Mapping[str, Any],
) -> Path | None:
    """Atomically publish the aggregate finalizer result artifact."""

    if not artifacts_dir:
        return None
    root = Path(artifacts_dir).expanduser().resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    path = root / FINALIZER_RESULT_FILENAME
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
        write_json_atomic(path, payload)
    return path


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    """Write *payload* as deterministic JSON using same-directory replace."""

    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def write_text_artifact(path: Path, text: str) -> None:
    """Write bounded stdout/stderr text with the same atomic convention."""

    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8", errors="replace") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


__all__ = [
    "FINALIZER_RESULT_FILENAME",
    "FINALIZER_RUNS_DIRNAME",
    "finalizer_runs_dir",
    "instance_artifact_dir",
    "write_finalizer_result",
    "write_json_atomic",
    "write_text_artifact",
]
