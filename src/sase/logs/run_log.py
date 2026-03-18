"""Structured JSONL run and event logging.

Provides ``log_agent_run()`` and ``log_event()`` which append JSON lines to
``~/.sase/logs/runs.jsonl`` and ``~/.sase/logs/events.jsonl`` respectively.
Uses atomic append with file locking (same pattern as the notifications store).
"""

import fcntl
import json
import os
from datetime import datetime
from typing import Any

from sase.sase_utils import EASTERN_TZ

LOGS_DIR = os.path.expanduser("~/.sase/logs")
RUNS_FILE = os.path.join(LOGS_DIR, "runs.jsonl")
EVENTS_FILE = os.path.join(LOGS_DIR, "events.jsonl")


def _append_jsonl(path: str, record: dict[str, Any]) -> None:
    """Append a JSON record as a single line with exclusive file locking."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(json.dumps(record, default=str) + "\n")
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


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
    now = datetime.now(EASTERN_TZ)
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
    _append_jsonl(RUNS_FILE, record)


def log_event(
    *,
    event: str,
    **kwargs: Any,
) -> None:
    """Append a lightweight event record to ``~/.sase/logs/events.jsonl``.

    Common events: ``hook_completed``, ``commit_created``, ``amend_created``,
    ``changespec_reverted``, ``changespec_restored``.
    """
    now = datetime.now(EASTERN_TZ)
    record: dict[str, Any] = {
        "timestamp": now.strftime("%y%m%d_%H%M%S"),
        "event": event,
        **kwargs,
    }
    _append_jsonl(EVENTS_FILE, record)
