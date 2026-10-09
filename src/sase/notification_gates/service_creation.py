"""Durable gate creation lifecycle for notification gates.

Owns :func:`create_gate` (re-exported through the ``service`` facade) and
the start/resume/resolve/complete lifecycle behind it. Envelope assembly
lives in :mod:`sase.notification_gates.service_assembly`, automatic-gate
evaluation in :mod:`sase.notification_gates.service_evaluation`, and the
shared journal/hash/lookup primitives in
:mod:`sase.notification_gates._service_shared`.
"""

from __future__ import annotations

import dataclasses
import shutil
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from sase.notification_gates._service_shared import (
    find_notification,
    notification_exists,
    optional_json,
    source_hashes,
    spec_fingerprint,
    write_journal,
)
from sase.notification_gates.durability import (
    atomic_write_json,
    file_lock,
    fsync_dir,
    materialize_resource,
    read_json_object,
    sha256_file,
)
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import GateCreationResult, GateError, GateSpec
from sase.notification_gates.paths import (
    bundle_paths,
    interaction_requests_dir,
    owned_resource_path,
)
from sase.notification_gates.registry import (
    GateAdapter,
    adapter_for_kind,
    validate_gate_spec,
)
from sase.notification_gates.service_assembly import (
    build_gate_creation_result,
    build_gate_envelope,
    build_gate_notification,
)
from sase.notification_gates.service_evaluation import effective_auto_state


def create_gate(spec_value: Mapping[str, Any] | GateSpec) -> GateCreationResult:
    """Create or repair one durable gate, idempotently by request id."""
    spec = (
        spec_value
        if isinstance(spec_value, GateSpec)
        else GateSpec.from_mapping(spec_value)
    )
    adapter = adapter_for_kind(spec.kind)
    validate_gate_spec(spec, adapter)
    request_id = spec.request_id or f"{adapter.kind}-{uuid4()}"
    paths = bundle_paths(adapter.kind, request_id)
    lock_path = (
        interaction_requests_dir() / ".locks" / adapter.kind / f"{request_id}.lock"
    )
    with file_lock(lock_path):
        if paths.creation_result.is_file():
            return GateCreationResult.from_mapping(
                read_json_object(paths.creation_result)
            )
        journal = optional_json(paths.journal)
        if journal.get("state") in {"initializing", "failed"}:
            shutil.rmtree(paths.root, ignore_errors=True)
            journal = {}

        if journal:
            return _resume_gate_creation(spec, adapter, paths, journal)
        return _start_gate_creation(spec, adapter, paths)


def _start_gate_creation(
    spec: GateSpec, adapter: GateAdapter, paths: Any
) -> GateCreationResult:
    effective, decision, policy_block, auto_execute = effective_auto_state(
        spec, adapter, request_id=paths.root.name
    )
    notification_id = None if auto_execute else str(uuid4())
    paths.root.mkdir(parents=True, exist_ok=False)
    fsync_dir(paths.root.parent)
    write_journal(
        paths.journal,
        state="initializing",
        request_id=paths.root.name,
        kind=adapter.kind,
        notification_id=notification_id,
    )
    published = False
    try:
        for resource in effective.resources:
            materialize_resource(paths.root, resource)
        resource_hashes = {
            resource.path: sha256_file(owned_resource_path(paths.root, resource.path))
            for resource in effective.resources
        }
        envelope = build_gate_envelope(
            effective,
            adapter,
            request_id=paths.root.name,
            notification_id=notification_id,
            resource_hashes=resource_hashes,
            policy_block=policy_block,
        )
        fingerprint = spec_fingerprint(effective, adapter, resource_hashes)
        atomic_write_json(paths.request, envelope)
        write_journal(
            paths.journal,
            state="bundle_written",
            request_id=paths.root.name,
            kind=adapter.kind,
            notification_id=notification_id,
            spec_sha256=fingerprint,
        )
        if auto_execute:
            return _resolve_auto_gate(
                effective,
                adapter,
                paths,
                envelope,
                fingerprint,
                decision,
                policy_block,
            )

        assert notification_id is not None
        write_journal(
            paths.journal,
            state="notification_prepared",
            request_id=paths.root.name,
            kind=adapter.kind,
            notification_id=notification_id,
            spec_sha256=fingerprint,
        )
        notification = build_gate_notification(
            effective, adapter, paths, notification_id
        )
        from sase.notifications.store import append_notification_strict

        append_notification_strict(notification)
        published = True
        return _complete_manual_gate(
            effective,
            adapter,
            paths,
            envelope,
            fingerprint,
            notification_id,
            policy_block,
        )
    except BaseException:
        row_exists = notification_id is not None and notification_exists(
            notification_id
        )
        if published or row_exists:
            _compensate_published_gate(notification_id, paths)
        else:
            shutil.rmtree(paths.root, ignore_errors=True)
        raise


