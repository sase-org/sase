"""Creating and reserving durable hijack latch requests."""

from __future__ import annotations

import math
import uuid
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack._latch_common import (
    current_time,
    observe_record,
    owner_identity_for,
    result,
    same_owner,
)
from sase.agent.hijack._stop_models import HijackTarget, StopDeps
from sase.agent.hijack.locks import acquire_hijack_lock


def request_latch(
    name: str,
    *,
    deps: StopDeps | None = None,
    hijack_id: str | None = None,
) -> dict[str, Any]:
    """Create or coalesce one latch for the currently occupying local member.

    The target-index lock covers the second occupant resolution, reservation,
    record creation, and transition to ``latched``. A later turn that reuses a
    session name or PID cannot inherit this request because member, artifact,
    and process identities must all match.
    """
    deps = deps or StopDeps()
    from sase.agent.hijack.facts import resolve_hijack_subject

    subject = resolve_hijack_subject(name, deps=deps)
    target = subject.target
    refusal = _validate_target(subject, target)
    if refusal is not None:
        return refusal
    assert target is not None
    owner_identity = owner_identity_for(target)
    if not owner_identity:
        return result(
            "ownership_uncertain",
            code="owner_identity_unavailable",
            message="the current owner process identity could not be verified; no latch was written",
        )
    target_key = _target_key(subject, target)
    new_id = hijack_id or _new_hijack_id(target.name)

    with acquire_hijack_lock(
        "target_index", ledger.target_index_lock_path(), timeout=10.0
    ):
        active = ledger.find_active_record_by_target_key(target_key)
        if active is not None:
            if not same_owner(active, target, owner_identity, target_key=target_key):
                return result(
                    "ownership_uncertain",
                    code="target_owner_changed",
                    message="this target key is reserved by a different member or process identity; retain custody and inspect the active record",
                    record=active,
                )
            return observe_record(
                active,
                target_key=target_key,
                boundary="request",
                target=target,
            )

        winner = ledger.claim_target_slot_locked(target_key, new_id)
        if winner != new_id:
            active = ledger.load_record(winner)
            if active is not None:
                if not same_owner(
                    active, target, owner_identity, target_key=target_key
                ):
                    return result(
                        "ownership_uncertain",
                        code="target_owner_changed",
                        message="the winning target reservation belongs to a different member or process identity",
                        record=active,
                    )
                return observe_record(
                    active,
                    target_key=target_key,
                    boundary="request",
                    target=target,
                )
            return result(
                "ownership_uncertain",
                code="target_reservation_uncertain",
                message="a target reservation exists but its record cannot be read; retain custody",
            )

        fresh_subject = resolve_hijack_subject(name, deps=deps)
        fresh_target = fresh_subject.target
        fresh_refusal = _validate_target(fresh_subject, fresh_target)
        fresh_identity = (
            None if fresh_target is None else owner_identity_for(fresh_target)
        )
        if (
            fresh_refusal is not None
            or fresh_target is None
            or fresh_subject.occupant_name != subject.occupant_name
            or _target_identity(fresh_target) != _target_identity(target)
            or fresh_identity != owner_identity
            or _target_key(fresh_subject, fresh_target) != target_key
        ):
            ledger.release_target_slot_locked(target_key, new_id)
            return result(
                "ownership_uncertain",
                code="occupant_changed",
                message="the occupying member or process identity changed while reserving the latch; nothing was applied",
            )

        target = fresh_target
        record = ledger.new_requested_record(
            hijack_id=new_id,
            agent_name=target.name,
            artifacts_dir=target.artifacts_dir,
            pid=target.pid,
            process_identity_token=owner_identity,
            project_file=None if target.is_home else target.project_file,
            workspace_num=target.workspace_num,
            workspace_dir=target.workspace_dir,
            expected_claim_owner_pid=target.claim_pid,
            session=target.agent_session,
            model_alias=target.model_alias,
            model_alias_trail=target.model_alias_trail,
            model_origin=target.model_origin,
            provider=target.provider,
            model=target.model,
            effort=target.effort,
            target_key=target_key,
            scope="llm",
        )
        record["prior_pin_state"] = bool(target.claim_pinned)
        created = False
        try:
            ledger.create_record(record)
            created = True
            latched = ledger.cas_advance_record(
                record,
                {
                    "event": ledger.HIJACK_EVENT_LATCH,
                    "owner_pid": int(target.pid or 0),
                    "owner_identity": owner_identity,
                    "latched_at": math.ceil(current_time(deps) * 1_000),
                },
            )
        except Exception as exc:
            if created:
                try:
                    ledger.hijack_record_path(new_id).unlink(missing_ok=True)
                except OSError:
                    pass
            ledger.release_target_slot_locked(target_key, new_id)
            return result(
                "error",
                code="latch_request_failed",
                message=f"could not durably request the hijack latch: {exc}",
            )
        return observe_record(
            latched,
            target_key=target_key,
            boundary="request",
            target=target,
        )


def _validate_target(
    subject: Any, target: HijackTarget | None
) -> dict[str, Any] | None:
    if (
        target is None
        or subject.is_remote
        or subject.is_bulk
        or subject.is_named_proc
        or subject.is_clan_container
        or (target is not None and (target.is_monitor_turn or target.is_gate_turn))
    ):
        return result(
            "refused",
            code="unsupported_target",
            message="a latch requires a local, directly addressable agent member",
        )
    if (
        target.is_home
        or target.workspace_num is None
        or target.claim_pid is None
        or target.pid is None
    ):
        return result(
            "refused",
            code="numbered_claim_required",
            message="a latch requires a live member with an exact numbered workspace claim",
        )
    selected = subject.selected
    if selected is None or selected.settled or not selected.process_alive:
        return result(
            "refused",
            code="owner_not_live",
            message="the selected member is no longer a live owner; no latch was written",
        )
    if "hijack" not in target.capabilities:
        return result(
            "refused",
            code="hijack_capability_required",
            message="the selected member does not advertise hijack capability",
        )
    return None


def _target_key(subject: Any, target: HijackTarget) -> str:
    session = getattr(subject, "session", None)
    base_name = getattr(session, "base_name", None)
    owner_name = base_name or target.agent_session or target.name
    project_file = None if target.is_home else target.project_file
    return ledger.target_key_for(project_file, str(owner_name))


def _target_identity(target: HijackTarget) -> tuple[Any, ...]:
    return (
        target.name,
        target.project_file,
        target.artifacts_timestamp,
        target.artifacts_dir,
        target.pid,
        target.claim_pid,
        target.workspace_num,
        target.agent_session,
        target.is_home,
    )


def _new_hijack_id(name: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in name
    ).strip("_")
    return f"hijack-{cleaned or 'agent'}-{uuid.uuid4().hex[:12]}"
