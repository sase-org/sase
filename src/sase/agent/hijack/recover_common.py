"""Shared types and tiny helpers for exactly-once keep-work recovery."""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import logging

from sase.agent.hijack import ledger

LOG = logging.getLogger(__name__)


KEEP_WORK_ACTIONS = ("escalate", "continue", "instruct")

#: Environment key carrying the durable launch identity into the successor.
RECOVERY_LAUNCH_IDENTITY_ENV = "SASE_HIJACK_LAUNCH_IDENTITY"

#: RecoveryResult kinds. ``launched`` and ``queued`` both hold custody;
#: only ``launched`` proves the successor owns the work.
RESULT_LAUNCHED = "launched"
RESULT_QUEUED = "queued"
RESULT_REFUSED = "refused"
RESULT_ERROR = "error"
RESULT_ALREADY_RESOLVING = "already_resolving"
RESULT_ALREADY_RESOLVED = "already_resolved"
RESULT_UNCERTAIN = "uncertain"

#: Ledger states this executor treats as settled for the predecessor.
TERMINAL_RECOVERY_STATES = frozenset(
    {"resolved", "dismissed", "expired", "stop_failed", "finished_first"}
)


class RecoveryRefusal(RuntimeError):
    """A typed, user-actionable reason recovery cannot proceed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RecoveryTarget:
    """Validated keep-work action with its pinned concrete model target."""

    action: str
    concrete_target: str
    model_changed: bool
    prompt: str
    context_mode: str
    transcript_path: str | None = None


@dataclass(frozen=True)
class RecoveryResult:
    """Structured outcome of one recovery executor call.

    ``successor`` carries the reserved/confirmed successor identity whenever
    one is known, including refusals that arrive after the reservation won.
    ``detail`` carries machine-readable context (current revision, stale
    reasons, launch/admission identity) for the CLI and durable operation.
    """

    kind: str
    hijack_id: str | None = None
    revision: int | None = None
    action: str | None = None
    successor: str | None = None
    launch_identity: str | None = None
    admission_request_id: str | None = None
    concrete_target: str | None = None
    model_changed: bool | None = None
    message: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RecoverySubject:
    """Record plus host-side facts the transaction needs before CAS."""

    record: Mapping[str, Any]
    project_name: str | None
    predecessor_meta: Mapping[str, Any]
    done_outcome: str | None
    done_recovery: Mapping[str, Any] | None


@dataclass(frozen=True)
class InheritanceEvidence:
    """Observable inputs for the mandatory inheritance validation."""

    predecessor_goal: str | None
    successor_goal: str | None
    predecessor_bead: str | None
    successor_bead: str | None
    baseline_inherited: bool
    baseline_diagnostics: tuple[str, ...] = ()
    predecessor_repo_count: int = 0
    transferred_repo_count: int = 0
    repo_diagnostics: tuple[str, ...] = ()
    predecessor_autonomy: Mapping[str, Any] | None = None
    predecessor_name: str | None = None
    explicit_autonomy_selection: str | None = None
    parent_meta: Mapping[str, Any] | None = None
    child_meta: Mapping[str, Any] | None = None
    successor_artifacts_dir: str | None = None


def code_detail(code: str) -> Mapping[str, Any]:
    """Return the ``detail`` payload for a refusal code."""
    return {"code": code}


def predecessor_concrete_target(record: Mapping[str, Any]) -> str | None:
    """Return the predecessor's pinned concrete ``provider/model[@effort]``."""
    provider = clean_string(record.get("provider"))
    model = clean_string(record.get("model"))
    if not model:
        return None
    concrete = model if "/" in model or not provider else f"{provider}/{model}"
    effort = clean_string(record.get("effort"))
    if effort and not concrete.endswith(f"@{effort}"):
        concrete += f"@{effort}"
    return concrete


def record_revision(record: Mapping[str, Any]) -> int:
    raw: Any = record.get("revision")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def record_workspace_num(record: Mapping[str, Any]) -> int | None:
    raw: Any = record.get("workspace_num")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def record_pid(value: Any) -> int | None:
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def clean_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def fail_to_held(resolving: Mapping[str, Any], error: str) -> None:
    try:
        ledger.cas_advance_record(
            dict(resolving), {"event": "resolution_failed", "error": error}
        )
    except (ledger.HijackLedgerConflict, ValueError):
        LOG.warning("recovery return-to-held lost its write", exc_info=True)
    except Exception:  # noqa: BLE001 - best-effort cleanup
        LOG.warning("recovery return-to-held failed", exc_info=True)


def record_launch_stage(
    resolving: Mapping[str, Any],
    launch_identity: str,
    binding: Mapping[str, str],
    *,
    stage: str,
    error: str | None = None,
) -> None:
    event: dict[str, Any] = {
        "event": "record_launch",
        "launch_identity": launch_identity,
        "admission_request_id": binding.get("admission_request_id"),
        "admission_identity": binding.get("admission_identity"),
        "launch_stage": stage,
    }
    if error:
        event["error"] = error
    try:
        ledger.cas_advance_record(dict(resolving), event)
    except (ledger.HijackLedgerConflict, ValueError):
        LOG.warning("recovery stage record lost its write", exc_info=True)
    except Exception:  # noqa: BLE001 - best-effort evidence
        LOG.warning("recovery stage record failed", exc_info=True)