def _persisted_policy_block(envelope: dict[str, Any]) -> dict[str, Any] | None:
    """Return the durable policy snapshot from a persisted gate envelope, if any."""
    try:
        auto = envelope.get("auto")
        if not isinstance(auto, dict):
            return None
        policy = auto.get("policy")
        return dict(policy) if isinstance(policy, dict) and policy else None
    except Exception:
        return None


def _effective_from_persisted_policy(
    spec: GateSpec, policy_block: dict[str, Any]
) -> tuple[GateSpec, dict[str, Any], dict[str, Any], bool]:
    """Rebuild the effective creation state from a persisted policy snapshot.

    Reuses the first evaluation's decision instead of evaluating again, so
    journal recovery never appends a duplicate decision-log row and the
    request/result/response policy identity stays consistent.
    """
    decision = dict(policy_block)
    auto_execute = bool(spec.auto.enabled) and decision.get("outcome") == "auto"
    if auto_execute:
        return spec, decision, dict(policy_block), True
    return (
        dataclasses.replace(
            spec,
            auto=dataclasses.replace(
                spec.auto, enabled=False, argument=None, policy=spec.auto.policy
            ),
        ),
        decision,
        dict(policy_block),
        False,
    )


def _resume_gate_creation(
    spec: GateSpec, adapter: GateAdapter, paths: Any, journal: dict[str, Any]
) -> GateCreationResult:
    state = journal.get("state")
    if state not in {"bundle_written", "notification_prepared"}:
        raise GateError(
            "invalid_creation_state", str(paths.journal), f"unknown gate state: {state}"
        )
    envelope = read_json_object(paths.request)
    persisted = _persisted_policy_block(envelope)
    if persisted is not None:
        effective, decision, policy_block, auto_execute = (
            _effective_from_persisted_policy(spec, persisted)
        )
    else:
        effective, decision, policy_block, auto_execute = effective_auto_state(
            spec, adapter, request_id=paths.root.name
        )
    candidate_fingerprint = spec_fingerprint(
        effective, adapter, source_hashes(effective)
    )
    if candidate_fingerprint != journal.get("spec_sha256"):
        raise GateError(
            "request_id_conflict",
            paths.root.name,
            "request id already belongs to a different gate specification",
        )
    if auto_execute:
        return _resolve_auto_gate(
            effective,
            adapter,
            paths,
            envelope,
            candidate_fingerprint,
            decision,
            policy_block,
        )
    notification_id = journal.get("notification_id")
    if not isinstance(notification_id, str) or not notification_id:
        raise GateError(
            "invalid_creation_state",
            str(paths.journal),
            "manual gate journal has no notification id",
        )
    if notification_exists(notification_id):
        from sase.notifications.pending_actions import register_notification

        notification = find_notification(notification_id)
        assert notification is not None
        register_notification(notification)
    else:
        notification = build_gate_notification(
            effective, adapter, paths, notification_id
        )
        from sase.notifications.store import append_notification_strict

        append_notification_strict(notification)
    return _complete_manual_gate(
        effective,
        adapter,
        paths,
        envelope,
        candidate_fingerprint,
        notification_id,
        policy_block,
    )


