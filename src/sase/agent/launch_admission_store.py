"""On-disk journal, sidecar, and unit receipts for launch admission."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.core.agent_launch_wire import (
    LAUNCH_ADMISSION_JOURNAL_SCHEMA_VERSION,
    LaunchPlanWire,
)
from sase.monitor.transaction import write_json_marker_atomic

ADMISSION_DIRNAME = "launch_admission"
JOURNAL_FILENAME = "journal.jsonl"
SIDECAR_FILENAME = "sidecar.json"
STARTED_FILENAME = "started.json"
RECEIPT_FILENAME = "receipt.json"
LOCK_FILENAME = "lock"
UNITS_DIRNAME = "units"
COORDINATOR_LOG_FILENAME = "coordinator.log"
START_ACK_TIMEOUT_SECONDS = 20.0
STOP_TERM_SECONDS = 5.0
STOP_KILL_SECONDS = 1.0
POLL_SECONDS = 0.05
COORDINATOR_ENV = "SASE_LAUNCH_ADMISSION_COORDINATOR"


def admission_dir(response_dir: Path) -> Path:
    return response_dir / ADMISSION_DIRNAME


def write_sidecar(root: Path, data: Mapping[str, Any], plan: LaunchPlanWire) -> None:
    write_json_marker_atomic(
        root / SIDECAR_FILENAME,
        {
            "schema_version": LAUNCH_ADMISSION_JOURNAL_SCHEMA_VERSION,
            "request_id": str(data.get("request_id") or ""),
            "plan_digest": plan.content_digest,
            "plan_schema_version": plan.schema_version,
            "pid": os.getpid(),
            "updated_at_unix": time.time(),
        },
    )


def append_journal(root: Path, entry: dict[str, Any]) -> None:
    path = root / JOURNAL_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(entry, sort_keys=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_journal(root: Path) -> list[dict[str, Any]]:
    path = root / JOURNAL_FILENAME
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            entries.append(parsed)
    return entries


def next_journal_seq(root: Path) -> int:
    seq = 1
    for entry in read_journal(root):
        try:
            seq = max(seq, int(entry.get("seq") or 0) + 1)
        except (TypeError, ValueError):
            continue
    return seq


def write_unit_receipt(
    root: Path,
    *,
    logical_id: str,
    fingerprint: str,
    identity: str,
) -> None:
    units_dir = root / UNITS_DIRNAME
    write_json_marker_atomic(
        units_dir / f"{logical_id}.json",
        {
            "logical_id": logical_id,
            "fingerprint": fingerprint,
            "identity": identity,
        },
    )


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
