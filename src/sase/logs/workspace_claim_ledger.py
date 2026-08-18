"""Durable ledger of RUNNING-field mutations (workspace claim/hold/transfer/release).

Every claim, hold, transfer, and release attempt against a ProjectSpec's
RUNNING field is appended, while the ProjectSpec lock is still held, to
``~/.sase/logs/workspace_claims.jsonl``. A record captures not just the
attempted mutation but the full set of claim rows for the affected
workspace number immediately before and immediately after the write, so a
vanished or duplicated claim row is attributable after the fact from the
ledger alone.

Writing the ledger must never fail a claim: :func:`record_running_field_mutation`
swallows and debug-logs every exception.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.core.paths import sase_subdir
from sase.core.time import get_timezone
from sase.logs._bounded import (
    DEFAULT_MAX_BYTES,
    append_jsonl_record,
    max_bytes_from_env,
)

if TYPE_CHECKING:
    from sase.running_field._model import WorkspaceClaim

log = logging.getLogger(__name__)

# Module-level path override for tests (same pattern as ``run_log``).
LOGS_DIR: str | None = None
LEDGER_FILE: str | None = None
ENV_MAX_BYTES = "SASE_WORKSPACE_CLAIM_LEDGER_MAX_BYTES"


def _logs_dir() -> str:
    return LOGS_DIR or str(sase_subdir("logs"))


def _ledger_file() -> str:
    return LEDGER_FILE or os.path.join(_logs_dir(), "workspace_claims.jsonl")


def ledger_path() -> Path:
    """Canonical path of the workspace-claim mutation ledger."""
    return Path(_ledger_file())


def _claims_for_workspace(
    content: str | None, workspace_num: int | None
) -> list[dict[str, Any]]:
    if content is None or workspace_num is None:
        return []
    from sase.core.agent_launch_claims import list_workspace_claims_from_content

    claims: list[WorkspaceClaim] = list_workspace_claims_from_content(content)
    return [asdict(claim) for claim in claims if claim.workspace_num == workspace_num]


def record_running_field_mutation(
    *,
    operation: str,
    project_file: str,
    workspace_num: int | None,
    success: bool,
    before_content: str,
    after_content: str | None = None,
    workflow: str | None = None,
    cl_name: str | None = None,
    artifacts_timestamp: str | None = None,
    claim_pid: int | None = None,
    error: str | None = None,
    caller_tag: str | None = None,
) -> None:
    """Durably record one RUNNING-field mutation attempt.

    Args:
        operation: One of ``"claim"``, ``"claim_next_axe"``, ``"transfer"``,
            ``"hold"``, ``"release"`` — the ``_operations.py`` helper that
            produced this record.
        project_file: Path to the ProjectSpec file being mutated.
        workspace_num: The affected workspace number, when known. ``None``
            for a ``claim_next_axe`` rejection where no workspace was ever
            selected.
        success: Whether the mutation (or attempted mutation) succeeded.
        before_content: ProjectSpec content as read under the lock, before
            any write.
        after_content: ProjectSpec content after a successful write. Omit
            (or pass ``before_content`` again) when nothing changed.
        workflow: Workflow label of the claim involved.
        cl_name: Patch name of the claim involved.
        artifacts_timestamp: Artifacts timestamp of the claim involved.
        claim_pid: PID named by the claim row itself (the claiming PID for
            claim/hold, the destination PID for transfer) — distinct from
            the acting process recorded in ``actor_pid``/``actor_ppid``,
            since a parent process commonly claims or transfers a slot on
            behalf of a child it is about to spawn.
        error: Human-readable rejection reason on failure.
        caller_tag: Short tag naming the code path that produced this
            record (e.g. ``"launcher-preclaim"``, ``"deferred-claim"``,
            ``"retry-transfer"``, ``"agent-finalize"``, ``"stale-cleanup"``,
            ``"dismiss"``).

    Never raises: any exception is swallowed and logged at debug level so a
    ledger write can never fail the mutation it is recording.
    """
    try:
        _write_record(
            operation=operation,
            project_file=project_file,
            workspace_num=workspace_num,
            success=success,
            before_content=before_content,
            after_content=after_content
            if after_content is not None
            else before_content,
            workflow=workflow,
            cl_name=cl_name,
            artifacts_timestamp=artifacts_timestamp,
            claim_pid=claim_pid,
            error=error,
            caller_tag=caller_tag,
        )
    except Exception:
        log.debug("Failed to write workspace-claim ledger record", exc_info=True)


def _write_record(
    *,
    operation: str,
    project_file: str,
    workspace_num: int | None,
    success: bool,
    before_content: str,
    after_content: str,
    workflow: str | None,
    cl_name: str | None,
    artifacts_timestamp: str | None,
    claim_pid: int | None,
    error: str | None,
    caller_tag: str | None,
) -> None:
    now = datetime.now(get_timezone())
    record: dict[str, Any] = {
        "timestamp": now.strftime("%y%m%d_%H%M%S"),
        "operation": operation,
        "project_file": project_file,
        "workspace_num": workspace_num,
        "workflow": workflow,
        "cl_name": cl_name,
        "artifacts_timestamp": artifacts_timestamp,
        "claim_pid": claim_pid,
        "actor_pid": os.getpid(),
        "actor_ppid": os.getppid(),
        "success": success,
        "error": error,
        "caller_tag": caller_tag,
        "before": _claims_for_workspace(before_content, workspace_num),
        "after": _claims_for_workspace(after_content, workspace_num),
    }
    append_jsonl_record(
        ledger_path(),
        record,
        max_bytes=max_bytes_from_env(ENV_MAX_BYTES, DEFAULT_MAX_BYTES),
        json_default=str,
    )


def read_ledger_records(
    *,
    project_file: str | None = None,
    workspace_num: int | None = None,
    ledger_file: str | None = None,
) -> list[dict[str, Any]]:
    """Read ledger records in file order, optionally filtered.

    Malformed lines are skipped. Intended for the ``detect`` phase's
    ``sase doctor`` check and for ad-hoc diagnosis of a reported occupancy
    conflict; not performance-tuned for huge ledgers.
    """
    import json

    path = ledger_file if ledger_file is not None else _ledger_file()
    if not os.path.exists(path):
        return []
    records: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if project_file is not None and record.get("project_file") != project_file:
            continue
        if workspace_num is not None and record.get("workspace_num") != workspace_num:
            continue
        records.append(record)
    return records


__all__ = [
    "ledger_path",
    "read_ledger_records",
    "record_running_field_mutation",
]