def _resolve_auto_gate(
    spec: GateSpec,
    adapter: GateAdapter,
    paths: Any,
    envelope: dict[str, Any],
    fingerprint: str,
    decision: dict[str, Any],
    policy_block: dict[str, Any],
) -> GateCreationResult:
    selected_option_ids = tuple(decision.get("option_ids") or ())

    gate_turn = None
    if spec.shell is not None:
        from sase.gate_turn.store import find_gate_turn_by_gate_id

        gate_turn = find_gate_turn_by_gate_id(None, paths.root.name)

    execution_kwargs: dict[str, Any] = {}
    if gate_turn is not None:
        from sase.gate_turn.log import bind_gate_turn_execution_callbacks

        execution_kwargs = bind_gate_turn_execution_callbacks(
            gate_turn.artifacts_dir
        ).as_kwargs()

    execution = execute_gate_selection(
        paths.root,
        selected_option_ids,
        adapter.automatic_input(spec, decision),
        source="auto_resolution",
        **execution_kwargs,
    )
    _write_auto_policy_response(paths, adapter.kind, policy_block)

    if gate_turn is not None:
        from sase.gate_turn.settlement import settle_gate_turn

        # `creator_live=True`: creation-time auto-resolution always runs
        # inline in the creating agent's own process/turn, which already
        # owns the lane and workspace (and, via `prev_artifacts_timestamp`
        # pointing at that same creator, the agent session's runner-slot claim) --
        # never a separate answering process. No follow-up may launch and
        # no claim may be disposed of here.
        settle_gate_turn(
            gate_turn,
            gate_state="answered",
            reason="gate resolved automatically",
            creator_live=True,
        )

    result = build_gate_creation_result(
        spec,
        adapter,
        paths,
        envelope,
        notification_id=None,
        auto_state="resolved",
        auto_selected_option_ids=selected_option_ids,
        policy_block=policy_block,
    )
    atomic_write_json(paths.creation_result, result.to_dict())
    write_journal(
        paths.journal,
        state="auto_resolved",
        request_id=paths.root.name,
        kind=adapter.kind,
        notification_id=None,
        spec_sha256=fingerprint,
        response_selected_option_ids=execution.response.get("selected_option_ids"),
    )
    return result


def _write_auto_policy_response(
    paths: Any, kind: str, policy_block: dict[str, Any]
) -> None:
    """Record the deciding policy block on an automatic gate's response.

    Every plan, epic, and question gate created by an agent carries the
    block that decided it; ``response.json`` carries it for automatic
    outcomes.
    """
    from sase.autonomy.gates import POLICY_BLOCK_KINDS

    if kind not in POLICY_BLOCK_KINDS:
        return
    try:
        response = read_json_object(paths.response)
    except GateError:
        return
    if not isinstance(response, dict):
        return
    response["policy"] = dict(policy_block)
    atomic_write_json(paths.response, response)


def _complete_manual_gate(
    spec: GateSpec,
    adapter: GateAdapter,
    paths: Any,
    envelope: dict[str, Any],
    fingerprint: str,
    notification_id: str,
    policy_block: dict[str, Any],
) -> GateCreationResult:
    result = build_gate_creation_result(
        spec,
        adapter,
        paths,
        envelope,
        notification_id=notification_id,
        auto_state="disabled",
        auto_selected_option_ids=None,
        policy_block=policy_block,
    )
    atomic_write_json(paths.creation_result, result.to_dict())
    write_journal(
        paths.journal,
        state="complete",
        request_id=paths.root.name,
        kind=adapter.kind,
        notification_id=notification_id,
        spec_sha256=fingerprint,
    )
    return result


def _compensate_published_gate(notification_id: str | None, paths: Any) -> None:
    if notification_id is None:
        return
    from sase.notifications.pending_actions import unregister_notification
    from sase.notifications.store import mark_dismissed

    unregister_notification(notification_id)
    mark_dismissed(notification_id)
    try:
        write_journal(
            paths.journal,
            state="failed",
            request_id=paths.root.name,
            kind=paths.root.parent.name,
            notification_id=notification_id,
        )
    except OSError:
        pass


__all__ = ["create_gate"]
