"""Shared public helpers for the private monitor proc adapter modules."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.procs.models import Proc, ProcObservedSettlementOutcome

from .output import OutputCapture


def capture_from_log(path: str | Path) -> OutputCapture:
    """Rebuild a bounded output view from the authoritative log file."""
    capture = OutputCapture()
    if not path:
        return capture
    output_path = Path(path)
    for candidate in (output_path.with_name(f"{output_path.name}.1"), output_path):
        try:
            data = candidate.read_bytes()
        except OSError:
            continue
        if data:
            capture.append_bytes(data)
    return capture


def elapsed_seconds(
    proc: Proc | None,
    *,
    ended_at: str | None = None,
) -> float | None:
    if proc is None:
        return None
    start = _parse_timestamp(proc.started_at or proc.created_at)
    end = _parse_timestamp(ended_at or proc.finished_at or proc.settled_at)
    if start is None:
        return None
    if end is None:
        end = datetime.now(UTC)
    return max(0.0, (end - start).total_seconds())


def command_ended_at(
    state: dict[str, Any], *, meta: dict[str, Any], proc: Proc | None
) -> str:
    """Return the frozen command-end time so result identity stays stable."""
    outcome = (
        ProcObservedSettlementOutcome.from_dict(proc.settlement_outcome)
        if proc is not None
        else None
    )
    for candidate in (
        state.get("command_ended_at"),
        None if outcome is None else outcome.command_ended_at,
        meta.get("stopped_at"),
        None if proc is None else proc.settling_started_at,
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return utc_now_iso()


def _parse_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def read_meta(artifacts_dir: str) -> dict[str, Any]:
    path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
