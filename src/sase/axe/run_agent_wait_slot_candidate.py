"""Runner-slot candidate decisions: parking markers and claim publication.

These helpers build the candidate record Rust's capacity engine evaluates,
interpret its authoritative decision, and persist the side effects of that
decision (a republished ``waiting.json`` queue marker, or a claimed slot's
ownership fields) for ``_try_claim_runner_slot``.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.axe.run_agent_wait_markers import (
    queue_capacity_marker_fields,
    remove_waiting_marker,
    write_waiting_marker,
)
from sase.axe.run_agent_wait_slot_state import (
    RunnerSlotAdmissionError,
    invalid_queue_weight_error,
    valid_queue_weight,
)
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.core.agent_hold_facade import candidate_created_at_from_timestamp
from sase.core.runner_slots import notify_runner_slot_state_changed


def abandon_unclaimed_attempt(artifacts_dir: str) -> tuple[None, bool]:
    """Drop any waiting marker so the caller can proceed without a claim."""
    waiting_path = Path(artifacts_dir) / "waiting.json"
    existed = waiting_path.is_file()
    remove_waiting_marker(artifacts_dir)
    if existed:
        notify_runner_slot_state_changed()
    return None, False


def park_for_unavailable_limit(
    *,
    artifacts_dir: str,
    cl_name: str,
    timestamp: str,
    waiting_data: dict[str, Any] | None,
    priority: int,
    priority_explicit: bool,
    queue_weight: float,
    queue_weight_explicit: bool,
    queue_capacity: int | None,
    queue_capacity_explicit: bool,
    error: Exception,
) -> tuple[None, bool]:
    """Republish the queue marker when the runner limit cannot be read."""
    requested_at = (
        waiting_data.get("slot_requested_at") if waiting_data is not None else None
    )
    if not isinstance(requested_at, str) or not requested_at:
        requested_at = datetime.now(UTC).isoformat()
    marker = dict(waiting_data or {})
    marker_queue_capacity = queue_capacity if queue_capacity is not None else 0
    marker.update(
        {
            "patch_name": cl_name,
            "cl_name": cl_name,
            "timestamp": timestamp,
            **queue_capacity_marker_fields(
                marker_queue_capacity,
                explicit=queue_capacity_explicit,
            ),
            "wait_priority": priority,
            "wait_priority_explicit": priority_explicit,
            "queue_weight": queue_weight,
            "queue_weight_explicit": queue_weight_explicit,
            "slot_requested_at": requested_at,
            "runner_limit_unavailable": str(error),
        }
    )
    parked = waiting_data is None or "slot_requested_at" not in waiting_data
    if waiting_data != marker:
        write_waiting_marker(artifacts_dir, marker)
    return None, parked


def hold_deadlock_armer_record(
    *,
    held_by: str,
    candidate_agent_name: str | None,
    active_holds: list[dict[str, Any]],
    records: list[AgentArtifactRecordWire],
    candidate: Mapping[str, Any] | None = None,
) -> AgentArtifactRecordWire | None:
    """Return the armer's own record when the hold is a mutual deadlock.

    A hold blocks *this* candidate; this returns the armer's scanned
    record only when the armer is itself pre-run (WAITING/QUEUED, never a
    RUNNING or done row -- those have left admission for good) and is
    blocked on the very candidate it holds, directly or transitively
    through the relevant wait set. Graph reachability, identity matching,
    and hood edges live in Rust. The TTL is still the forward-progress
    guarantee; this only surfaces the deadlock, it never breaks it.
    """
    candidate_name = _candidate_deadlock_name(candidate_agent_name, candidate)
    if not candidate_name:
        return None
    hold = next(
        (
            hold
            for hold in active_holds
            if isinstance(hold.get("armer"), Mapping)
            and hold["armer"].get("key") == held_by
        ),
        None,
    )
    if hold is None:
        return None
    armer = hold.get("armer")
    if not isinstance(armer, Mapping) or armer.get("kind") != "agent":
        return None
    marker_path = armer.get("done_marker_path")
    if not isinstance(marker_path, str) or not marker_path:
        return None
    armer_dir = str(Path(marker_path).parent)
    by_dir = {record.artifact_dir: record for record in records}
    armer_record = by_dir.get(armer_dir)
    if armer_record is None or armer_record.running is not None:
        return None
    if armer_record.has_done_marker:
        return None
    from sase.core.rust import require_rust_binding

    nodes = [_hold_deadlock_wait_node_wire(record) for record in records]
    _apply_hold_deadlock_identity(nodes, records)
    reaches = require_rust_binding("agent_hold_deadlock_reaches")
    if reaches(
        armer_dir,
        _hold_deadlock_candidate_wire(
            candidate_name,
            candidate,
            records,
            by_dir,
        ),
        nodes,
    ):
        return armer_record
    return None


def _candidate_deadlock_name(
    candidate_agent_name: str | None,
    candidate: Mapping[str, Any] | None,
) -> str | None:
    if candidate_agent_name:
        return candidate_agent_name
    if candidate is None:
        return None
    name = candidate.get("agent_name")
    return name if isinstance(name, str) and name else None


def _hold_deadlock_candidate_wire(
    candidate_agent_name: str,
    candidate: Mapping[str, Any] | None,
    records: list[AgentArtifactRecordWire],
    by_dir: Mapping[str, AgentArtifactRecordWire],
) -> dict[str, Any]:
    payload = dict(candidate or {})
    artifact_dir = payload.get("artifact_dir")
    record = by_dir.get(artifact_dir) if isinstance(artifact_dir, str) else None
    if record is None:
        record = next(
            (
                item
                for item in records
                if item.agent_meta is not None
                and item.agent_meta.name == candidate_agent_name
            ),
            None,
        )
    meta = None if record is None else record.agent_meta
    tribes = payload.get("tribes")
    tribe_values = [str(item) for item in tribes] if isinstance(tribes, list) else []
    tribe = payload.get("tribe")
    if isinstance(tribe, str) and tribe and tribe not in tribe_values:
        tribe_values.append(tribe)
    if not tribe_values and meta is not None:
        for value in (meta.tribe, meta.clan_tribe):
            if isinstance(value, str) and value and value not in tribe_values:
                tribe_values.append(value)
    family = payload.get("agent_family")
    if not isinstance(family, str) or not family:
        family = payload.get("family")
    if not isinstance(family, str) or not family:
        family = None if meta is None else meta.agent_family
    workflow = payload.get("workflow")
    if not isinstance(workflow, str) or not workflow:
        workflow = None if meta is None else meta.workflow_name
    clan = payload.get("clan")
    if not isinstance(clan, str) or not clan:
        clan = None if meta is None else meta.agent_clan
    timestamp = payload.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp:
        timestamp = None if record is None else record.timestamp
    if not isinstance(artifact_dir, str) or not artifact_dir:
        artifact_dir = None if record is None else record.artifact_dir
    return {
        "artifact_dir": artifact_dir,
        "agent_name": candidate_agent_name,
        "family": family,
        "clan": clan,
        "workflow": workflow,
        "timestamp": timestamp,
        "tribes": tribe_values,
    }


def _hold_deadlock_wait_node_wire(
    record: AgentArtifactRecordWire,
) -> dict[str, Any]:
    meta = record.agent_meta
    waiting = record.waiting
    waiting_for: list[str] = []
    wait_for_hoods: list[str] = []
    if waiting is not None:
        waiting_for = [name for name in waiting.waiting_for if name]
        wait_for_hoods = [hood for hood in waiting.wait_for_hoods if hood]
        if not wait_for_hoods and meta is not None:
            wait_for_hoods = [hood for hood in meta.wait_for_hoods if hood]
    elif meta is not None:
        waiting_for = [name for name in meta.wait_for if name]
        wait_for_hoods = [hood for hood in meta.wait_for_hoods if hood]
    tribes: list[str] = []
    if meta is not None:
        for value in (meta.tribe, meta.clan_tribe):
            if isinstance(value, str) and value and value not in tribes:
                tribes.append(value)
    return {
        "artifact_dir": record.artifact_dir,
        "agent_name": None if meta is None else meta.name,
        "family": None if meta is None else meta.agent_family,
        "clan": None if meta is None else meta.agent_clan,
        "workflow": None if meta is None else meta.workflow_name,
        "timestamp": record.timestamp,
        "waiting_for": waiting_for,
        "wait_for_hoods": wait_for_hoods,
        "tribes": tribes,
        "running": record.running is not None,
        "has_done_marker": record.has_done_marker,
    }


def _apply_hold_deadlock_identity(
    nodes: list[dict[str, Any]],
    records: list[AgentArtifactRecordWire],
) -> None:
    from sase.core.agent_hold_identity import (
        apply_hold_identity_to_capacity_records,
        attach_hold_identity_scratch_from_meta,
        strip_hold_identity_scratch_fields,
    )

    rows: list[dict[str, Any]] = []
    for record, node in zip(records, nodes, strict=True):
        meta = record.agent_meta
        row: dict[str, Any] = {
            "artifact_dir": record.artifact_dir,
            "timestamp": record.timestamp,
            "clan": node.get("clan"),
        }
        attach_hold_identity_scratch_from_meta(
            row,
            cl_name=None if meta is None else meta.cl_name,
            clan_generation=None if meta is None else meta.agent_clan_generation,
            parent_timestamp=None if meta is None else meta.parent_timestamp,
            timestamp=record.timestamp,
            meta_tribe=None if meta is None else meta.tribe,
            clan_tribe=None if meta is None else meta.clan_tribe,
            clan=None if meta is None else meta.agent_clan,
        )
        rows.append(row)
    apply_hold_identity_to_capacity_records(rows, scan_records=records)
    for node, row in zip(nodes, rows, strict=True):
        tribes = row.get("tribes")
        if isinstance(tribes, list):
            node["tribes"] = [
                str(item) for item in tribes if isinstance(item, str) and item
            ]
        strip_hold_identity_scratch_fields(row)


def candidate_blocker_codes(blockers: object) -> set[str]:
    if not isinstance(blockers, list):
        return set()
    return {
        str(blocker.get("code"))
        for blocker in blockers
        if isinstance(blocker, dict) and blocker.get("code")
    }


def decision_blocker_message(decision: Mapping[str, Any]) -> str:
    messages = [
        str(blocker.get("message"))
        for blocker in decision.get("blockers", [])
        if isinstance(blocker, dict) and blocker.get("message")
    ]
    return "; ".join(messages) or (
        "Runner capacity rejected this candidate for an unspecified reason."
    )


_VALID_CANDIDATE_DECISIONS = frozenset(
    {"acquire_capacity", "reuse_existing_claim", "blocked", "invalid"}
)


def require_candidate_decision(
    snapshot: dict[str, Any],
    artifacts_dir: str,
) -> dict[str, Any]:
    """Return Rust's authoritative candidate decision, failing closed.

    Rust's ``candidate_decision`` is the single source of truth for whether
    this candidate may acquire or reuse capacity -- see ``build_candidate_decision``
    in ``sase-core``'s ``runner_capacity.rs``. A missing, malformed, or unknown
    decision must never be treated as permission to proceed.
    """
    decision = snapshot.get("candidate_decision")
    if (
        not isinstance(decision, dict)
        or decision.get("artifact_dir") != artifacts_dir
        or decision.get("decision") not in _VALID_CANDIDATE_DECISIONS
        or not isinstance(decision.get("owner_key"), str)
        or not isinstance(decision.get("lineage_key"), str)
        or not isinstance(decision.get("effective_weight"), (int, float))
        or isinstance(decision.get("effective_weight"), bool)
    ):
        raise RunnerSlotAdmissionError(
            "Runner capacity returned no usable candidate decision for "
            f"{artifacts_dir}; refusing to admit or park without an "
            "authoritative decision."
        )
    return decision


def enrich_candidate_from_records(
    candidate: dict[str, Any],
    records: list[AgentArtifactRecordWire],
) -> dict[str, Any]:
    for record in records:
        if record.artifact_dir != candidate.get("artifact_dir"):
            continue
        meta = record.agent_meta
        enriched = dict(candidate)
        enriched.update(
            {
                "project_name": record.project_name,
                "workflow_dir_name": record.workflow_dir_name,
                "timestamp": record.timestamp,
                "agent_name": None if meta is None else meta.name,
                "workflow": (
                    None
                    if meta is None
                    else (
                        meta.workflow_name
                        or (
                            record.workflow_state.workflow_name
                            if record.workflow_state is not None
                            else None
                        )
                    )
                ),
                "clan": None if meta is None else meta.agent_clan,
                "tribe": None if meta is None else (meta.tribe or meta.clan_tribe),
                "tribes": [],
                "created_at": candidate_created_at_from_timestamp(record.timestamp),
                "has_agent_meta": meta is not None,
                "has_done_marker": record.has_done_marker,
                "appears_as_agent": (
                    True
                    if record.workflow_state is None
                    else record.workflow_state.appears_as_agent
                ),
                "parent_timestamp": None if meta is None else meta.parent_timestamp,
                "agent_family": None if meta is None else meta.agent_family,
                "agent_family_role": None if meta is None else meta.agent_family_role,
                "agent_family_parallel": (
                    False if meta is None else meta.agent_family_parallel
                ),
                "runner_claim_owner_key": (
                    None if meta is None else meta.runner_claim_owner_key
                ),
            }
        )
        from sase.core.agent_hold_identity import (
            apply_hold_identity_to_capacity_records,
            attach_hold_identity_scratch_from_meta,
        )

        attach_hold_identity_scratch_from_meta(
            enriched,
            cl_name=None if meta is None else meta.cl_name,
            clan_generation=None if meta is None else meta.agent_clan_generation,
            parent_timestamp=None if meta is None else meta.parent_timestamp,
            timestamp=record.timestamp,
            meta_tribe=None if meta is None else meta.tribe,
            clan_tribe=None if meta is None else meta.clan_tribe,
            clan=None if meta is None else meta.agent_clan,
        )
        apply_hold_identity_to_capacity_records([enriched], scan_records=records)
        return enriched
    return candidate


def candidate_scan_queue_weight_error(
    records: list[AgentArtifactRecordWire],
    artifacts_dir: str,
) -> RunnerSlotAdmissionError | None:
    for record in records:
        if record.artifact_dir != artifacts_dir:
            continue
        waiting = record.waiting
        if waiting is not None:
            if waiting.queue_weight_invalid:
                return invalid_queue_weight_error(
                    "waiting marker",
                    waiting.queue_weight,
                )
            if (
                waiting.queue_weight is not None
                and valid_queue_weight(waiting.queue_weight) is None
            ):
                return invalid_queue_weight_error(
                    "waiting marker",
                    waiting.queue_weight,
                )
        meta = record.agent_meta
        if meta is None:
            return None
        if meta.queue_weight_invalid:
            return invalid_queue_weight_error("agent metadata", meta.queue_weight)
        if (
            meta.queue_weight is not None
            and valid_queue_weight(meta.queue_weight) is None
        ):
            return invalid_queue_weight_error("agent metadata", meta.queue_weight)
        return None
    return None


def publish_claim_ownership(
    *,
    artifacts_dir: str,
    agent_meta: dict[str, Any] | None,
    queue_weight: float,
    queue_weight_explicit: bool,
    runner_claim_owner_key: str,
) -> None:
    """Persist the Rust-resolved claim before *claim* exposes the work.

    Both the effective weight and the durable lineage owner key are written
    atomically under the runner-slot lock so a later admission check -- even
    one that can no longer see a released predecessor once ``capacity_only``
    scans drop its done directory -- resolves this record's lineage from its
    own metadata instead of re-walking a live scan.
    """
    fields = {
        "queue_weight": queue_weight,
        "queue_weight_explicit": queue_weight_explicit,
        "runner_claim_owner_key": runner_claim_owner_key,
    }
    if agent_meta is not None:
        agent_meta.update(fields)
        agent_meta.pop("queue_weight_invalid", None)
        agent_meta.pop("queue_weight_error", None)
    from sase.axe.run_agent_helpers_artifacts import update_meta_fields

    update_meta_fields(
        artifacts_dir,
        fields,
        remove_keys=("queue_weight_invalid", "queue_weight_error"),
    )
