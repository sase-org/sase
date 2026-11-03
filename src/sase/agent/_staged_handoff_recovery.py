"""Durable recovery identity for staged-handoff adoption.

The staged record proves what was staged; this companion preserves the
original execution context a dead runner's successor needs to adopt without
the caller's environment or live ``LoopState``. It is additive: v1 staged
records and receipts are never rewritten here. Old artifacts with
insufficient evidence get a precise refusal instead of invented context.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.core.atomic_json import write_json_marker_atomic
from sase.agent._staged_handoff_store import (
    HANDOFF_LOCK_FILENAME,
    STAGED_HANDOFF_RECEIPT_FILENAME,
    StagedHandoffError,
    acquire_handoff_locks,
    artifacts_root,
    path_exists,
    read_json_object,
)
from sase.core.staged_handoff import (
    StagedHandoffContractError,
    evaluate_recovery_decision,
    receipt_transition_allowed,
    recovery_adoption_lock_filename,
    recovery_context_wire_schema_version,
    validate_recovery_context,
)

if TYPE_CHECKING:
    from sase.axe._run_agent_exec_staged_shared import StagedInlineContinuation

#: Companion filename bound to the original stage.
RECOVERY_CONTEXT_FILENAME = ".sase_handoff_recovery.json"


@dataclass(frozen=True)
class StagedRecoveryAttempt:
    """Adapter input for one adoption attempt.

    ``recovery_context`` is the persisted origin context. ``continuation``
    is the live runner continuation when present; later phases add the
    detached outside-runner path, but this contract already carries the
    persisted facts that path will need. A ``None`` continuation is a
    refusal in the live-runner dispatcher, not a silent default.
    """

    staged_record: Mapping[str, Any]
    run_metadata: Mapping[str, Any]
    recovery_context: Mapping[str, Any]
    continuation: Any | None = None

    def require_live_continuation(self) -> Any:
        """Return the live continuation or refuse without a default."""
        if self.continuation is None:
            raise StagedHandoffError(
                "staged recovery requires the live runner continuation"
            )
        return self.continuation


@contextmanager
def acquire_adoption_lock(root: Path, *, blocking: bool = True) -> Iterator[bool]:
    """Hold the shared adoption lock for *root*.

    Lock ordering: the adoption lock (the existing handoff flock) is the
    outermost staged lock. Acquire it before any gate-lane, monitor-lane,
    or claim lock, and never while already holding the receipt writer's
    lock. Callers that already hold it must use the ``*_locked`` helpers
    below instead of re-acquiring.

    With ``blocking=False``, check the yielded boolean before touching state;
    a busy lock yields false without waiting or changing the staged evidence.
    """
    try:
        adoption_filename = recovery_adoption_lock_filename()
    except StagedHandoffContractError:
        raise
    except ValueError as exc:
        raise StagedHandoffError(str(exc)) from exc
    if adoption_filename != HANDOFF_LOCK_FILENAME:
        raise StagedHandoffError(
            f"adoption lock {adoption_filename!r} does not match handoff lock"
        )
    with acquire_handoff_locks(root, blocking=blocking) as acquired:
        yield acquired


def recovery_context_path(artifacts_dir: str | Path) -> Path:
    """Return the recovery-context companion path."""
    return Path(artifacts_dir) / RECOVERY_CONTEXT_FILENAME


def read_recovery_context(
    artifacts_dir: str | None = None,
    *,
    staged_id: str | None = None,
) -> dict[str, Any] | None:
    """Return the persisted recovery context, or ``None`` when absent.

    Malformed state or a staged-ID mismatch is a refusal, not absence.
    """
    root = artifacts_root(artifacts_dir)
    path = root / RECOVERY_CONTEXT_FILENAME
    if not path_exists(path):
        return None
    payload = read_json_object(path, label="staged recovery context")
    try:
        normalized = validate_recovery_context(payload)
    except StagedHandoffContractError as exc:
        raise StagedHandoffError(
            f"malformed staged recovery context {path.name}: {exc}"
        ) from exc
    if staged_id is not None and normalized.get("staged_id") != staged_id:
        raise StagedHandoffError(
            f"staged recovery context {path.name} belongs to a different stage"
        )
    return normalized


def _normalize_context(context: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return validate_recovery_context(dict(context))
    except StagedHandoffContractError as exc:
        raise StagedHandoffError(str(exc)) from exc


def write_recovery_context_locked(
    context: Mapping[str, Any],
    *,
    artifacts_dir: str | Path,
) -> Path:
    """Persist *context* while the caller holds the adoption lock."""
    normalized = _normalize_context(context)
    path = Path(artifacts_dir) / RECOVERY_CONTEXT_FILENAME
    write_json_marker_atomic(path, normalized)
    return path


def write_recovery_context(
    context: Mapping[str, Any],
    *,
    artifacts_dir: str | None = None,
) -> Path:
    """Validate and atomically persist a recovery-context companion."""
    root = artifacts_root(artifacts_dir)
    normalized = _normalize_context(context)
    with acquire_adoption_lock(root):
        path = root / RECOVERY_CONTEXT_FILENAME
        write_json_marker_atomic(path, normalized)
        return path


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def build_recovery_context(
    staged_record: Mapping[str, Any],
    *,
    artifacts_dir: str,
    run_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the recovery context from stage facts and persisted metadata.

    Only facts not already recoverable from canonical artifacts are carried:
    stable origin identity, workspace/project ownership, prompt/continuation
    references, and the selected model/provider. Nothing is copied from the
    recovering shell's environment.
    """
    from sase.agent._staged_handoff_store import now_rfc3339

    staged_id = staged_record.get("staged_id")
    if not isinstance(staged_id, str) or not staged_id:
        raise StagedHandoffError("staged record has no staged_id")
    kind = staged_record.get("kind")
    if not isinstance(kind, str) or not kind:
        raise StagedHandoffError("staged record has no kind")
    origin_agent = _text(run_metadata.get("name")) or _text(
        run_metadata.get("agent_name")
    )
    if origin_agent is None:
        raise StagedHandoffError("persisted run metadata has no origin agent identity")
    try:
        schema_version = recovery_context_wire_schema_version()
    except StagedHandoffContractError:
        raise
    except ValueError as exc:
        raise StagedHandoffError(str(exc)) from exc
    context: dict[str, Any] = {
        "schema_version": schema_version,
        "staged_id": staged_id,
        "kind": kind,
        "origin_agent": origin_agent,
        "origin_artifacts_dir": str(artifacts_dir),
        "created_at": now_rfc3339(),
    }
    workspace_dir = _text(run_metadata.get("workspace_dir"))
    if workspace_dir is not None:
        context["workspace_dir"] = workspace_dir
    project = _text(run_metadata.get("project")) or _text(
        run_metadata.get("project_name")
    )
    if project is not None:
        context["project"] = project
    model = _text(run_metadata.get("model"))
    if model is not None:
        context["model"] = model
    provider = _text(run_metadata.get("llm_provider")) or _text(
        run_metadata.get("provider")
    )
    if provider is not None:
        context["provider"] = provider
    return _normalize_context(context)