def reload_record(hijack_id: str, fallback: Mapping[str, Any]) -> dict[str, Any]:
    reloaded = ledger.load_record(hijack_id)
    if isinstance(reloaded, Mapping) and reloaded:
        return dict(reloaded)
    return dict(fallback)


def reload_resolution(hijack_id: str, revision: int) -> RecoveryResult:
    current = ledger.load_record(hijack_id)
    if not isinstance(current, Mapping) or not current:
        return RecoveryResult(
            kind=RESULT_ERROR,
            detail=code_detail("record_vanished"),
            hijack_id=hijack_id,
            message="The hijack record disappeared during the reservation",
        )
    state = clean_string(current.get("state")) or ""
    if state == "resolved":
        return current_resolution_result(dict(current), RESULT_ALREADY_RESOLVED)
    if state == "resolving":
        return current_resolution_result(dict(current), RESULT_ALREADY_RESOLVING)
    return RecoveryResult(
        kind=RESULT_REFUSED,
        hijack_id=hijack_id,
        revision=record_revision(current),
        message=(
            f"Another resolver acted first (revision {revision} lost); "
            f"the record is now {state!r}"
        ),
        detail={**code_detail("stale_revision"), "state": state},
    )


def current_resolution_result(record: Mapping[str, Any], kind: str) -> RecoveryResult:
    hijack_id = clean_string(record.get("hijack_id"))
    state = clean_string(record.get("state")) or ""
    message = (
        f"The hijack is already resolved by "
        f"{clean_string(record.get('reserved_successor_name')) or 'a successor'}"
        if kind == RESULT_ALREADY_RESOLVED
        else "A recovery resolution is already in progress"
    )
    return RecoveryResult(
        kind=kind,
        hijack_id=hijack_id,
        revision=record_revision(record),
        action=clean_string(record.get("resolution_action")),
        successor=clean_string(record.get("reserved_successor_name")),
        launch_identity=clean_string(record.get("launch_identity")),
        admission_request_id=clean_string(record.get("admission_request_id")),
        concrete_target=clean_string(record.get("concrete_target_model")),
        model_changed=record.get("model_changed")
        if isinstance(record.get("model_changed"), bool)
        else None,
        message=message,
        detail={
            "state": state,
            "resolver_pid": record.get("resolver_pid"),
            "launch_stage": clean_string(record.get("launch_stage")),
        },
    )


@dataclass
class RecoveryDeps:
    """Injectable seams for the recovery executor.

    Defaults perform the real preview, attach-plan resolution, strict
    spawn, inheritance observation, and claim verification; tests and the
    reconcile phase override individual seams without touching the
    transaction order.
    """

    load_subject: Callable[[object], RecoverySubject | None] | None = None
    preview: Callable[[Mapping[str, Any]], Any] | None = None
    build_prompt: Callable[..., Any] | None = None
    execution_facts: (
        Callable[[Mapping[str, Any], str, str], Mapping[str, Any]] | None
    ) = None
    resolve_session_plan: Callable[[str, str | None], Any] | None = None
    spawn_successor: Callable[..., Any] | None = None
    gather_inheritance: Callable[..., InheritanceEvidence | None] | None = None
    verify_claim: Callable[..., bool] | None = None
    terminate_pid: Callable[[int], None] | None = None
    sleep: Callable[[float], None] | None = None
    settle_timeout_seconds: float = 20.0
    settle_poll_seconds: float = 0.5


def new_launch_identity() -> str:
    """Return a fresh durable launch identity for one resolution attempt."""
    return uuid.uuid4().hex


def admission_binding_for(
    hijack_id: str,
    launch_identity: str,
    reserved_name: str,
    concrete_target: str,
) -> dict[str, str]:
    """Derive the durable admission binding for one resolution.

    ``admission_request_id`` names the single admission request this
    resolution owns; retries address that request rather than submitting
    another launch. ``admission_identity`` is the stable dispatch
    fingerprint for the reserved successor and pinned target. Both are
    persisted on the record before dispatch so a resolver crash leaves
    evidence reconciliation can match without launching a duplicate.
    """
    safe_id = (
        "".join(
            ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(hijack_id)
        ).strip("_")
        or "hijack"
    )
    request_id = f"hijack-recover-{safe_id}-{str(launch_identity)[:12]}"
    fingerprint = hashlib.sha256(
        "\n".join([request_id, str(reserved_name), str(concrete_target)]).encode(
            "utf-8"
        )
    ).hexdigest()
    return {
        "admission_request_id": request_id,
        "admission_identity": fingerprint,
    }


def resolver_identity(
    pid: int | None = None,
    token_fn: Callable[[int], str] | None = None,
) -> tuple[int, str | None]:
    """Return the resolver (pid, process-identity token) pair for CAS.

    The token pairs the pid with kernel boot/start evidence so a recycled
    pid is never mistaken for the winning resolver. An empty token stays
    ``None`` so reconciliation treats the resolver as unverifiable rather
    than confirmed dead.
    """
    resolved_pid = os.getpid() if pid is None else int(pid)
    token: str | None = None
    try:
        raw = (
            token_fn(resolved_pid)
            if token_fn is not None
            else _process_identity_token(resolved_pid)
        )
    except Exception:
        raw = None
    if isinstance(raw, str) and raw:
        token = raw
    return resolved_pid, token


def _process_identity_token(pid: int) -> str | None:
    from sase.core.process_identity import process_identity_token

    try:
        token = process_identity_token(int(pid))
    except Exception:
        return None
    return token or None
