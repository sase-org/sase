"""Row and tier builders for the shared capacity view."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any

from ._capacity_view import (
    CapacityHoldingRow,
    CapacityIdleGroup,
    CapacityQueuedRow,
    CapacityRiderRow,
    MachineCapacityView,
)
from ._capacity_view_text import (
    assemble_capacity_view,
    capacity_blocker_text,
    capacity_one_blocker,
    seconds_since_stamp,
)

_IDLE_GROUP_LIMIT = 10

_REASON_ORDER = (
    "not_started",
    "pending_question",
    "pending_gate",
    "explicit_zero_weight",
    "invalid_weight",
    "not_live",
    "no_pid",
    "unknown_holder",
    "done",
    "not_agent_record",
)

_REASON_LABELS = {
    "not_started": "not started",
    "pending_question": "waiting on a question",
    "pending_gate": "waiting on a gate",
    "explicit_zero_weight": "explicit zero weight",
    "invalid_weight": "invalid weight",
    "not_live": "not live",
    "no_pid": "no process evidence",
    "unknown_holder": "claim holder unknown",
    "done": "done",
    "not_agent_record": "not an agent record",
}

_TIER_LABELS = {
    "not_started": "waiting to start",
    "pending_question": "waiting on a question",
    "pending_gate": "waiting on a gate",
    "explicit_zero_weight": "zero weight",
    "invalid_weight": "invalid weight",
    "not_live": "not live",
    "no_pid": "no process evidence",
    "unknown_holder": "claim holder unknown",
    "done": "done",
    "not_agent_record": "not agent records",
}

_EXPLANATIONS = {
    "not_started": (
        "Live, but its run has not begun (waiting on dependencies, a "
        "schedule, or launch). Holds nothing until admitted."
    ),
    "pending_question": (
        "Paused on a question while a human decides. Holds nothing; the "
        "follow-up reacquires capacity when answered."
    ),
    "pending_gate": (
        "Paused on a gate while a human decides. Holds nothing; the "
        "follow-up reacquires capacity when decided."
    ),
    "explicit_zero_weight": (
        "Launched with an explicit weight of 0, so it never charges capacity."
    ),
    "not_live": (
        "No live process and no done marker (killed, crashed, or stranded). "
        "Never holds capacity."
    ),
    "done": "Finished. Done records never hold capacity.",
    "not_agent_record": (
        "Not an agent run (workflow step, proc, or hidden record). Only "
        "agent runs charge capacity."
    ),
    "no_pid": (
        "A monitor member with no recorded process. Its charge is unknown — "
        "never counted as free."
    ),
    "invalid_weight": (
        "Its queue weight cannot be parsed, so its claim is dropped and "
        "accounting is invalid."
    ),
    "unknown_holder": (
        "Shares a claim whose holder could not be determined. Its charge is "
        "unknown — never counted as free."
    ),
}

_INACTIVE_REASONS = frozenset({"not_live", "done", "not_agent_record"})
_SKIP_IDLE_STATES = frozenset({"holding", "riding_claim", "waiting"})
_QUEUE_TONE_BY_CODE = {
    "insufficient-capacity": "capacity",
    "hold-barrier": "held",
    "deference-window": "deferred",
    "weight-exceeds-limit": "never_fits",
}


def project_capacity_view(
    report: Any,
    *,
    running_nodes: int | None = None,
    expanded_idle_groups: Collection[str] = (),
    now: float | None = None,
) -> MachineCapacityView:
    """Build the shared capacity view for *report*."""
    moment = report.computed_at if now is None else now
    accounting = tuple(report.accounting)
    inputs = {
        record_inputs.artifact_dir: record_inputs
        for record_inputs in report.record_inputs
    }
    by_dir = {str(entry.get("artifact_dir")): entry for entry in accounting}
    names = {path: _display_name(entry) for path, entry in by_dir.items()}

    riders, riders_by_holder = _rider_rows(accounting, names, inputs, moment)
    holdings = _holding_rows(
        report.claims, by_dir, names, inputs, riders_by_holder, moment
    )
    holdings.sort(key=lambda row: row.name)
    charged = tuple(
        sorted(
            (row for row in holdings if row.charged_weight > 0),
            key=_holding_sort_key,
        )
    )
    zero_weight = tuple(
        sorted(
            (row for row in holdings if row.charged_weight <= 0),
            key=_holding_sort_key,
        )
    )

    idle_groups = _idle_groups(
        accounting,
        names,
        expanded_groups=frozenset(expanded_idle_groups),
        complete=False,
    )
    attention_groups = _idle_groups(
        accounting, names, expanded_groups=frozenset(), complete=True, tier="attention"
    )
    waiting_groups = _idle_groups(
        accounting, names, expanded_groups=frozenset(), complete=True, tier="waiting"
    )
    inactive_groups = _idle_groups(
        accounting, names, expanded_groups=frozenset(), complete=True, tier="inactive"
    )
    queued = _queued_rows(report.waiters, names, inputs, by_dir, moment)
    return assemble_capacity_view(
        report,
        moment=moment,
        running_nodes=running_nodes,
        holdings=holdings,
        riders=riders,
        charged=charged,
        zero_weight=zero_weight,
        idle_groups=idle_groups,
        attention_groups=attention_groups,
        waiting_groups=waiting_groups,
        inactive_groups=inactive_groups,
        queued=queued,
        names=names,
        inputs=inputs,
    )


def _holding_rows(
    claims: Any,
    by_dir: dict[str, Mapping[str, Any]],
    names: dict[str, str],
    inputs: dict[str, Any],
    riders_by_holder: dict[str, tuple[str, ...]],
    moment: float,
) -> list[CapacityHoldingRow]:
    holdings: list[CapacityHoldingRow] = []
    for claim in claims:
        owner_key = str(claim.get("owner_key") or "")
        holder_dir = str(claim.get("owner_artifact_dir") or "")
        entry = by_dir.get(holder_dir)
        if entry is None:
            continue
        record = inputs.get(holder_dir)
        holdings.append(
            CapacityHoldingRow(
                name=names.get(holder_dir, holder_dir),
                kind=_holding_kind(entry, claim, record),
                charged_weight=float(entry.get("charged_weight") or 0.0),
                weight_source=str(entry.get("weight_source") or "unknown"),
                since=getattr(record, "run_started_at", None),
                authored_budget=getattr(record, "authored_queue_capacity", None),
                owner_key=owner_key,
                artifact_dir=holder_dir,
                project_key=str(entry.get("project_name") or ""),
                running_seconds=seconds_since_stamp(
                    moment, getattr(record, "run_started_at", None)
                ),
                rider_names=riders_by_holder.get(holder_dir, ()),
            )
        )
    return holdings


def _rider_rows(
    accounting: tuple[Mapping[str, Any], ...],
    names: dict[str, str],
    inputs: dict[str, Any],
    moment: float,
) -> tuple[list[CapacityRiderRow], dict[str, tuple[str, ...]]]:
    riders: list[CapacityRiderRow] = []
    names_by_holder: dict[str, list[str]] = {}
    for entry in accounting:
        if str(entry.get("state")) != "riding_claim":
            continue
        path = str(entry.get("artifact_dir"))
        holder_dir = entry.get("claim_holder_artifact_dir")
        holder = str(holder_dir) if holder_dir else ""
        record = inputs.get(path)
        name = names.get(path, path)
        riders.append(
            CapacityRiderRow(
                name=name,
                holder_name=names.get(holder, holder) if holder else "?",
                owner_key=str(entry.get("claim_owner_key") or ""),
                artifact_dir=path,
                holder_artifact_dir=holder,
                project_key=str(entry.get("project_name") or ""),
                running_seconds=seconds_since_stamp(
                    moment, getattr(record, "run_started_at", None)
                ),
            )
        )
        if holder:
            names_by_holder.setdefault(holder, []).append(name)
    riders.sort(key=lambda row: row.name)
    riders_by_holder = {
        path: tuple(sorted(member_names))
        for path, member_names in names_by_holder.items()
    }
    return riders, riders_by_holder


def _holding_sort_key(row: CapacityHoldingRow) -> tuple[object, ...]:
    running = row.running_seconds
    return (-row.charged_weight, running is None, -(running or 0.0), row.name)


def _display_name(entry: Mapping[str, Any]) -> str:
    name = entry.get("agent_name")
    if isinstance(name, str) and name:
        return name
    path = str(entry.get("artifact_dir") or "")
    return path.rsplit("/", 1)[-1] or path


def _holding_kind(
    entry: Mapping[str, Any], claim: Mapping[str, Any], record: Any
) -> str:
    if str(entry.get("weight_source")) == "explicit_zero":
        return "wait monitor"
    turn_kind = getattr(record, "turn_kind", None)
    if turn_kind == "monitor":
        return "verify monitor"
    if getattr(record, "turn_role", None) == "gate":
        return "gate"
    if str(claim.get("claim_kind")) == "parallel_member":
        return "parallel member"
    return "worker"


def _idle_reason_code(entry: Mapping[str, Any]) -> str:
    reason = entry.get("reason_code")
    if str(entry.get("state")) == "unknown" and not (
        isinstance(reason, str) and reason
    ):
        return "unknown_holder"
    if isinstance(reason, str) and reason:
        return reason
    return "not_started"


def _idle_tier(entry: Mapping[str, Any], code: str) -> str:
    if str(entry.get("state")) == "unknown" or code in {
        "no_pid",
        "invalid_weight",
        "unknown_holder",
    }:
        return "attention"
    if code in _INACTIVE_REASONS:
        return "inactive"
    return "waiting"


def _reason_label(code: str, *, tiered: bool) -> str:
    labels = _TIER_LABELS if tiered else _REASON_LABELS
    return labels.get(code, code.replace("_", " "))


def _explanation(code: str) -> str:
    text = _EXPLANATIONS.get(code)
    if text is not None:
        return text
    return f"Holds no capacity (reason: {code})."


def _idle_groups(
    accounting: tuple[Mapping[str, Any], ...],
    names: dict[str, str],
    *,
    expanded_groups: frozenset[str] = frozenset(),
    complete: bool = False,
    tier: str | None = None,
) -> tuple[CapacityIdleGroup, ...]:
    by_reason: dict[str, list[tuple[str, str, str]]] = {}
    for entry in accounting:
        if str(entry.get("state")) in _SKIP_IDLE_STATES:
            continue
        code = _idle_reason_code(entry)
        group_tier = _idle_tier(entry, code)
        if tier is not None and group_tier != tier:
            continue
        path = str(entry.get("artifact_dir"))
        by_reason.setdefault(code, []).append((names.get(path, path), path, group_tier))
    groups: list[CapacityIdleGroup] = []
    ordered = [code for code in _REASON_ORDER if code in by_reason]
    ordered.extend(sorted(code for code in by_reason if code not in _REASON_ORDER))
    for code in ordered:
        members = sorted(by_reason[code], key=lambda member: (member[0], member[1]))
        if complete or code in expanded_groups:
            shown = members
        else:
            shown = members[:_IDLE_GROUP_LIMIT]
        hidden = 0 if complete else len(members) - len(shown)
        group_tier = members[0][2]
        groups.append(
            CapacityIdleGroup(
                reason_code=code,
                reason_label=_reason_label(code, tiered=complete or tier is not None),
                count=len(members),
                members=tuple(name for name, _, _ in shown),
                truncated=hidden > 0,
                hidden=hidden,
                member_artifact_dirs=tuple(path for _, path, _ in shown),
                tier=group_tier,  # type: ignore[arg-type]
                explanation=_explanation(code),
            )
        )
    return tuple(groups)


def _queued_rows(
    waiters: Any,
    names: dict[str, str],
    inputs: dict[str, Any],
    by_dir: dict[str, Mapping[str, Any]],
    moment: float,
) -> tuple[CapacityQueuedRow, ...]:
    rows: list[CapacityQueuedRow] = []
    for waiter in waiters:
        path = str(waiter.get("artifact_dir"))
        record = inputs.get(path)
        entry = by_dir.get(path)
        slot_requested_at = waiter.get("slot_requested_at") or getattr(
            record, "slot_requested_at", None
        )
        blocker_items = [
            item for item in (waiter.get("blockers") or []) if isinstance(item, Mapping)
        ]
        rows.append(
            CapacityQueuedRow(
                name=names.get(path, _fallback_name(path, record)),
                queue_position=int(waiter.get("queue_position") or 0),
                requested_weight=float(waiter.get("requested_weight") or 0.0),
                admission_limit=float(waiter.get("admission_limit") or 0.0),
                blocker=capacity_blocker_text(waiter),
                eligible=bool(waiter.get("eligible")),
                slot_requested_at=slot_requested_at,
                artifact_dir=path,
                project_key=str((entry or {}).get("project_name") or ""),
                waiting_seconds=seconds_since_stamp(moment, slot_requested_at),
                tone=_queue_tone(waiter, blocker_items),
                blockers=tuple(capacity_one_blocker(item) for item in blocker_items),
            )
        )
    return tuple(rows)


def _queue_tone(
    waiter: Mapping[str, Any], blocker_items: list[Mapping[str, Any]]
) -> Any:
    for item in blocker_items:
        code = str(item.get("code") or "")
        mapped = _QUEUE_TONE_BY_CODE.get(code)
        if mapped is not None:
            return mapped
        if code:
            return "other"
    if waiter.get("eligible"):
        return "ready"
    return "capacity"


def _fallback_name(path: str, record: Any) -> str:
    monitor_id = getattr(record, "monitor_id", None)
    if isinstance(monitor_id, str) and monitor_id:
        return monitor_id
    return path.rsplit("/", 1)[-1] or path