def ensure_recovery_context_locked(
    staged_record: Mapping[str, Any],
    *,
    artifacts_dir: str,
    run_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Persist the recovery context before activation while holding the lock.

    An existing companion for the same stage wins and is never clobbered
    with the recovering caller's values. A companion for a different stage
    is replaced by the freshly built context for this stage.
    """
    staged_id = staged_record.get("staged_id")
    if not isinstance(staged_id, str) or not staged_id:
        raise StagedHandoffError("staged record has no staged_id")
    existing = read_recovery_context(artifacts_dir, staged_id=None)
    if existing is not None and existing.get("staged_id") == staged_id:
        return existing
    context = build_recovery_context(
        staged_record, artifacts_dir=artifacts_dir, run_metadata=run_metadata
    )
    write_recovery_context_locked(context, artifacts_dir=artifacts_dir)
    return context


def ensure_recovery_context(
    staged_record: Mapping[str, Any],
    *,
    artifacts_dir: str,
    run_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Persist the recovery context before activation side effects."""
    root = artifacts_root(artifacts_dir)
    with acquire_adoption_lock(root):
        return ensure_recovery_context_locked(
            staged_record, artifacts_dir=str(root), run_metadata=run_metadata
        )


def decide_recovery(request: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate the Rust recovery decision table for *request*."""
    try:
        return evaluate_recovery_decision(dict(request))
    except StagedHandoffContractError as exc:
        raise StagedHandoffError(str(exc)) from exc


def receipt_may_replace(
    current: Mapping[str, Any] | None,
    next_receipt: Mapping[str, Any],
    staged_id: str,
) -> bool:
    """Return whether *next_receipt* may replace *current* for *staged_id*."""
    try:
        return receipt_transition_allowed(
            dict(current) if current is not None else None,
            dict(next_receipt),
            staged_id,
        )
    except StagedHandoffContractError as exc:
        raise StagedHandoffError(str(exc)) from exc


def write_adoption_receipt_locked(
    receipt: Mapping[str, Any],
    *,
    artifacts_dir: str | Path,
) -> Path:
    """Validate and persist a receipt while holding the adoption lock.

    Enforces receipt monotonicity: a racing hold must never overwrite a
    matching adopted receipt, and a mismatched staged ID is a refusal.
    """
    from sase.core.staged_handoff import validate_staged_handoff_receipt

    root = Path(artifacts_dir)
    try:
        normalized = validate_staged_handoff_receipt(dict(receipt))
    except StagedHandoffContractError as exc:
        raise StagedHandoffError(str(exc)) from exc
    staged_id = normalized.get("staged_id")
    if not isinstance(staged_id, str) or not staged_id:
        raise StagedHandoffError("adoption receipt has no staged_id")
    current_path = root / STAGED_HANDOFF_RECEIPT_FILENAME
    current: dict[str, Any] | None = None
    if path_exists(current_path):
        current = read_json_object(current_path, label="staged handoff receipt")
    if not receipt_may_replace(current, normalized, staged_id):
        raise StagedHandoffError(
            "a successful adoption receipt already owns this stage"
        )
    write_json_marker_atomic(current_path, normalized)
    return current_path


__all__ = [
    "RECOVERY_CONTEXT_FILENAME",
    "StagedRecoveryAttempt",
    "acquire_adoption_lock",
    "build_recovery_context",
    "decide_recovery",
    "ensure_recovery_context",
    "ensure_recovery_context_locked",
    "read_recovery_context",
    "receipt_may_replace",
    "recovery_context_path",
    "write_adoption_receipt_locked",
    "write_recovery_context",
    "write_recovery_context_locked",
]
