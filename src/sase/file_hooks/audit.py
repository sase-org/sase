"""Producer audit records for file-hook dispatch attempts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
import threading
from typing import Any, Literal
from uuid import uuid4

from sase.core.paths import sase_subdir
from sase.core.time import get_timezone

logger = logging.getLogger(__name__)

AUDIT_SCHEMA_VERSION = 1
FILE_HOOK_STATE_DIRS = ("audit", "batches", "logs", "runs")
FileHookDispatchOutcome = Literal[
    "no_hooks",
    "no_match",
    "batch_already_present",
    "batch_dispatched",
    "producer_error",
]
FileHookProducer = Literal["artifact", "commit", "sdd", "finalizer", "dispatch"]

_ERROR_MESSAGE_LIMIT = 500
_SECRET_RE = re.compile(
    r"(?i)\b(password|secret|token|api[_-]?key|authorization|bearer)\b\s*[:=]\s*\S+"
)
_notify_guard = threading.local()


@dataclass(frozen=True)
class FileHookDispatchResult:
    """Typed outcome of one producer-side file-hook dispatch attempt."""

    outcome: FileHookDispatchOutcome
    producer: FileHookProducer
    created_at: str = ""
    audit_id: str = ""
    events: tuple[dict[str, Any], ...] = ()
    matched_hook_names: tuple[str, ...] = ()
    configured_hook_count: int = 0
    commit_sha: str | None = None
    batch_id: str | None = None
    batch_path: str | None = None
    audit_path: str | None = None
    error: str | None = None
    repo_root: str | None = None
    sidecar_role: str | None = None
    agent_name: str | None = None
    project: str | None = None

    def to_payload(self) -> dict[str, Any]:
        """Serialize this result for the producer audit record."""
        return {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "audit_id": self.audit_id,
            "created_at": self.created_at,
            "outcome": self.outcome,
            "producer": self.producer,
            "commit_sha": self.commit_sha,
            "repo_root": self.repo_root,
            "sidecar_role": self.sidecar_role,
            "agent_name": self.agent_name,
            "project": self.project,
            "events": list(self.events),
            "matched_hook_names": list(self.matched_hook_names),
            "configured_hook_count": self.configured_hook_count,
            "batch_id": self.batch_id,
            "batch_path": self.batch_path,
            "error": self.error,
        }


def _file_hook_dispatch_result_from_payload(
    payload: Mapping[str, Any],
    *,
    audit_path: str | None = None,
) -> FileHookDispatchResult:
    """Reconstruct a dispatch result from a persisted producer audit."""
    events_raw = payload.get("events")
    if isinstance(events_raw, list):
        events = tuple(item for item in events_raw if isinstance(item, dict))
    else:
        events = ()
    matched_raw = payload.get("matched_hook_names")
    if isinstance(matched_raw, list):
        matched = tuple(str(item) for item in matched_raw)
    else:
        matched = ()
    return FileHookDispatchResult(
        outcome=_coerce_outcome(payload.get("outcome")),
        producer=_coerce_producer(payload.get("producer")),
        created_at=str(payload.get("created_at") or ""),
        audit_id=str(payload.get("audit_id") or ""),
        events=events,
        matched_hook_names=matched,
        configured_hook_count=_coerce_int(payload.get("configured_hook_count")),
        commit_sha=_optional_str(payload.get("commit_sha")),
        batch_id=_optional_str(payload.get("batch_id")),
        batch_path=_optional_str(payload.get("batch_path")),
        audit_path=audit_path or _optional_str(payload.get("audit_path")),
        error=_optional_str(payload.get("error")),
        repo_root=_optional_str(payload.get("repo_root")),
        sidecar_role=_optional_str(payload.get("sidecar_role")),
        agent_name=_optional_str(payload.get("agent_name")),
        project=_optional_str(payload.get("project")),
    )


def _coerce_outcome(value: object) -> FileHookDispatchOutcome:
    if value in {
        "no_hooks",
        "no_match",
        "batch_already_present",
        "batch_dispatched",
        "producer_error",
    }:
        return value  # type: ignore[return-value]
    return "producer_error"


def _coerce_producer(value: object) -> FileHookProducer:
    if value in {"artifact", "commit", "sdd", "finalizer", "dispatch"}:
        return value  # type: ignore[return-value]
    return "dispatch"


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _coerce_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def safe_file_hook_error_diagnostic(exc: BaseException) -> str:
    """Return a bounded, redacted diagnostic that is safe to persist."""
    text = f"{type(exc).__name__}: {exc}"
    text = _SECRET_RE.sub(r"\1=<redacted>", text)
    if len(text) > _ERROR_MESSAGE_LIMIT:
        return f"{text[: _ERROR_MESSAGE_LIMIT - 3]}..."
    return text


def file_hooks_root() -> Path:
    """Return the file-hook state root under ``SASE_HOME``."""
    return sase_subdir("file_hooks")


def now_iso() -> str:
    """Return the current timezone-aware ISO timestamp."""
    return datetime.now(get_timezone()).isoformat()


def atomic_create_json(path: Path, payload: Mapping[str, Any]) -> bool:
    """Create *path* exactly once and return whether this call won."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(dict(payload), stream, indent=2, sort_keys=True)
            stream.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return True


