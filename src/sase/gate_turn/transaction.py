"""Ordered creation transaction for gate-turn backed gates.

This module is the public entry point and owns the ordered publication and
replay steps. Creator identity, request normalization, and replay
preconditions live in the ``_transaction_*`` sibling modules.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sase.agent.gate_intent import begin_gate_intent, clear_gate_intent
from sase.axe.run_agent_helpers_artifacts import update_meta_fields
from sase.finalizers.owned_turn import finalizer_owned_turn_is_active
from sase.gate_turn import naming
from sase.gate_turn._transaction_creator import (
    CreatorContext,
    creator_context_from_persisted,
    resolve_creator,
    resolve_project_name,
)
from sase.gate_turn._transaction_replay import (
    replay_claim_already_applied,
    validate_replay_identity,
)
from sase.gate_turn._transaction_spec import (
    gate_label,
    gate_reason,
    spec_from_request,
    stamp_pending_shell_on_spec,
)
from sase.gate_turn.lane_lock import gate_lane_lock
from sase.gate_turn.member import create_gate_turn_member
from sase.gate_turn.models import (
    GateTurnError,
    GateTurnRecord,
)
from sase.gate_turn.settlement import settle_gate_turn
from sase.gate_turn.start_claim import (
    GateClaimMove,
    move_gate_turn_claim,
    restore_gate_turn_claim,
)
from sase.gate_turn.store import (
    find_gate_turn_by_gate_id,
    has_any_gate_turn,
    read_gate_turn_marker,
)
from sase.notification_gates.model_request import GateSpec
from sase.notification_gates.model_results import GateCreationResult
from sase.notification_gates.service import create_gate

_FINALIZER_OWNED_TURN_ERROR = (
    "gate turns cannot be created from a host finalizer turn: this turn cannot "
    "end the agent run, so the gate could never hand off. Finish the finalizer's "
    "task in this turn, or report the blocker in your response so the host "
    "records the failure."
)


@dataclass(frozen=True)
class GateTurnCreation:
    """Result of creating a gate turn and its gate."""

    gate: GateCreationResult
    record: GateTurnRecord
    project_file: str | None
    claim_move: GateClaimMove | None
    cl_name: str | None

    @property
    def should_handoff(self) -> bool:
        """Return whether the creator should hand off to the gate turn."""
        return not self.record.is_terminal

    def to_dict(self) -> dict[str, Any]:
        """Return the CLI descriptor with additive gate-turn metadata."""
        payload = self.gate.to_dict()
        payload["gate_turn"] = {
            "gate_id": self.record.gate_id,
            "member_agent_name": self.record.member_agent_name,
            "artifacts_dir": self.record.artifacts_dir,
            "state": self.record.gate_state,
            "workspace_policy": self.record.workspace_policy,
        }
        return payload


def create_gate_turn(
    request: Mapping[str, Any] | GateSpec,
    *,
    before_auto_settle: Callable[[GateTurnRecord, GateCreationResult], None]
    | None = None,
    frozen_auto: Mapping[str, Any] | None = None,
) -> GateTurnCreation:
    """Create a gate-turn member, then create the durable gate.

    This is the immediate compatibility wrapper: it resolves the creator
    from the live environment, stamps a gate-intent marker, and publishes.
    Staged adoption calls :func:`publish_gate_turn` with persisted creator
    context and never writes an intent marker.
    """
    if finalizer_owned_turn_is_active():
        raise GateTurnError(_FINALIZER_OWNED_TURN_ERROR)
    spec = spec_from_request(request)
    if spec.turn is None:
        raise GateTurnError("gate turn creation requires a shell block")
    begin_gate_intent(spec.kind, request_id=spec.request_id)

    try:
        creator = resolve_creator(resolve_project_name())
        creation = publish_gate_turn(
            spec,
            creator=creator,
            before_auto_settle=before_auto_settle,
            frozen_auto=frozen_auto,
        )
    except Exception:
        clear_gate_intent()
        raise

    if not creation.should_handoff:
        clear_gate_intent()
    return creation


def publish_gate_turn(
    spec: GateSpec,
    *,
    creator: CreatorContext,
    before_auto_settle: Callable[[GateTurnRecord, GateCreationResult], None]
    | None = None,
    frozen_auto: Mapping[str, Any] | None = None,
    resource_bytes: Mapping[str, bytes] | None = None,
) -> GateTurnCreation:
    """Run the ordered publication transaction with explicit creator context.

    The publisher alone creates the gate member, transfers or releases its
    workspace claim, materializes the bundle, publishes the notification,
    and pulses watchers. Request-id replay validates identity and payload,
    then finishes any missing claim, bundle, or notification work under the
    original member instead of allocating another suffix or moving the
    claim twice.
    """
    turn = spec.turn
    if turn is None:
        raise GateTurnError("gate turn publication requires a shell block")
    assert spec.request_id is not None

    project_name = creator.project_name
    with gate_lane_lock(project_name, creator.durable_lane):
        replay = find_gate_turn_by_gate_id(project_name, spec.request_id)
        if replay is not None:
            return _finish_existing_gate_turn(
                spec,
                creator=creator,
                replay=replay,
                before_auto_settle=before_auto_settle,
                frozen_auto=frozen_auto,
                resource_bytes=resource_bytes,
            )

        suffix = turn.suffix or naming.allocate_gate_suffix(
            creator.durable_lane,
            has_existing_gate=has_any_gate_turn(project_name, creator.durable_lane),
        )
        label = gate_label(spec, spec.request_id)
        artifacts_dir = create_gate_turn_member(
            project_name,
            creator.meta,
            lane=creator.durable_lane,
            suffix=suffix,
            prev_artifacts_timestamp=creator.timestamp,
            workspace_num=creator.workspace_num,
            gate_id=spec.request_id,
            gate_kind=spec.kind,
            label=label,
            reason=gate_reason(spec),
            creator_agent=creator.meta.get("name")
            if isinstance(creator.meta.get("name"), str)
            else creator.target_name,
            timeout_seconds=spec.gate_timeout_seconds or 0.0,
            request_fingerprint=None,
            turn=turn,
        )
        member_timestamp = os.path.basename(artifacts_dir.rstrip("/"))
        claim_move = move_gate_turn_claim(
            creator.project_file,
            creator.workspace_num,
            creator_pid=creator.runner_pid,
            artifacts_timestamp=member_timestamp,
            cl_name=creator.cl_name,
            workspace_policy=turn.workspace,
            creator_artifacts_timestamp=creator.timestamp,
        )
        _record_creator_claim(artifacts_dir, claim_move)
        if not claim_move.result.success:
            record = _read_required_record(project_name, artifacts_dir)
            settle_gate_turn(
                record,
                gate_state="failed",
                reason=claim_move.result.error or "workspace claim move failed",
                creator_live=True,
            )
            raise GateTurnError(
                claim_move.result.error or "workspace claim move failed"
            )

        try:
            stamp_pending_shell_on_spec(
                spec,
                member_artifacts_dir=artifacts_dir,
                member_timestamp=member_timestamp,
            )
            gate_result = _create_durable_gate(
                spec,
                frozen_auto=frozen_auto,
                resource_bytes=resource_bytes,
            )
        except BaseException:
            record = _read_required_record(project_name, artifacts_dir)
            settle_gate_turn(
                record,
                gate_state="failed",
                reason="gate creation failed",
                creator_live=True,
            )
            restore_gate_turn_claim(
                creator.project_file,
                move=claim_move,
                cl_name=creator.cl_name,
            )
            raise

        record = _record_with_gate_result(
            project_name,
            _read_required_record(project_name, artifacts_dir),
            gate_result,
        )
        if gate_result.auto_resolution.get("state") == "resolved":
            if before_auto_settle is not None:
                before_auto_settle(record, gate_result)
                record = _read_required_record(project_name, artifacts_dir)
            record = settle_gate_turn(
                record,
                gate_state="answered",
                reason="auto-resolved",
                creator_live=True,
            )
            # The creator is still running in the workspace ``move_gate_turn_claim``
            # retitled to this gate turn above; restore its original claim now
            # that settlement (under ``creator_live=True``) left it untouched,
            # rather than leaking it as an unowned gate-turn claim.
            restore_gate_turn_claim(
                creator.project_file,
                move=claim_move,
                cl_name=creator.cl_name,
            )
        creation = GateTurnCreation(
            gate=gate_result,
            record=record,
            project_file=creator.project_file,
            claim_move=claim_move,
            cl_name=creator.cl_name,
        )
        _pulse_after_gate_visible(creation.record.project_name)
        return creation


def _finish_existing_gate_turn(
    spec: GateSpec,
    *,
    creator: CreatorContext,
    replay: GateTurnRecord,
    before_auto_settle: Callable[[GateTurnRecord, GateCreationResult], None] | None,
    frozen_auto: Mapping[str, Any] | None,
    resource_bytes: Mapping[str, bytes] | None,
) -> GateTurnCreation:
    """Resume a partially published member under its original request id."""
    validate_replay_identity(spec, creator, replay)
    if (
        replay.gate_state == "failed"
        and not replay.bundle_path
        and not replay.notification_id
    ):
        raise GateTurnError(
            "request id already belongs to a failed gate turn that never published"
        )
    claim_move = _repair_replay_claim(spec, creator, replay)
    member_timestamp = replay.timestamp or os.path.basename(
        replay.artifacts_dir.rstrip("/")
    )
    stamp_pending_shell_on_spec(
        spec,
        member_artifacts_dir=replay.artifacts_dir,
        member_timestamp=member_timestamp,
    )
    try:
        gate_result = _create_durable_gate(
            spec,
            frozen_auto=frozen_auto,
            resource_bytes=resource_bytes,
        )
    except BaseException:
        if claim_move is not None and not replay.is_terminal:
            record = _read_required_record(creator.project_name, replay.artifacts_dir)
            settle_gate_turn(
                record,
                gate_state="failed",
                reason="gate creation failed",
                creator_live=True,
            )
            restore_gate_turn_claim(
                creator.project_file,
                move=claim_move,
                cl_name=creator.cl_name,
            )
        raise

    record = _record_with_gate_result(creator.project_name, replay, gate_result)
    if (
        not record.is_terminal
        and gate_result.auto_resolution.get("state") == "resolved"
    ):
        if before_auto_settle is not None:
            before_auto_settle(record, gate_result)
            record = _read_required_record(creator.project_name, replay.artifacts_dir)
        record = settle_gate_turn(
            record,
            gate_state="answered",
            reason="auto-resolved",
            creator_live=True,
        )
        if claim_move is not None:
            restore_gate_turn_claim(
                creator.project_file,
                move=claim_move,
                cl_name=creator.cl_name,
            )
    creation = GateTurnCreation(
        gate=gate_result,
        record=record,
        project_file=creator.project_file,
        claim_move=claim_move,
        cl_name=creator.cl_name,
    )
    _pulse_after_gate_visible(creation.record.project_name)
    return creation


def _repair_replay_claim(
    spec: GateSpec, creator: CreatorContext, replay: GateTurnRecord
) -> GateClaimMove | None:
    """Finish a pending claim transfer or release without moving twice."""
    turn = spec.turn
    if turn is None or replay.is_terminal:
        return None
    if replay_claim_already_applied(creator, replay, turn.workspace):
        return None
    claim_move = move_gate_turn_claim(
        creator.project_file,
        creator.workspace_num,
        creator_pid=creator.runner_pid,
        artifacts_timestamp=replay.timestamp
        or os.path.basename(replay.artifacts_dir.rstrip("/")),
        cl_name=creator.cl_name,
        workspace_policy=turn.workspace,
        creator_artifacts_timestamp=creator.timestamp,
    )
    if not claim_move.result.success:
        record = _read_required_record(creator.project_name, replay.artifacts_dir)
        settle_gate_turn(
            record,
            gate_state="failed",
            reason=claim_move.result.error or "workspace claim move failed",
            creator_live=True,
        )
        raise GateTurnError(claim_move.result.error or "workspace claim move failed")
    if claim_move.creator_claim is None:
        return None
    _record_creator_claim(replay.artifacts_dir, claim_move)
    return claim_move


def _pulse_after_gate_visible(project_name: str | None) -> None:
    """Nudge artifact watchers after the gate member and notification exist."""
    from sase.turns.settlement import touch_turn_refresh_pulse

    touch_turn_refresh_pulse(project_name)


def _create_durable_gate(
    spec: GateSpec,
    *,
    frozen_auto: Mapping[str, Any] | None,
    resource_bytes: Mapping[str, bytes] | None,
) -> GateCreationResult:
    """Call ``create_gate`` without extra kwargs when the immediate path is used.

    Existing tests patch ``create_gate`` with a one-argument callable. The
    staged publication path is the only caller that supplies frozen auto
    state or snapshot bytes.
    """
    if frozen_auto is None and resource_bytes is None:
        return create_gate(spec)
    return create_gate(
        spec,
        frozen_auto=frozen_auto,
        resource_bytes=resource_bytes,
    )


def _record_with_gate_result(
    project_name: str,
    record: GateTurnRecord,
    result: GateCreationResult,
) -> GateTurnRecord:
    update_meta_fields(
        record.artifacts_dir,
        {
            "gate_bundle_path": str(result.bundle_path),
            "gate_notification_id": result.notification_id,
            "gate_request_fingerprint": result.hashes.get("request"),
        },
    )
    return read_gate_turn_marker(project_name, record.artifacts_dir) or record


def _record_creator_claim(artifacts_dir: str, move: GateClaimMove) -> None:
    claim = move.creator_claim
    if claim is None:
        return
    update_meta_fields(
        artifacts_dir,
        {
            "gate_creator_claim_pid": claim.pid,
            "gate_creator_claim_workflow": claim.workflow,
            "gate_creator_claim_cl_name": claim.cl_name,
            "gate_creator_claim_artifacts_timestamp": claim.artifacts_timestamp,
            "gate_creator_claim_pinned": claim.pinned,
        },
    )


def _read_required_record(project_name: str, artifacts_dir: str) -> GateTurnRecord:
    record = read_gate_turn_marker(project_name, artifacts_dir)
    if record is None:
        raise GateTurnError(f"gate turn member missing at {artifacts_dir}")
    return record


__all__ = [
    "GateTurnCreation",
    "create_gate_turn",
    "creator_context_from_persisted",
    "publish_gate_turn",
]
