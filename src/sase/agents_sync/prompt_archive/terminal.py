"""Audited terminal state for genuinely unrecoverable prompt archives.

A deferred prompt row becomes terminal only when the sase-core classifier
reports ``unrecoverable``: past the grace period, attempts exhausted or
quarantined, no local source in any known location, and no archived copy in
the sidecar. The transition stops retries, releases staging-pool protection
(the pool collector only protects revisions with a non-terminal outbox row),
is excluded from ``--retry-quarantined`` revival, and leaves one JSONL audit
record per transition. It never counts as success: the row is retired, never
acknowledged as published.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)

TERMINAL_OBLIGATIONS_FILENAME = "terminal_obligations.jsonl"
TERMINAL_PROMPT_ARCHIVE_REASON_PREFIX = "prompt_archive_unrecoverable"


def terminal_obligations_path() -> Path:
    """Return where terminal prompt transitions are audited."""

    from sase.core.paths import sase_home

    return sase_home() / "agent_publication" / TERMINAL_OBLIGATIONS_FILENAME


def is_terminal_prompt_archive_reason(reason: str | None) -> bool:
    """Return whether *reason* marks an unrecoverable prompt archive.

    The retiring update records the full restore-failure message as the row's
    ``terminal_reason`` (it must equal the recorded error), so the
    ``prompt_archive_unrecoverable:`` marker is matched anywhere in the
    reason, not just at its start.
    """

    return (
        isinstance(reason, str)
        and TERMINAL_PROMPT_ARCHIVE_REASON_PREFIX + ":" in reason
    )


def terminal_prompt_archive_reason(evidence: str) -> str:
    """Render the ``terminal_reason`` for an unrecoverable prompt archive."""

    return f"{TERMINAL_PROMPT_ARCHIVE_REASON_PREFIX}: {evidence.strip()}"


def _record_terminal_prompt_obligation(
    *,
    project_key: str,
    global_agent: str,
    primary_revision: str,
    run_id: str | None,
    artifacts_dir: str | None,
    evidence: str,
    probes: dict[str, object] | None = None,
    now: float | None = None,
) -> Path:
    """Append one audit record for a terminal prompt transition.

    Returns the audit file path. A failed write is logged and re-raised: the
    transition must not silently lose its audit record.
    """

    path = terminal_obligations_path()
    record = {
        "version": 1,
        "terminal_reason_prefix": TERMINAL_PROMPT_ARCHIVE_REASON_PREFIX,
        "project_key": project_key,
        "global_agent": global_agent,
        "primary_revision": primary_revision,
        "run_id": run_id,
        "artifacts_dir": artifacts_dir,
        "evidence": evidence,
        "probes": probes or {},
        "recorded_at": time.time() if now is None else now,
    }
    line = json.dumps(record, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return path


__all__ = [
    "TERMINAL_OBLIGATIONS_FILENAME",
    "TERMINAL_PROMPT_ARCHIVE_REASON_PREFIX",
    "is_terminal_prompt_archive_reason",
    "record_terminal_prompt_transition",
    "terminal_obligations_path",
    "terminal_prompt_archive_reason",
]


def record_terminal_prompt_transition(
    *,
    project_key: str,
    before: object,
    after: object,
) -> bool:
    """Append the audit record when *after* newly retired *before* as unrecoverable.

    *before* is the outbox row the sync read; *after* is the row the retiring
    update wrote back. Returns whether a record was appended. A failed audit
    write is logged and re-raised: the caller already retired the row, so a
    lost record would leave the transition unaudited.
    """

    was_terminal = bool(getattr(before, "terminal", False))
    is_terminal = bool(getattr(after, "terminal", False))
    reason = getattr(after, "terminal_reason", None)
    if was_terminal or not is_terminal:
        return False
    if not is_terminal_prompt_archive_reason(
        reason if isinstance(reason, str) else None
    ):
        return False
    _record_terminal_prompt_obligation(
        project_key=project_key,
        global_agent=str(getattr(before, "global_agent", "")),
        primary_revision=str(getattr(before, "primary_revision", "")),
        run_id=_optional_str(getattr(before, "run_id", None)),
        artifacts_dir=_optional_str(getattr(before, "artifacts_dir", None)),
        evidence=str(reason),
        probes={
            "attempts_before": getattr(before, "attempts", None),
            "attempts_after": getattr(after, "attempts", None),
            "quarantined_before": getattr(before, "quarantined", None),
            "quarantined_after": getattr(after, "quarantined", None),
            "last_error_before": getattr(before, "last_error", None),
            "created_at": getattr(before, "created_at", None),
        },
    )
    return True


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
