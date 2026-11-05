"""Durable typed admission for keep-work recovery attempts.

The attempt descriptor is prepared before the hijack CAS but is not a launch
request until the CAS wins. A typed admission bundle then makes that exact
attempt coordinator-readable. Its dispatcher reconstructs the strict
successor launch from the persisted descriptor rather than allocating a new
workspace or successor identity.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack.recover_common import RECOVERY_LAUNCH_IDENTITY_ENV
from sase.agent.hijack.recovery_successor import (
    RECOVERY_DESCRIPTOR_ENV,
    RecoveryInheritanceError,
    RecoveryLineage,
    build_recovery_descriptor,
    encode_recovery_descriptor,
)
from sase.agent.launch_admission_store import (
    RECEIPT_FILENAME,
    admission_dir,
    read_journal,
    read_json,
)
from sase.core.agent_launch_facade import dispatch_fingerprint
from sase.core.agent_launch_wire import (
    AgentUnitWire,
    agent_launch_wire_to_json_dict,
    launch_plan_from_dict,
)
from sase.core.atomic_json import write_json_marker_atomic

RECOVERY_ADMISSION_SOURCE_SURFACE = "agent_hijack_recovery"
RECOVERY_ADMISSION_METADATA_KEY = "hijack_recovery_descriptor"
RECOVERY_ADMISSION_SCHEMA_VERSION = 1
RECOVERY_REQUESTS_SUBDIR = "hijack_recovery_requests"
TYPED_LAUNCHES_SUBDIR = "typed_launches"
LOGICAL_ID = "hijack-recovery"
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+\Z")


def prepare_recovery_admission_descriptor(
    *,
    record: Mapping[str, Any],
    action: str,
    target: str,
    model_changed: bool,
    prompt: str,
    context_mode: str,
    reserved_successor_name: str,
    session_base: str,
    project_name: str,
    launch_identity: str,
    admission_request_id: str,
    lineage: RecoveryLineage,
    resolver_pid: int,
    resolver_process_identity_token: str | None,
    attempt_revision: int,
    launch_submitted_at: str,
) -> dict[str, Any]:
    """Build the immutable, coordinator-readable descriptor for one attempt."""
    from sase.agent.launch_request_planning import prepare_typed_launch_plan
    from sase.macro.directive_edit import set_prompt_model, set_prompt_name

    descriptor: dict[str, Any] = {
        "schema_version": RECOVERY_ADMISSION_SCHEMA_VERSION,
        "hijack_id": str(record.get("hijack_id") or ""),
        "action": action,
        "target": target,
        "model_changed": bool(model_changed),
        "prompt": prompt,
        "context_mode": context_mode,
        "reserved_successor_name": reserved_successor_name,
        "session_base": session_base,
        "project_name": project_name,
        "project_file": _string_or_none(record.get("project_file")),
        "workspace_num": _positive_int(record.get("workspace_num")),
        "workspace_dir": _string_or_none(record.get("workspace_dir")),
        "expected_claim_owner_pid": _positive_int(
            record.get("expected_claim_owner_pid")
        ),
        "launch_identity": launch_identity,
        "admission_request_id": admission_request_id,
        "lineage": lineage.as_dict(),
        "resolver_pid": resolver_pid,
        "resolver_process_identity_token": resolver_process_identity_token,
        "attempt_revision": attempt_revision,
        "launch_submitted_at": launch_submitted_at,
    }
    _validate_descriptor_fields(descriptor)
    descriptor_digest = _descriptor_digest(descriptor)
    # This synthetic planner prompt carries the reserved identity and exact
    # model into the Rust admission fingerprint. The recovery dispatcher uses
    # the prepared prompt in metadata and never dispatches this marker text.
    plan_prompt = set_prompt_name("", reserved_successor_name)
    plan_prompt = set_prompt_model(plan_prompt, target)
    plan_prompt = f"{plan_prompt}\nSASE recovery descriptor {descriptor_digest}"
    plan_data = prepare_typed_launch_plan(
        plan_prompt,
        selected_project=project_name,
        launch_kind="multi_prompt",
    )
    plan = launch_plan_from_dict(plan_data)
    if len(plan.units) != 1:
        raise ValueError("recovery admission must plan exactly one agent unit")
    unit = plan.units[0]
    payload = unit.payload
    if not isinstance(payload, AgentUnitWire):
        raise ValueError("recovery admission must contain an agent unit")
    if payload.identity != reserved_successor_name:
        raise ValueError("typed recovery plan changed the reserved successor name")
    expected_model, expected_effort = _split_model_effort(target)
    if payload.model != expected_model or payload.reasoning_effort != expected_effort:
        raise ValueError("typed recovery plan changed the pinned model or effort")
    fingerprint = dispatch_fingerprint(
        plan.content_digest,
        unit.logical_id,
        payload,
    )
    descriptor.update(
        descriptor_digest=descriptor_digest,
        logical_id=unit.logical_id,
        typed_plan=plan_data,
        plan_digest=plan.content_digest,
        dispatch_fingerprint=fingerprint,
    )
    return descriptor


def persist_prepared_recovery_descriptor(descriptor: Mapping[str, Any]) -> Path:
    """Persist an inert draft so a post-CAS crash can materialize its request."""
    from sase.core.paths import sase_subdir
    from sase.notification_gates.durability import file_lock

    request_id = _required_string(descriptor, "admission_request_id")
    _validate_request_id(request_id)
    path = sase_subdir(RECOVERY_REQUESTS_SUBDIR) / f"{request_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path.with_suffix(".lock"), timeout=10.0):
        existing = read_json(path)
        candidate = dict(descriptor)
        if path.exists() and existing is None:
            raise ValueError(
                f"recovery request {request_id} is unreadable or malformed"
            )
        if existing is not None:
            if _canonical_json(existing) != _canonical_json(candidate):
                raise ValueError(
                    f"recovery request {request_id} already has different contents"
                )
            return path
        write_json_marker_atomic(path, candidate)
    return path


def _read_prepared_recovery_descriptor(request_id: str) -> dict[str, Any] | None:
    """Read one inert or submitted recovery descriptor by its durable id."""
    from sase.core.paths import sase_subdir

    _validate_request_id(request_id)
    path = sase_subdir(RECOVERY_REQUESTS_SUBDIR) / f"{request_id}.json"
    payload = read_json(path)
    if payload is None:
        return None
    return payload


def remove_prepared_recovery_descriptor(request_id: str) -> None:
    """Remove an inert draft whose held-state CAS lost to another resolver."""
    from sase.core.paths import sase_subdir

    _validate_request_id(request_id)
    path = sase_subdir(RECOVERY_REQUESTS_SUBDIR) / f"{request_id}.json"
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return


def dispatch_recovery_admission(
    descriptor: Mapping[str, Any],
    *,
    spawn_successor: Callable[..., Any] | None = None,
    resolve_session_plan: Callable[[str, str | None], Any] | None = None,
    spawn_coordinator: bool = True,
) -> tuple[Any, Path]:
    """Materialize and submit the exact typed recovery request idempotently."""
    from sase.agent.direct_typed_launch import typed_launch_project_display_name
    from sase.agent.launch_admission import dispatch_typed_launch_request
    from sase.core.paths import sase_subdir
    from sase.notification_gates.durability import file_lock
    from sase.notification_gates.paths import REQUEST_FILENAME

    payload = _typed_request_payload(descriptor, typed_launch_project_display_name)
    request_id = _required_string(payload, "request_id")
    _validate_request_id(request_id)
    bundle_dir = sase_subdir(TYPED_LAUNCHES_SUBDIR) / request_id
    request_path = bundle_dir / REQUEST_FILENAME
    envelope = {
        "kind": "direct_typed_launch",
        "request_id": request_id,
        "payload": payload,
    }
    bundle_dir.mkdir(parents=True, exist_ok=True)
    with file_lock(bundle_dir / "recovery-request.lock", timeout=10.0):
        existing = read_json(request_path)
        if request_path.exists() and existing is None:
            raise ValueError(
                f"typed admission request {request_id} is unreadable or malformed"
            )
        if existing is not None:
            if _canonical_json(existing) != _canonical_json(envelope):
                raise ValueError(
                    f"typed admission request {request_id} has conflicting contents"
                )
        else:
            write_json_marker_atomic(request_path, envelope)
    dispatcher = make_hijack_recovery_agent_dispatcher(
        payload,
        bundle_dir=bundle_dir,
        spawn_successor=spawn_successor,
        resolve_session_plan=resolve_session_plan,
    )
    result = dispatch_typed_launch_request(
        bundle_dir,
        payload,
        agent_dispatcher=dispatcher,
        spawn_coordinator=spawn_coordinator,
    )
    return result, bundle_dir


def is_hijack_recovery_typed_request(data: Mapping[str, Any]) -> bool:
    return str(data.get("source_surface") or "") == RECOVERY_ADMISSION_SOURCE_SURFACE


def make_hijack_recovery_agent_dispatcher(
    data: Mapping[str, Any],
    *,
    bundle_dir: Path | None = None,
    spawn_successor: Callable[..., Any] | None = None,
    resolve_session_plan: Callable[[str, str | None], Any] | None = None,
) -> Callable[..., Any]:
    """Reconstruct a strict, same-workspace dispatcher from request metadata."""
    descriptor = _descriptor_from_data(data)
    if descriptor is None:
        return _missing_descriptor_dispatcher()
    response_dir = bundle_dir or _bundle_dir_for_request(
        _required_string(data, "request_id")
    )

    def dispatch(
        unit: Any,
        fingerprint: str,
    ) -> tuple[bool, str | None, str | None, list[Any], dict[str, Any]]:
        error = _validate_dispatch_binding(
            data,
            descriptor,
            response_dir,
            unit,
            fingerprint,
        )
        if error:
            return False, None, error, [], {"receipt_state": "rejected"}
        current = ledger.load_record(_required_string(descriptor, "hijack_id"))
        if current is None:
            return (
                False,
                None,
                "recovery record disappeared before dispatch",
                [],
                {"receipt_state": "rejected"},
            )
        if not _record_owns_descriptor(current, descriptor):
            return (
                False,
                None,
                "recovery reservation changed before dispatch",
                [],
                {"receipt_state": "rejected"},
            )
        available, message = _target_available(_required_string(descriptor, "target"))
        if not available:
            return False, None, message, [], {"receipt_state": "rejected"}
        try:
            claim_owner = _current_claim_owner(descriptor)
            plan = _resolve_reserved_plan(descriptor, resolve_session_plan)
        except RecoveryInheritanceError as exc:
            return False, None, str(exc), [], {"receipt_state": "rejected"}
        except Exception as exc:  # noqa: BLE001 - no spawn has started
            return (
                False,
                None,
                f"recovery successor could not be prepared: {exc}",
                [],
                {"receipt_state": "rejected"},
            )
        if str(getattr(plan, "agent_name", "") or "") != str(
            descriptor.get("reserved_successor_name") or ""
        ):
            return (
                False,
                None,
                "reserved recovery successor identity is no longer available",
                [],
                {"receipt_state": "rejected"},
            )
        spawn = spawn_successor or _spawn_strict_successor
        try:
            bootstrap_descriptor = _bootstrap_reservation_descriptor(
                descriptor, fingerprint
            )
            extra_env = _launch_environment(descriptor, unit.logical_id, fingerprint)
            extra_env[RECOVERY_DESCRIPTOR_ENV] = encode_recovery_descriptor(
                bootstrap_descriptor
            )
        except (RecoveryInheritanceError, TypeError, ValueError) as exc:
            return False, None, str(exc), [], {"receipt_state": "rejected"}
        try:
            result = spawn(
                session_base=_required_string(descriptor, "session_base"),
                plan=plan,
                project_name=_required_string(descriptor, "project_name"),
                project_file=_string_or_none(descriptor.get("project_file")),
                prompt=_required_string(descriptor, "prompt"),
                workspace_dir=_required_string(descriptor, "workspace_dir"),
                workspace_num=int(descriptor["workspace_num"]),
                transfer_from_pid=claim_owner,
                lineage=RecoveryLineage(**dict(descriptor["lineage"])),
                descriptor=bootstrap_descriptor,
                extra_env=extra_env,
            )
        except RecoveryInheritanceError as exc:
            return False, None, str(exc), [], {"receipt_state": "rejected"}
        except Exception as exc:
            from sase.running_field import WorkspaceClaimError

            if isinstance(exc, WorkspaceClaimError):
                return False, None, str(exc), [], {"receipt_state": "failed"}
            raise
        identity = str(getattr(result, "agent_name", "") or "")
        if not identity:
            identity = str(getattr(result, "pid", "") or fingerprint)
        extra = {
            "workspace_reference": str(descriptor.get("workspace_dir") or ""),
            "dispatch_target": _required_string(descriptor, "target"),
        }
        return True, identity, None, [result], extra

    return dispatch


def observe_recovery_admission(request_id: str) -> dict[str, Any]:
    """Read request and journal status for recovery reconciliation callers."""
    from sase.agent.launch_request_response import read_launch_request

    _validate_request_id(request_id)
    bundle_dir = _bundle_dir_for_request(request_id)
    try:
        data = read_launch_request(bundle_dir)
    except Exception as exc:
        return {
            "request_id": request_id,
            "state": "missing",
            "message": str(exc),
        }
    descriptor = _descriptor_from_data(data)
    plan_digest = str(data.get("plan_digest") or "")
    states = _ledgerless_admission_states(bundle_dir)
    logical_id = str((descriptor or {}).get("logical_id") or LOGICAL_ID)
    unit_state = states.get(logical_id, {})
    phase = str(unit_state.get("phase") or "submitted")
    return {
        "request_id": request_id,
        "dispatch_fingerprint": str(
            (descriptor or {}).get("dispatch_fingerprint") or ""
        ),
        "identity": unit_state.get("identity"),
        "plan_digest": plan_digest,
        "state": phase,
        "message": unit_state.get("message"),
        "receipt_state": unit_state.get("receipt_state"),
        "in_flight": phase
        in {"submitted", "reserved", "waiting", "checking", "eligible", "dispatching"},
        "cancel_requested": (admission_dir(bundle_dir) / "cancel.json").is_file(),
        "receipt": read_json(admission_dir(bundle_dir) / RECEIPT_FILENAME),
    }


def resume_recovery_admission(
    record: Mapping[str, Any],
    *,
    spawn_successor: Callable[..., Any] | None = None,
    resolve_session_plan: Callable[[str, str | None], Any] | None = None,
) -> dict[str, Any]:
    """Resume the exact pending request after a resolver interruption."""
    from sase.agent.launch_request_response import read_launch_request

    request_id = _string_or_none(record.get("admission_request_id"))
    if request_id is None:
        return {"state": "missing", "message": "record has no admission request id"}
    descriptor = _read_prepared_recovery_descriptor(request_id)
    bundle_dir = _bundle_dir_for_request(request_id)
    if descriptor is None:
        try:
            descriptor = _descriptor_from_data(read_launch_request(bundle_dir))
        except Exception:
            descriptor = None
    if descriptor is None:
        return observe_recovery_admission(request_id)
    if not _record_owns_descriptor(record, descriptor):
        return {
            "request_id": request_id,
            "state": "mismatch",
            "message": "prepared request does not match the resolving reservation",
        }
    status = observe_recovery_admission(request_id)
    if status.get("state") not in {
        "missing",
        "submitted",
        "reserved",
        "waiting",
        "eligible",
    }:
        return status
    try:
        dispatch_recovery_admission(
            descriptor,
            spawn_successor=spawn_successor,
            resolve_session_plan=resolve_session_plan,
            spawn_coordinator=True,
        )
    except Exception as exc:  # noqa: BLE001 - retain attempt for reconciliation
        status = observe_recovery_admission(request_id)
        status["message"] = f"could not resume durable recovery request: {exc}"
        return status
    return observe_recovery_admission(request_id)


def cancel_recovery_admission_request(
    request_id: str,
    *,
    reason: str = "recovery attempt cancelled",
) -> dict[str, Any]:
    """Durably cancel one request and wait until its admission journal settles."""
    from sase.agent.launch_admission import cancel_typed_launch_request
    from sase.agent.launch_request_response import read_launch_request

    _validate_request_id(request_id)
    bundle_dir = _bundle_dir_for_request(request_id)
    result = cancel_typed_launch_request(
        bundle_dir,
        reason=reason,
    )
    if result.get("state") != "cancelled":
        return result
    try:
        descriptor = _descriptor_from_data(read_launch_request(bundle_dir))
    except Exception:
        descriptor = None
    if descriptor is None:
        return result
    current = ledger.load_record(_required_string(descriptor, "hijack_id"))
    if current is None or not _record_owns_descriptor(current, descriptor):
        return result
    from sase.agent.hijack.recover_common import fail_to_held

    fail_to_held(current, reason)
    settled = ledger.load_record(_required_string(descriptor, "hijack_id"))
    result["recovery_state"] = (
        str(settled.get("state") or "unknown")
        if isinstance(settled, Mapping)
        else "unknown"
    )
    return result


def cancel_recovery_admission_for_rollback(
    request_id: str,
    *,
    reason: str = "recovery confirmation failed",
) -> dict[str, Any]:
    """Make a recovery request non-dispatchable without changing its bead state.

    Confirmation rollback must first prove cancellation, child termination,
    and custody restoration, then advance the hijack record. The ordinary
    cancellation entrypoint also returns the record to held, so this variant
    deliberately performs only the admission cancellation and observation.
    """
    status = observe_recovery_admission(request_id)
    if not status.get("in_flight"):
        return dict(status)

    from sase.agent.launch_admission import cancel_typed_launch_request

    try:
        cancellation = cancel_typed_launch_request(
            _bundle_dir_for_request(request_id), reason=reason
        )
    except Exception as exc:  # noqa: BLE001 - observe whether cancellation settled
        status = observe_recovery_admission(request_id)
        return {
            **dict(status),
            "cancel_error": str(exc),
        }
    status = observe_recovery_admission(request_id)
    return {
        **dict(status),
        "cancellation": dict(cancellation),
    }


def _typed_request_payload(
    descriptor: Mapping[str, Any],
    project_display: Callable[[str | None], str | None],
) -> dict[str, Any]:
    _validate_descriptor_fields(descriptor)
    plan = descriptor.get("typed_plan")
    if not isinstance(plan, Mapping):
        raise ValueError("recovery descriptor has no typed plan")
    plan_dict = dict(plan)
    plan_digest = str(plan_dict.get("content_digest") or "")
    if plan_digest != str(descriptor.get("plan_digest") or ""):
        raise ValueError("recovery descriptor plan digest does not match")
    selected_project = _required_string(descriptor, "project_name")
    payload: dict[str, Any] = {
        "request_id": _required_string(descriptor, "admission_request_id"),
        "source_surface": RECOVERY_ADMISSION_SOURCE_SURFACE,
        "typed_plan": plan_dict,
        "plan_digest": plan_digest,
        "plan_schema_version": plan_dict.get("schema_version"),
        "dispatch": {
            "cwd": _required_string(descriptor, "workspace_dir"),
            "prompt": _required_string(descriptor, "prompt"),
        },
        "submitted_prompt": _required_string(descriptor, "prompt"),
        "expanded_prompt": _required_string(descriptor, "prompt"),
        "safe_inputs": {},
        "launch_submitted_at": _required_string(descriptor, "launch_submitted_at"),
        "unit_dispatch_metadata": {
            RECOVERY_ADMISSION_METADATA_KEY: dict(descriptor),
        },
        "selected_project": selected_project,
    }
    display = project_display(selected_project)
    if display:
        payload["selected_project_display"] = display
    project_file = _string_or_none(descriptor.get("project_file"))
    if project_file:
        payload["project_file"] = project_file
    return payload


def _descriptor_from_data(data: Mapping[str, Any]) -> dict[str, Any] | None:
    metadata = data.get("unit_dispatch_metadata")
    if not isinstance(metadata, Mapping):
        return None
    descriptor = metadata.get(RECOVERY_ADMISSION_METADATA_KEY)
    if not isinstance(descriptor, Mapping):
        return None
    return dict(descriptor)


def _validate_dispatch_binding(
    data: Mapping[str, Any],
    descriptor: Mapping[str, Any],
    bundle_dir: Path,
    unit: Any,
    fingerprint: str,
) -> str | None:
    if not is_hijack_recovery_typed_request(data):
        return "typed request is not owned by hijack recovery"
    if str(data.get("request_id") or "") != str(
        descriptor.get("admission_request_id") or ""
    ):
        return "recovery admission request id does not match its descriptor"
    if str(data.get("plan_digest") or "") != str(descriptor.get("plan_digest") or ""):
        return "recovery admission plan digest changed"
    try:
        _validate_descriptor_fields(descriptor)
        _validate_request_id(str(data.get("request_id") or ""))
    except (TypeError, ValueError) as exc:
        return str(exc)
    if _descriptor_digest(descriptor) != str(descriptor.get("descriptor_digest") or ""):
        return "recovery admission descriptor checksum changed"
    try:
        plan = launch_plan_from_dict(dict(data.get("typed_plan") or {}))
    except (TypeError, ValueError) as exc:
        return f"recovery admission typed plan is invalid: {exc}"
    if plan.content_digest != str(descriptor.get("plan_digest") or ""):
        return "recovery admission plan changed"
    if len(plan.units) != 1 or plan.units[0].logical_id != str(
        descriptor.get("logical_id") or ""
    ):
        return "recovery admission unit identity changed"
    if not isinstance(unit.payload, AgentUnitWire):
        return "recovery admission contains a non-agent unit"
    if unit.logical_id != str(descriptor.get("logical_id") or ""):
        return "recovery admission unit identity changed"
    if unit.payload.identity != str(descriptor.get("reserved_successor_name") or ""):
        return "recovery admission reserved successor changed"
    expected_model, expected_effort = _split_model_effort(
        _required_string(descriptor, "target")
    )
    if (
        unit.payload.model != expected_model
        or unit.payload.reasoning_effort != expected_effort
    ):
        return "recovery admission model or effort changed"
    actual = dispatch_fingerprint(plan.content_digest, unit.logical_id, unit.payload)
    if actual != fingerprint or actual != str(
        descriptor.get("dispatch_fingerprint") or ""
    ):
        return "recovery admission dispatch fingerprint changed"
    if not _descriptor_is_persisted(descriptor):
        return "recovery admission has no matching prepared descriptor"
    from sase.notification_gates.paths import REQUEST_FILENAME

    request_path = bundle_dir / REQUEST_FILENAME
    envelope = read_json(request_path)
    if (
        not isinstance(envelope, Mapping)
        or envelope.get("kind") != "direct_typed_launch"
        or envelope.get("request_id") != data.get("request_id")
        or _canonical_json(envelope.get("payload")) != _canonical_json(data)
    ):
        return "recovery admission request envelope changed"
    return None


def _descriptor_is_persisted(descriptor: Mapping[str, Any]) -> bool:
    try:
        persisted = _read_prepared_recovery_descriptor(
            _required_string(descriptor, "admission_request_id")
        )
    except (TypeError, ValueError):
        return False
    return persisted is not None and _canonical_json(persisted) == _canonical_json(
        dict(descriptor)
    )


def _record_owns_descriptor(
    record: Mapping[str, Any], descriptor: Mapping[str, Any]
) -> bool:
    expected = {
        "state": "resolving",
        "hijack_id": descriptor.get("hijack_id"),
        "resolution_action": descriptor.get("action"),
        "reserved_successor_name": descriptor.get("reserved_successor_name"),
        "concrete_target_model": descriptor.get("target"),
        "launch_identity": descriptor.get("launch_identity"),
        "admission_request_id": descriptor.get("admission_request_id"),
        "admission_identity": descriptor.get("dispatch_fingerprint"),
        "workspace_num": descriptor.get("workspace_num"),
        "workspace_dir": descriptor.get("workspace_dir"),
        "project_file": descriptor.get("project_file"),
        "expected_claim_owner_pid": descriptor.get("expected_claim_owner_pid"),
        "resolver_pid": descriptor.get("resolver_pid"),
        "resolver_process_identity_token": descriptor.get(
            "resolver_process_identity_token"
        ),
    }
    return all(record.get(key) == value for key, value in expected.items())


def _current_claim_owner(descriptor: Mapping[str, Any]) -> int | None:
    from sase.ace.patch import patch_lock
    from sase.running_field._model import WorkspaceClaim
    from sase.workflows.utils import get_project_file_path

    project_name = _required_string(descriptor, "project_name")
    project_file = _string_or_none(
        descriptor.get("project_file")
    ) or get_project_file_path(project_name)
    workspace_num = descriptor.get("workspace_num")
    expected_owner = _positive_int(descriptor.get("expected_claim_owner_pid"))
    if (
        not isinstance(workspace_num, int)
        or isinstance(workspace_num, bool)
        or workspace_num <= 0
    ):
        raise RecoveryInheritanceError("recovery requires a fixed positive workspace")
    try:
        with patch_lock(project_file):
            content = Path(project_file).read_text(encoding="utf-8")
    except OSError as exc:
        raise RecoveryInheritanceError(
            f"recovery cannot read the held workspace claim: {exc}"
        ) from exc
    claims = [
        claim
        for line in content.splitlines()
        if (claim := WorkspaceClaim.from_line(line)) is not None
        and claim.workspace_num == workspace_num
    ]
    if len(claims) > 1:
        raise RecoveryInheritanceError(
            f"workspace #{workspace_num} has multiple current claims"
        )
    if not claims:
        # The old claim may already be missing. The exact workspace will be
        # claimed atomically at child spawn, and a new/foreign row will fail
        # that operation rather than redirecting to an allocator.
        return None
    actual_owner = int(claims[0].pid)
    if expected_owner is None or actual_owner != expected_owner:
        raise RecoveryInheritanceError(
            f"workspace #{workspace_num} is owned by pid {actual_owner}, not the "
            f"held owner {expected_owner!r}"
        )
    return actual_owner


def _resolve_reserved_plan(
    descriptor: Mapping[str, Any],
    resolve_session_plan: Callable[[str, str | None], Any] | None,
) -> Any:
    session_base = _required_string(descriptor, "session_base")
    project_name = _required_string(descriptor, "project_name")
    if resolve_session_plan is not None:
        return resolve_session_plan(session_base, project_name)
    from sase.agent import _agent_session_attach_resolution as resolution
    from sase.agent.detached_child import AgentSessionAttachDirective

    return resolution.resolve_agent_session_attach_plan(
        AgentSessionAttachDirective(parent=session_base, suffix="@"),
        project_name=project_name,
    )


def _spawn_strict_successor(**kwargs: Any) -> Any:
    from sase.agent.detached_child import (
        AgentSessionAttachDirective,
        spawn_recovery_successor,
    )

    lineage = kwargs["lineage"]
    plan = kwargs["plan"]
    return spawn_recovery_successor(
        AgentSessionAttachDirective(parent=kwargs["session_base"], suffix="@"),
        project_name=kwargs["project_name"],
        project_file=kwargs.get("project_file"),
        prompt=kwargs["prompt"],
        workspace_dir=kwargs["workspace_dir"],
        workspace_num=kwargs["workspace_num"],
        transfer_from_pid=kwargs["transfer_from_pid"],
        lineage=lineage,
        descriptor=kwargs["descriptor"],
        cl_name=plan.agent_name,
        extra_env=dict(kwargs["extra_env"]),
        resolve_plan=lambda *args, **kw: plan,
    )


def _launch_environment(
    descriptor: Mapping[str, Any], logical_id: str, fingerprint: str
) -> dict[str, str]:
    import json as json_module

    from sase.agent.hijack.recovery_successor import (
        RECOVERY_LINEAGE_ENV,
        RECOVERY_STRICT_ENV,
    )
    from sase.env_contracts import SASE_LAUNCH_SUBMITTED_AT_ENV

    return {
        RECOVERY_LAUNCH_IDENTITY_ENV: _required_string(descriptor, "launch_identity"),
        RECOVERY_LINEAGE_ENV: json_module.dumps(
            dict(descriptor["lineage"]), sort_keys=True
        ),
        RECOVERY_STRICT_ENV: "1",
        "SASE_LAUNCH_DISPATCH_FINGERPRINT": fingerprint,
        "SASE_LAUNCH_LOGICAL_ID": logical_id,
        SASE_LAUNCH_SUBMITTED_AT_ENV: _required_string(
            descriptor, "launch_submitted_at"
        ),
    }


def _bootstrap_reservation_descriptor(
    descriptor: Mapping[str, Any], fingerprint: str
) -> dict[str, Any]:
    """Bind strict child bootstrap to the typed admission reservation."""
    prompt = _required_string(descriptor, "prompt")
    return build_recovery_descriptor(
        hijack_id=_required_string(descriptor, "hijack_id"),
        launch_identity=_required_string(descriptor, "launch_identity"),
        concrete_target=_required_string(descriptor, "target"),
        reserved_successor_name=_required_string(descriptor, "reserved_successor_name"),
        project=_required_string(descriptor, "project_name"),
        workspace_dir=_required_string(descriptor, "workspace_dir"),
        lineage=RecoveryLineage(**dict(descriptor["lineage"])),
        reserved_member=_required_string(descriptor, "reserved_successor_name"),
        admission_request_id=_required_string(descriptor, "admission_request_id"),
        admission_identity=fingerprint,
        workspace_num=int(descriptor["workspace_num"]),
        expected_owner_pid=_positive_int(descriptor.get("expected_claim_owner_pid")),
        resolver_pid=int(descriptor["resolver_pid"]),
        resolver_process_identity_token=_string_or_none(
            descriptor.get("resolver_process_identity_token")
        ),
        prompt_digest=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        attempt_revision=int(descriptor["attempt_revision"]),
    )


def _target_available(target: str) -> tuple[bool, str | None]:
    from sase.llm_provider.model_alias_resolution_types import (
        resolved_target_is_available,
    )
    from sase.llm_provider.provider_disable_peek import peek_active_provider_disables

    try:
        model_ref, _effort = _split_model_effort(target)
        provider, separator, model = model_ref.partition("/")
        if not separator or not provider or not model:
            return False, "recovery target is not a concrete provider/model"
        disables = peek_active_provider_disables()
        if provider in disables:
            return False, f"provider {provider!r} is disabled"
        if not resolved_target_is_available(
            f"{provider}/{model}", provider_disables=disables
        ):
            return False, f"provider/model {provider}/{model} is unavailable"
    except Exception as exc:  # noqa: BLE001 - unavailable facts fail closed
        return False, f"could not revalidate pinned recovery target: {exc}"
    return True, None


def _ledgerless_admission_states(bundle_dir: Path) -> dict[str, dict[str, Any]]:
    """Return the latest typed admission states without mutating the journal."""
    from sase.core.agent_launch_facade import reconcile_admission_journal

    return reconcile_admission_journal(read_journal(admission_dir(bundle_dir)))


def _bundle_dir_for_request(request_id: str) -> Path:
    from sase.core.paths import sase_subdir

    _validate_request_id(request_id)
    return sase_subdir(TYPED_LAUNCHES_SUBDIR) / request_id


def _missing_descriptor_dispatcher() -> Callable[..., Any]:
    def missing(
        *args: Any, **kwargs: Any
    ) -> tuple[bool, None, str, list[Any], dict[str, str]]:
        del args, kwargs
        return (
            False,
            None,
            "hijack recovery typed request is missing its durable descriptor",
            [],
            {"receipt_state": "rejected"},
        )

    return missing


def _validate_descriptor_fields(descriptor: Mapping[str, Any]) -> None:
    if descriptor.get("schema_version") != RECOVERY_ADMISSION_SCHEMA_VERSION:
        raise ValueError("unsupported recovery admission descriptor schema")
    for field in (
        "hijack_id",
        "action",
        "target",
        "prompt",
        "reserved_successor_name",
        "session_base",
        "project_name",
        "workspace_dir",
        "launch_identity",
        "admission_request_id",
        "launch_submitted_at",
    ):
        _required_string(descriptor, field)
    _validate_request_id(_required_string(descriptor, "admission_request_id"))
    workspace_num = descriptor.get("workspace_num")
    if (
        not isinstance(workspace_num, int)
        or isinstance(workspace_num, bool)
        or workspace_num <= 0
    ):
        raise ValueError("recovery admission requires a positive fixed workspace")
    if _positive_int(descriptor.get("resolver_pid")) is None:
        raise ValueError("recovery admission requires a positive resolver pid")
    attempt_revision = descriptor.get("attempt_revision")
    if (
        not isinstance(attempt_revision, int)
        or isinstance(attempt_revision, bool)
        or attempt_revision <= 0
    ):
        raise ValueError("recovery admission requires a positive attempt revision")
    lineage = descriptor.get("lineage")
    if not isinstance(lineage, Mapping):
        raise ValueError("recovery admission descriptor has no lineage")
    RecoveryLineage(**dict(lineage))


def _descriptor_digest(descriptor: Mapping[str, Any]) -> str:
    body = {
        key: value
        for key, value in descriptor.items()
        if key
        not in {
            "descriptor_digest",
            "dispatch_fingerprint",
            "logical_id",
            "plan_digest",
            "typed_plan",
        }
    }
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _split_model_effort(target: str) -> tuple[str, str | None]:
    from sase.macro.effort import split_model_effort

    model, effort = split_model_effort(target)
    return str(model), str(effort) if effort is not None else None


def _required_string(value: Mapping[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise ValueError(f"recovery admission descriptor requires {key}")
    return result.strip()


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _validate_request_id(request_id: str) -> None:
    if not _REQUEST_ID_PATTERN.fullmatch(request_id):
        raise ValueError("recovery admission request id is not a safe path component")


__all__ = [
    "RECOVERY_ADMISSION_METADATA_KEY",
    "RECOVERY_ADMISSION_SCHEMA_VERSION",
    "RECOVERY_ADMISSION_SOURCE_SURFACE",
    "cancel_recovery_admission_request",
    "cancel_recovery_admission_for_rollback",
    "dispatch_recovery_admission",
    "is_hijack_recovery_typed_request",
    "make_hijack_recovery_agent_dispatcher",
    "observe_recovery_admission",
    "persist_prepared_recovery_descriptor",
    "prepare_recovery_admission_descriptor",
    "remove_prepared_recovery_descriptor",
    "resume_recovery_admission",
]
