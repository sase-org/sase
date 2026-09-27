"""Structured step channel for finalizer operations (epic plan §3.3 contract C3).

A finalizer subprocess learns its steps file through the
``SASE_FINALIZER_STEPS_FILE`` environment variable, which holds the absolute
path of ``attempt-<N>.<op>.steps.jsonl``. :func:`emit_step` appends one JSON
record per line; it does nothing when the variable is unset and never raises,
so producers stay best-effort observability that cannot change a verdict.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STEPS_ENV_VAR = "SASE_FINALIZER_STEPS_FILE"
STEPS_FILE_CEILING_BYTES = 64 * 1024
STEPS_SCHEMA_VERSION = 1
STEP_TEXT_CAP = 120
STEP_DETAIL_CAP = 500

VALID_STEP_STATES = frozenset({"start", "ok", "warn", "fail"})


def steps_file_for(prefix: str) -> str:
    """Return the steps filename for an op artifact *prefix*."""
    return f"{prefix}.steps.jsonl"


def live_file_for(prefix: str) -> str:
    """Return the live-sink filename for an op artifact *prefix*."""
    return f"{prefix}.live"


def emit_step(
    step: str,
    state: str = "start",
    detail: str | None = None,
) -> None:
    """Append one step record to ``SASE_FINALIZER_STEPS_FILE``; never raises.

    Does nothing when the variable is unset. ``step`` is capped at 120
    characters and ``detail`` at 500 characters. Writers stop silently once
    the file reaches 64 KiB.
    """
    path = os.environ.get(STEPS_ENV_VAR, "").strip()
    if not path:
        return
    if state not in VALID_STEP_STATES:
        logger.debug("dropping step with unknown state %r", state)
        return
    try:
        text = str(step).strip()
        if not text:
            return
        record: dict[str, Any] = {
            "v": STEPS_SCHEMA_VERSION,
            "t": time.time(),
            "step": text[:STEP_TEXT_CAP],
            "state": state,
        }
        if detail is not None:
            detail_text = str(detail).strip()
            if detail_text:
                record["detail"] = detail_text[:STEP_DETAIL_CAP]
        line = json.dumps(record, ensure_ascii=False) + "\n"
        encoded = line.encode("utf-8")
        steps_path = Path(path)
        try:
            existing = steps_path.stat().st_size if steps_path.is_file() else 0
        except OSError:
            existing = 0
        if existing + len(encoded) > STEPS_FILE_CEILING_BYTES:
            return
        steps_path.parent.mkdir(parents=True, exist_ok=True)
        with open(steps_path, "a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
    except Exception:  # noqa: BLE001 - the step channel is best-effort
        logger.debug("finalizer step write failed", exc_info=True)


def _read_steps_tail(
    steps_path: str | Path,
    *,
    max_bytes: int = STEPS_FILE_CEILING_BYTES,
) -> list[dict[str, Any]]:
    """Return parsed step records from the tail (≤ *max_bytes*) of *steps_path*.

    Blank lines and malformed rows are skipped, mirroring the tolerant
    journal reader. Never raises: errors yield an empty list.
    """
    try:
        path = Path(steps_path)
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes), os.SEEK_SET)
            raw = handle.read()
        records: list[dict[str, Any]] = []
        for line in raw.decode("utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(payload, dict):
                records.append(payload)
        return records
    except Exception:  # noqa: BLE001 - step reads are best-effort
        logger.debug("finalizer steps tail read failed", exc_info=True)
        return []


def _latest_step_summary(steps_path: str | Path) -> tuple[str | None, int]:
    """Return ``(latest step text, warn count)`` from a steps file.

    The warn count covers every ``warn``-state record in the tail, matching
    the tracker's warning tally. Returns ``(None, 0)`` when no step record
    is present.
    """
    latest: str | None = None
    warnings = 0
    for record in _read_steps_tail(steps_path):
        step = record.get("step")
        if isinstance(step, str) and step.strip():
            latest = step.strip()
        if record.get("state") == "warn":
            warnings += 1
    return latest, warnings


def make_progress_tick(
    tracker: Any,
    instance_id: str,
    steps_path: str | Path,
) -> Callable[[], None]:
    """Build a ``progress_tick`` callback that refreshes tracker step state.

    The callback reads the latest step from the op's steps file and records
    it through ``tracker.note_step`` (which applies the C5 2 s throttle).
    It never raises.
    """

    def _tick() -> None:
        try:
            latest, warnings = _latest_step_summary(steps_path)
            if latest is None:
                return
            tracker.note_step(instance_id, latest, warnings=warnings)
        except Exception:  # noqa: BLE001 - progress ticks are best-effort
            logger.debug("finalizer progress tick failed", exc_info=True)

    return _tick


__all__ = [
    "STEPS_ENV_VAR",
    "STEPS_FILE_CEILING_BYTES",
    "STEPS_SCHEMA_VERSION",
    "STEP_DETAIL_CAP",
    "STEP_TEXT_CAP",
    "VALID_STEP_STATES",
    "emit_step",
    "live_file_for",
    "make_progress_tick",
    "steps_file_for",
]
