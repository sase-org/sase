"""Prepare and persist immutable recovery admission descriptors."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.hijack._recovery_admission_common import (
    RECOVERY_ADMISSION_SCHEMA_VERSION,
    canonical_json,
    descriptor_digest,
    positive_int,
    required_string,
    split_model_effort,
    string_or_none,
    validate_descriptor_fields,
    validate_request_id,
)
from sase.agent.hijack.recovery_successor import RecoveryLineage
from sase.core.agent_launch_facade import dispatch_fingerprint
from sase.core.agent_launch_wire import (
    AgentUnitWire,
    launch_plan_from_dict,
)

__all__ = [
    "persist_prepared_recovery_descriptor",
    "prepare_recovery_admission_descriptor",
    "remove_prepared_recovery_descriptor",
]


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
        "project_file": string_or_none(record.get("project_file")),
        "workspace_num": positive_int(record.get("workspace_num")),
        "workspace_dir": string_or_none(record.get("workspace_dir")),
        "expected_claim_owner_pid": positive_int(
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
    validate_descriptor_fields(descriptor)
    digest = descriptor_digest(descriptor)
    # This synthetic planner prompt carries the reserved identity and exact
    # model into the Rust admission fingerprint. The recovery dispatcher uses
    # the prepared prompt in metadata and never dispatches this marker text.
    plan_prompt = set_prompt_name("", reserved_successor_name)
    plan_prompt = set_prompt_model(plan_prompt, target)
    plan_prompt = f"{plan_prompt}\nSASE recovery descriptor {digest}"
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
    expected_model, expected_effort = split_model_effort(target)
    if payload.model != expected_model or payload.reasoning_effort != expected_effort:
        raise ValueError("typed recovery plan changed the pinned model or effort")
    fingerprint = dispatch_fingerprint(
        plan.content_digest,
        unit.logical_id,
        payload,
    )
    descriptor.update(
        descriptor_digest=digest,
        logical_id=unit.logical_id,
        typed_plan=plan_data,
        plan_digest=plan.content_digest,
        dispatch_fingerprint=fingerprint,
    )
    return descriptor


def persist_prepared_recovery_descriptor(descriptor: Mapping[str, Any]) -> Path:
    """Persist an inert draft so a post-CAS crash can materialize its request."""
    from sase.agent.launch_admission_store import read_json
    from sase.core.atomic_json import write_json_marker_atomic
    from sase.core.paths import sase_subdir
    from sase.notification_gates.durability import file_lock
    from sase.agent.hijack._recovery_admission_common import (
        RECOVERY_REQUESTS_SUBDIR,
    )

    request_id = required_string(descriptor, "admission_request_id")
    validate_request_id(request_id)
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
            if canonical_json(existing) != canonical_json(candidate):
                raise ValueError(
                    f"recovery request {request_id} already has different contents"
                )
            return path
        write_json_marker_atomic(path, candidate)
    return path


def remove_prepared_recovery_descriptor(request_id: str) -> None:
    """Remove an inert draft whose held-state CAS lost to another resolver."""
    from sase.core.paths import sase_subdir
    from sase.agent.hijack._recovery_admission_common import (
        RECOVERY_REQUESTS_SUBDIR,
    )

    validate_request_id(request_id)
    path = sase_subdir(RECOVERY_REQUESTS_SUBDIR) / f"{request_id}.json"
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return
