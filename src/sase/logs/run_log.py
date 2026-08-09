"""Structured JSONL run and event logging.

Provides ``log_agent_run()`` and ``log_event()`` which append JSON lines to
``~/.sase/logs/runs.jsonl`` and ``~/.sase/logs/events.jsonl`` respectively.
Uses one-write atomic append with sibling locking and bounded rotation.
"""

import json
import os
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.core.paths import sase_subdir
from sase.core.time import get_timezone
from sase.logs._bounded import (
    DEFAULT_MAX_BYTES,
    append_jsonl_record,
    max_bytes_from_env,
)

REVIVE_EVENTS: frozenset[str] = frozenset(
    {"agent_revive_started", "agent_revived", "agent_revive_failed"}
)

LOGS_DIR: str | None = None
RUNS_FILE: str | None = None
EVENTS_FILE: str | None = None
ENV_MAX_BYTES = "SASE_RUN_LOG_MAX_BYTES"


def _logs_dir() -> str:
    return LOGS_DIR or str(sase_subdir("logs"))


def _runs_file() -> str:
    return RUNS_FILE or os.path.join(_logs_dir(), "runs.jsonl")


def _events_file() -> str:
    return EVENTS_FILE or os.path.join(_logs_dir(), "events.jsonl")


def runs_log_path() -> Path:
    """Canonical path of the agent-runs JSONL log."""
    return Path(_runs_file())


def events_log_path() -> Path:
    """Canonical path of the events JSONL log."""
    return Path(_events_file())


def _append_jsonl(path: str, record: dict[str, Any]) -> None:
    """Append a JSON record with bounded, concurrency-safe rotation."""
    append_jsonl_record(
        Path(path),
        record,
        max_bytes=max_bytes_from_env(ENV_MAX_BYTES, DEFAULT_MAX_BYTES),
        json_default=str,
    )


def log_agent_run(
    *,
    workflow: str,
    project: str,
    branch_or_workspace: str,
    workspace_num: int,
    model: str | None = None,
    llm_provider: str | None = None,
    duration_seconds: float,
    status: str,
    artifacts_dir: str | None = None,
    chat_file: str | None = None,
    prompt_preview: str | None = None,
) -> None:
    """Append an agent run record to ``~/.sase/logs/runs.jsonl``."""
    now = datetime.now(get_timezone())
    record: dict[str, Any] = {
        "timestamp": now.strftime("%y%m%d_%H%M%S"),
        "event": "agent_run",
        "workflow": workflow,
        "project": project,
        "branch_or_workspace": branch_or_workspace,
        "workspace_num": workspace_num,
        "duration_seconds": round(duration_seconds, 1),
        "status": status,
    }
    if model:
        record["model"] = model
    if llm_provider:
        record["llm_provider"] = llm_provider
    if artifacts_dir:
        record["artifacts_dir"] = artifacts_dir
    if chat_file:
        record["chat_file"] = chat_file
    if prompt_preview:
        record["prompt_preview"] = prompt_preview[:100]
    _append_jsonl(_runs_file(), record)


def log_event(
    *,
    event: str,
    **kwargs: Any,
) -> None:
    """Append a lightweight event record to ``~/.sase/logs/events.jsonl``.

    Common events: ``hook_completed``, ``commit_created``, ``amend_created``,
    ``patch_reverted``, ``patch_restored``.
    """
    now = datetime.now(get_timezone())
    record: dict[str, Any] = {
        "timestamp": now.strftime("%y%m%d_%H%M%S"),
        "event": event,
        **kwargs,
    }
    _append_jsonl(_events_file(), record)


def _parse_event_timestamp(record: dict[str, Any]) -> datetime | None:
    """Parse the ``%y%m%d_%H%M%S`` timestamp on an event record.

    Event timestamps are written in the configured timezone (see
    :func:`log_event`), so the parsed value is made aware in that same zone.
    This keeps ``since`` / ``until`` comparisons — whose bounds come from
    ``parse_daterange`` as aware configured-tz datetimes — from raising
    ``TypeError`` on a naive/aware mismatch.
    """
    raw = record.get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.strptime(raw, "%y%m%d_%H%M%S").replace(tzinfo=get_timezone())
    except ValueError:
        return None


def iter_revive_events(
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    outcome: str | None = None,
    events_file: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield agent-revive records from ``events.jsonl`` in reverse-chronological order.

    Records are read from the end of the file so the most recent attempt
    is yielded first. Filters:

    - ``since`` / ``until``: inclusive bounds on the record timestamp
      (parsed from the ``timestamp`` field, naive local time matching how
      ``log_event`` writes them).
    - ``outcome``: ``"success"`` or ``"failure"``.

    Malformed JSON lines and records missing required fields are skipped.
    """
    path = events_file if events_file is not None else _events_file()
    if not os.path.exists(path):
        return
    try:
        with open(path) as f:
            lines = f.readlines()
    except OSError:
        return
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if record.get("event") not in REVIVE_EVENTS:
            continue
        if outcome is not None:
            record_outcome = record.get("outcome")
            if record_outcome is None:
                if record["event"] == "agent_revived":
                    record_outcome = "success"
                elif record["event"] == "agent_revive_failed":
                    record_outcome = "failure"
            if record_outcome != outcome:
                continue
        ts = _parse_event_timestamp(record)
        if since is not None and (ts is None or ts < since):
            continue
        if until is not None and (ts is None or ts > until):
            continue
        yield record