def _persist_audit(result: FileHookDispatchResult) -> FileHookDispatchResult:
    """Write one producer audit record, retrying once on an id collision."""
    audit_id = result.audit_id or uuid4().hex[:24]
    created_at = result.created_at or now_iso()
    filled = replace(result, audit_id=audit_id, created_at=created_at)
    payload = filled.to_payload()
    directory = file_hooks_root() / "audit"
    path = directory / f"{audit_id}.json"
    if not atomic_create_json(path, payload):
        audit_id = uuid4().hex[:24]
        payload["audit_id"] = audit_id
        path = directory / f"{audit_id}.json"
        if not atomic_create_json(path, payload):
            raise RuntimeError("failed to persist file-hook producer audit")
        filled = replace(filled, audit_id=audit_id)
    return replace(filled, audit_path=str(path))


def _notify_producer_error(result: FileHookDispatchResult) -> None:
    if getattr(_notify_guard, "active", False):
        return
    _notify_guard.active = True
    try:
        from sase.notifications.models import Notification
        from sase.notifications.store import append_notification

        audit_path = result.audit_path
        notes = [
            "❌ file-hook producer failed",
            f"producer: {result.producer}",
            f"outcome: {result.outcome}",
        ]
        if result.commit_sha:
            notes.append(f"commit: {result.commit_sha}")
        if result.repo_root:
            notes.append(f"repository: {result.repo_root}")
        if result.error:
            notes.append(f"error: {result.error}")
        if audit_path:
            notes.append(f"audit: {audit_path}")
        files = [audit_path] if audit_path else []
        notification = Notification(
            id=str(uuid4()),
            timestamp=result.created_at or now_iso(),
            sender="file-hooks",
            icon="❌",
            notes=notes,
            files=files,
            tags=["file-hooks", "producer"],
            action="ViewErrorReport",
            action_data=({"error_report_path": audit_path} if audit_path else {}),
        )
        append_notification(notification)
    except Exception:
        logger.debug(
            "File-hook producer notification failed; continuing", exc_info=True
        )
    finally:
        _notify_guard.active = False


def complete_file_hook_attempt(
    result: FileHookDispatchResult,
) -> FileHookDispatchResult:
    """Persist a producer audit and notify on producer errors. Never raises."""
    completed = result
    try:
        completed = _persist_audit(result)
    except Exception:
        logger.warning(
            "File-hook producer audit persist failed; continuing",
            exc_info=True,
        )
        if not completed.audit_id:
            completed = replace(completed, audit_id=uuid4().hex[:24])
        if not completed.created_at:
            completed = replace(completed, created_at=now_iso())
    if completed.outcome == "producer_error":
        _notify_producer_error(completed)
    return completed


def list_file_hook_audits(*, limit: int | None = None) -> list[FileHookDispatchResult]:
    """Return producer audits newest first, skipping unreadable records."""
    directory = file_hooks_root() / "audit"
    if not directory.is_dir():
        return []
    records: list[FileHookDispatchResult] = []
    for path in directory.iterdir():
        if not path.is_file() or path.suffix != ".json":
            continue
        try:
            with path.open(encoding="utf-8") as stream:
                payload = json.load(stream)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        records.append(
            _file_hook_dispatch_result_from_payload(payload, audit_path=str(path))
        )
    records.sort(key=lambda item: (item.created_at, item.audit_id), reverse=True)
    if limit is None or limit < 0:
        return records
    return records[:limit]


class FileHookAuditNotFoundError(LookupError):
    """Raised when ``sase file-hook show`` cannot resolve an audit id."""


class FileHookAuditAmbiguousError(LookupError):
    """Raised when an audit id prefix matches more than one record."""

    def __init__(self, prefix: str, matches: Sequence[str]) -> None:
        self.prefix = prefix
        self.matches = tuple(matches)
        listed = ", ".join(self.matches)
        super().__init__(f"ambiguous file-hook audit id {prefix!r}: {listed}")


def load_file_hook_audit(audit_id: str) -> FileHookDispatchResult:
    """Load one producer audit by exact id or unique prefix."""
    needle = audit_id.strip()
    if not needle:
        raise FileHookAuditNotFoundError("file-hook audit id is required")
    records = list_file_hook_audits()
    exact = [item for item in records if item.audit_id == needle]
    if exact:
        return exact[0]
    prefixed = [item for item in records if item.audit_id.startswith(needle)]
    if len(prefixed) == 1:
        return prefixed[0]
    if len(prefixed) > 1:
        raise FileHookAuditAmbiguousError(needle, [item.audit_id for item in prefixed])
    raise FileHookAuditNotFoundError(f"file-hook audit not found: {needle}")


__all__ = [
    "AUDIT_SCHEMA_VERSION",
    "FILE_HOOK_STATE_DIRS",
    "FileHookAuditAmbiguousError",
    "FileHookAuditNotFoundError",
    "FileHookDispatchOutcome",
    "FileHookDispatchResult",
    "FileHookProducer",
    "atomic_create_json",
    "complete_file_hook_attempt",
    "file_hooks_root",
    "list_file_hook_audits",
    "load_file_hook_audit",
    "now_iso",
    "safe_file_hook_error_diagnostic",
]
