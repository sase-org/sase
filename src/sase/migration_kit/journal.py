"""Durable migration journal helpers.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from typing import Any

from sase.core.time import local_now
from sase.migration_kit.core_contract import normalize_journal_record, plan_next_step
from sase.migration_kit.paths import run_dir, run_journal_path


def append_record(
    run_id: str,
    *,
    state: str,
    operation: str | None = None,
    message: str | None = None,
    source_digests: Mapping[str, str] | None = None,
    refusal: Mapping[str, Any] | None = None,
    step_id: str | None = None,
) -> dict[str, Any]:
    """Append one normalized record to the run journal."""
    record = normalize_journal_record(
        {
            "schema_version": 1,
            "run_id": run_id,
            "step_id": step_id,
            "operation": operation,
            "recorded_at": local_now().isoformat(),
            "state": state,
            "source_digests": dict(source_digests or {}),
            "message": message,
            "refusal": dict(refusal) if refusal is not None else None,
        }
    )
    path = run_journal_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_dir(path.parent)
    return record


def read_records(run_id: str) -> list[dict[str, Any]]:
    """Read normalized journal records for *run_id*."""
    path = run_journal_path(run_id)
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected a JSON object")
        records.append(value)
    return records


def current_resume_plan(
    manifest: Mapping[str, Any],
    *,
    records: list[dict[str, Any]] | None = None,
    observed_source_digests: Mapping[str, str],
) -> dict[str, Any]:
    """Return the Rust journal replay decision for *manifest*."""
    run_id = str(manifest.get("run_id") or manifest["manifest_id"])
    return plan_next_step(
        manifest,
        read_records(run_id) if records is None else records,
        observed_source_digests,
    )


def ensure_run_dir(run_id: str) -> None:
    """Create the run directory used by manifest, journal, and receipt."""
    run_dir(run_id).mkdir(parents=True, exist_ok=True)


def _fsync_dir(path: os.PathLike[str] | str) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


__all__ = [
    "append_record",
    "current_resume_plan",
    "ensure_run_dir",
    "read_records",
]
