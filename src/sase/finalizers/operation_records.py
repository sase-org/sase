"""Uniform schema-v1 operation records for finalizer executors.

Every operation inside a finalizer attempt writes one
``attempt-N.<op>.outcome.json`` record (or ``preflight.<op>.outcome.json``
before an attempt exists) and emits ``op_started``/``op_finished`` journal
events. See the epic plan §3.3 contracts C1 (journal) and C2 (record).
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from pathlib import Path
from typing import Any

from sase.finalizers.artifacts import (
    instance_artifact_dir,
    write_json_atomic,
)
from sase.finalizers.commit_repair_common import artifact_label

logger = logging.getLogger(__name__)

OPERATION_RECORD_SCHEMA_VERSION = 1

VALID_OPERATION_KINDS = frozenset(
    {"subprocess", "model_turn", "validation", "internal"}
)


def operation_filename(attempt: int | None, op: str) -> str:
    """Return the outcome filename for *op* under *attempt*."""
    safe = artifact_label(op)
    if attempt is None:
        return f"preflight.{safe}.outcome.json"
    return f"attempt-{attempt}.{safe}.outcome.json"


def _journal_of(context: Any) -> Any:
    return getattr(context, "journal", None)


def _tracker_of(context: Any) -> Any:
    return getattr(context, "tracker", None)


@dataclass
class OperationRecorder:
    """Best-effort writer of operation records plus journal op events."""

    artifacts_dir: str | None
    instance_id: str
    journal: Any = None
    tracker: Any = None

    @classmethod
    def for_context(cls, context: Any, instance_id: str) -> OperationRecorder:
        """Build a recorder from an execution context, if it carries any."""
        artifacts_dir = getattr(context, "artifacts_dir", None)
        return cls(
            artifacts_dir,
            instance_id,
            journal=_journal_of(context),
            tracker=_tracker_of(context),
        )

    def start(
        self,
        op: str,
        *,
        kind: str,
        label: str,
        attempt: int | None,
    ) -> float:
        """Emit ``op_started`` and tracker state; return wall-clock start."""
        started_at = time.time()
        if kind not in VALID_OPERATION_KINDS:
            logger.debug("unknown operation kind %r; recording anyway", kind)
        if self.tracker is not None and attempt is not None:
            try:
                self.tracker.note_op(self.instance_id, label)
            except Exception:  # noqa: BLE001 - observability is best-effort
                logger.debug("operation tracker note_op failed", exc_info=True)
        if self.journal is not None:
            try:
                self.journal.record(
                    "op_started",
                    instance_id=self.instance_id,
                    attempt=attempt,
                    op=artifact_label(op),
                    kind=kind,
                    label=label,
                )
            except Exception:  # noqa: BLE001 - journaling is best-effort
                logger.debug("operation journal op_started failed", exc_info=True)
        return started_at

    def finish(
        self,
        op: str,
        *,
        kind: str,
        label: str,
        attempt: int | None,
        started_at: float | None = None,
        duration_seconds: float = 0.0,
        argv: Any | None = None,
        returncode: int | None = None,
        timed_out: bool = False,
        stdout_truncated: bool = False,
        stderr_truncated: bool = False,
        logs: dict[str, str] | None = None,
        steps: str | None = None,
        prompt: str | None = None,
        response: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Path | None:
        """Write the outcome record and emit ``op_finished``; never fails open."""
        if started_at is None:
            started_at = time.time()
        payload: dict[str, Any] = {
            "schema_version": OPERATION_RECORD_SCHEMA_VERSION,
            "op": artifact_label(op),
            "kind": kind,
            "label": label,
            "attempt": attempt,
            "started_at": started_at,
            "duration_seconds": float(duration_seconds or 0.0),
            "timed_out": bool(timed_out),
            "stdout_truncated": bool(stdout_truncated),
            "stderr_truncated": bool(stderr_truncated),
        }
        if argv is not None:
            payload["argv"] = list(argv)
        if returncode is not None:
            payload["returncode"] = returncode
        if logs:
            payload["logs"] = dict(logs)
        if steps is not None:
            payload["steps"] = steps
        if prompt is not None:
            payload["prompt"] = prompt
        if response is not None:
            payload["response"] = response
        if extra:
            for key, value in extra.items():
                if key not in payload:
                    payload[key] = value
        written: Path | None = None
        try:
            artifact_dir = instance_artifact_dir(self.artifacts_dir, self.instance_id)
            if artifact_dir is not None:
                filename = operation_filename(attempt, op)
                exclusive = attempt is not None
                try:
                    write_json_atomic(
                        artifact_dir / filename, payload, exclusive=exclusive
                    )
                    written = artifact_dir / filename
                except FileExistsError:
                    raise
                except Exception:  # noqa: BLE001 - observability is best-effort
                    logger.debug("operation record write failed", exc_info=True)
                    written = None
        except FileExistsError:
            raise
        except Exception:  # noqa: BLE001 - observability is best-effort
            logger.debug("operation record resolve failed", exc_info=True)
        if self.journal is not None:
            try:
                finished_fields: dict[str, Any] = {
                    "instance_id": self.instance_id,
                    "attempt": attempt,
                    "op": artifact_label(op),
                    "kind": kind,
                    "label": label,
                    "duration_seconds": float(duration_seconds or 0.0),
                    "timed_out": bool(timed_out),
                }
                if returncode is not None:
                    finished_fields["returncode"] = returncode
                self.journal.record("op_finished", **finished_fields)
            except Exception:  # noqa: BLE001 - journaling is best-effort
                logger.debug("operation journal op_finished failed", exc_info=True)
        if self.tracker is not None:
            try:
                self.tracker.flush_pending_step(self.instance_id)
            except Exception:  # noqa: BLE001 - observability is best-effort
                logger.debug("operation tracker flush failed", exc_info=True)
        return written


__all__ = [
    "OPERATION_RECORD_SCHEMA_VERSION",
    "VALID_OPERATION_KINDS",
    "OperationRecorder",
    "operation_filename",
]
