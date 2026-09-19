"""Runner-slot admission control for the run agent runner.

The global participating-agent cap is enforced by a check-and-claim under a
single host-wide lock: each candidate reads the shared capacity-only scan,
decides whether it may start, and either claims RUNNING atomically or
publishes a ``waiting.json`` queue marker and retries with jittered backoff.
Hold publication uses the same ``runner_slots.lock`` so an arm cannot land
between the hold snapshot and claim.

Marker-state decoding (priority, queue weight, eligibility) lives in
``run_agent_wait_slot_state``, and candidate-decision handling (parking,
enrichment, claim publication) lives in ``run_agent_wait_slot_candidate``;
both are imported here so the admission loop below reads as one flow.
"""

import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.agent.names import is_process_alive
from sase.axe.run_agent_wait_markers import (
    hold_marker_fields,
    queue_capacity_marker_fields,
    read_json_dict,
    remove_waiting_marker,
    write_waiting_marker,
)
from sase.axe.run_agent_wait_slot_candidate import (
    abandon_unclaimed_attempt,
    candidate_blocker_codes,
    candidate_scan_queue_weight_error,
    decision_blocker_message,
    enrich_candidate_from_records,
    hold_deadlock_armer_record,
    park_for_unavailable_limit,
    publish_claim_ownership,
    require_candidate_decision,
)
from sase.axe.run_agent_wait_slot_poll import advance_runner_slot_poll
from sase.axe.run_agent_wait_slot_state import (
    RunnerSlotAdmissionError,
    continuous_eligibility_start,
    marker_priority_state,
    marker_queue_weight_state,
    marker_runner_condition_state,
)
from sase.axe.runner_idle_memory import (
    IDLE_TRIM_INTERVAL_SECONDS,
    release_idle_memory,
)
from sase.axe.runner_signals import was_killed
from sase.config.core import (
    get_max_running_agents,
    get_runner_slot_deference_max_seconds,
    get_runner_slot_deference_seconds_per_step,
)
from sase.core.agent_hold_facade import (
    candidate_created_at_from_timestamp,
    snapshot_active_agent_holds,
)
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
)
from sase.core.agent_hold_notifications import notify_hold_prune_outcomes
from sase.core.paths import sase_projects_dir
from sase.core.runner_slots import (
    DEFAULT_WAIT_PRIORITY,
    deference_window_seconds,
    load_or_refresh_runner_slot_scan,
    notify_runner_slot_state_changed,
    runner_capacity_snapshot,
    runner_slot_admission_lock,
    runner_slot_candidate_record,
    runner_slot_state_token,
)

_RUNNER_SLOT_POLL_INTERVAL = 2
_DEFAULT_QUEUE_WEIGHT = 1.0
_RUNNER_SLOT_SCAN_OPTIONS = AgentArtifactScanOptionsWire(
    include_prompt_step_markers=False,
    include_raw_prompt_snippets=False,
    only_workflow_dirs=("ace-run",),
    include_done_markers=False,
    capacity_only=True,
)


def _collect_runner_slot_records() -> list[AgentArtifactRecordWire]:
    from sase.core.agent_scan_facade import scan_agent_artifacts

    return scan_agent_artifacts(sase_projects_dir(), _RUNNER_SLOT_SCAN_OPTIONS).records


def _scan_runner_slot_records() -> list[AgentArtifactRecordWire]:
    return load_or_refresh_runner_slot_scan(
        _collect_runner_slot_records,
        max_age=float(_RUNNER_SLOT_POLL_INTERVAL),
    )


def scan_runner_slot_records() -> list[AgentArtifactRecordWire]:
    return _scan_runner_slot_records()


def _record_liveness_probe() -> Callable[[AgentArtifactRecordWire], bool]:
    cache: dict[str, bool] = {}

    def is_live(record: AgentArtifactRecordWire) -> bool:
        if record.artifact_dir in cache:
            return cache[record.artifact_dir]
        meta = record.agent_meta
        pid = None if meta is None else meta.pid
        if pid is None and record.running is not None:
            pid = record.running.pid
        liveness: dict[str, object] = {}
        if pid is not None:
            liveness["pid"] = pid
        if meta is not None:
            if meta.stopped_at is not None:
                liveness["stopped_at"] = meta.stopped_at
            process_identity = getattr(meta, "process_identity", None)
            if process_identity is not None:
                liveness["process_identity"] = process_identity
        if (
            "process_identity" not in liveness
            and record.running is not None
            and getattr(record.running, "process_identity", None) is not None
        ):
            liveness["process_identity"] = record.running.process_identity
        alive = is_process_alive(
            liveness,
            Path(record.artifact_dir),
        )
        cache[record.artifact_dir] = alive
        return alive

    return is_live


def record_liveness_probe() -> Callable[[AgentArtifactRecordWire], bool]:
    return _record_liveness_probe()


def _agent_meta_str(agent_meta: dict[str, Any] | None, key: str) -> str | None:
    if not isinstance(agent_meta, dict):
        return None
    value = agent_meta.get(key)
    return value if isinstance(value, str) and value else None


def _try_claim_runner_slot(
    *,
    artifacts_dir: str,
    cl_name: str,
    timestamp: str,
    directive_threshold: int | None,
    directive_priority: int | None = None,
    directive_priority_implied: int | None = None,
    directive_queue_weight: float = _DEFAULT_QUEUE_WEIGHT,
    directive_queue_weight_explicit: bool = False,
    agent_meta: dict[str, Any] | None = None,
    claim: Callable[[], str],
    park_on_block: bool = True,
) -> tuple[str | None, bool]:
    """Try one check-and-claim under the global lock.

    Returns ``(run_started_at, parked)``. ``parked`` is true when this call
    first published the slot queue marker. When ``park_on_block`` is false, a
    blocked or limit-unavailable decision leaves no waiting marker and
    returns ``(None, False)`` so the caller may proceed unclaimed.

    The hold snapshot and claim share ``runner_slots.lock`` with hold
    publication. Lifecycle and deadlock notifications are sent after the
    lock is released.
    """
    holds_after: list[dict[str, Any]] = []
    holds_pruned: list[dict[str, Any]] = []
    hold_now: datetime | None = None
    deadlocks: list[tuple[str, str | None, str, AgentArtifactRecordWire]] = []
    with runner_slot_admission_lock():
        waiting_path = Path(artifacts_dir) / "waiting.json"
        waiting_data = read_json_dict(waiting_path)
        priority, priority_explicit = marker_priority_state(
            waiting_data,
            directive_priority,
            implied_priority=directive_priority_implied,
        )
        queue_weight, queue_weight_explicit = marker_queue_weight_state(
            waiting_data,
            directive_queue_weight,
            directive_queue_weight_explicit,
        )
        queue_capacity: int | None = None
        queue_capacity_explicit = False
        try:
            queue_capacity, queue_capacity_explicit = marker_runner_condition_state(
                waiting_data, directive_threshold
            )
            effective_limit = float(get_max_running_agents())
        except Exception as error:  # noqa: BLE001 - admission fails closed.
            if not park_on_block:
                return abandon_unclaimed_attempt(artifacts_dir)
            return park_for_unavailable_limit(
                artifacts_dir=artifacts_dir,
                cl_name=cl_name,
                timestamp=timestamp,
                waiting_data=waiting_data,
                priority=priority,
                priority_explicit=priority_explicit,
                queue_weight=queue_weight,
                queue_weight_explicit=queue_weight_explicit,
                queue_capacity=queue_capacity,
                queue_capacity_explicit=queue_capacity_explicit,
                error=error,
            )
        requested_at = (
            waiting_data.get("slot_requested_at") if waiting_data is not None else None
        )
        if not isinstance(requested_at, str) or not requested_at:
            requested_at = datetime.now(UTC).isoformat()
        marker_eligible_since = (
            waiting_data.get("eligible_since") if waiting_data is not None else None
        )
        candidate = runner_slot_candidate_record(
            artifacts_dir=artifacts_dir,
            timestamp=timestamp,
            slot_requested_at=requested_at,
            queue_capacity=queue_capacity,
            queue_capacity_explicit=queue_capacity_explicit,
            wait_priority=priority,
            queue_weight=queue_weight,
            queue_weight_explicit=queue_weight_explicit,
            eligible_since=(
                marker_eligible_since
                if isinstance(marker_eligible_since, str)
                else None
            ),
            agent_name=_agent_meta_str(agent_meta, "name"),
            workflow=_agent_meta_str(agent_meta, "workflow_name"),
            clan=_agent_meta_str(agent_meta, "agent_clan"),
            tribe=_agent_meta_str(agent_meta, "tribe"),
            agent_family=_agent_meta_str(agent_meta, "agent_family"),
            created_at=candidate_created_at_from_timestamp(timestamp),
            cl_name=cl_name or _agent_meta_str(agent_meta, "cl_name"),
            clan_generation=_agent_meta_str(agent_meta, "agent_clan_generation"),
            clan_tribe=_agent_meta_str(agent_meta, "clan_tribe"),
            parent_timestamp=_agent_meta_str(agent_meta, "parent_timestamp"),
        )
        records = scan_runner_slot_records()
        queue_weight_error = candidate_scan_queue_weight_error(
            records,
            artifacts_dir,
        )
        if queue_weight_error is not None:
            raise queue_weight_error
        candidate = enrich_candidate_from_records(candidate, records)
        hold_now = datetime.now(UTC)
        _, holds_after, holds_pruned = snapshot_active_agent_holds(
            records, now=hold_now
        )
        is_live = record_liveness_probe()
        snapshot = runner_capacity_snapshot(
            records,
            is_live,
            effective_limit=effective_limit,
            now=hold_now.isoformat(),
            deference_seconds_per_step=(
                get_runner_slot_deference_seconds_per_step()
                if priority > DEFAULT_WAIT_PRIORITY
                else 0
            ),
            deference_max_seconds=(
                get_runner_slot_deference_max_seconds()
                if priority > DEFAULT_WAIT_PRIORITY
                else 0
            ),
            candidate=candidate,
            active_holds=holds_after,
        )
        decision = require_candidate_decision(snapshot, artifacts_dir)
        if decision["decision"] == "invalid":
            raise RunnerSlotAdmissionError(decision_blocker_message(decision))
        if decision["decision"] in ("reuse_existing_claim", "acquire_capacity"):
            publish_claim_ownership(
                artifacts_dir=artifacts_dir,
                agent_meta=agent_meta,
                queue_weight=float(decision["effective_weight"]),
                queue_weight_explicit=queue_weight_explicit,
                runner_claim_owner_key=decision["lineage_key"],
            )
            run_started_at = claim()
            notify_runner_slot_state_changed()
            remove_waiting_marker(artifacts_dir)
            result: tuple[str | None, bool] = (run_started_at, False)
        elif not park_on_block:
            result = abandon_unclaimed_attempt(artifacts_dir)
        else:
            eligible_since: str | None = None
            entered_deference = False
            deference_window = 0.0
            blocker_codes = candidate_blocker_codes(decision.get("blockers"))
            deadlocks = _hold_deadlock_armers(
                artifacts_dir=artifacts_dir,
                candidate=candidate,
                blockers=decision.get("blockers"),
                active_holds=holds_after,
                records=records,
            )
            if "deference-window" in blocker_codes:
                deference_window = deference_window_seconds(
                    priority,
                    seconds_per_step=get_runner_slot_deference_seconds_per_step(),
                    max_seconds=get_runner_slot_deference_max_seconds(),
                )
                eligible_since, entered_deference = continuous_eligibility_start(
                    marker_eligible_since,
                    hold_now,
                )
            marker = dict(waiting_data or {})
            marker.pop("runner_limit_unavailable", None)
            if eligible_since is None:
                marker.pop("eligible_since", None)
            else:
                marker["eligible_since"] = eligible_since
            marker.pop("held_by", None)
            marker.pop("hold_expires_at", None)
            marker.update(
                {
                    "patch_name": cl_name,
                    "cl_name": cl_name,
                    "timestamp": timestamp,
                    **queue_capacity_marker_fields(
                        queue_capacity if queue_capacity is not None else 0,
                        explicit=queue_capacity_explicit,
                    ),
                    "wait_priority": priority,
                    "wait_priority_explicit": priority_explicit,
                    "queue_weight": queue_weight,
                    "queue_weight_explicit": queue_weight_explicit,
                    "slot_requested_at": requested_at,
                    **hold_marker_fields(decision.get("blockers")),
                }
            )
            parked = waiting_data is None or "slot_requested_at" not in waiting_data
            if waiting_data != marker:
                write_waiting_marker(artifacts_dir, marker)
            if entered_deference:
                print(
                    f"Deferring for up to {deference_window:g}s (priority {priority})"
                )
            result = (None, parked)
    if hold_now is not None:
        notify_hold_prune_outcomes(holds_pruned, now=hold_now)
    for artifacts, agent_name, held_by, armer_record in deadlocks:
        _notify_hold_deadlock(
            artifacts_dir=artifacts,
            candidate_agent_name=agent_name,
            held_by=held_by,
            armer_record=armer_record,
        )
    return result


def _notify_hold_deadlock(
    *,
    artifacts_dir: str,
    candidate_agent_name: str | None,
    held_by: str,
    armer_record: AgentArtifactRecordWire,
) -> None:
    """Upsert a deduped notification for a candidate/armer mutual hold block."""
    from uuid import uuid4

    from sase.core.time import get_timezone
    from sase.notifications.models import Notification, normalize_notification_tags
    from sase.notifications.store import upsert_notification

    armer_meta = armer_record.agent_meta
    armer_label = (armer_meta.name if armer_meta is not None else None) or held_by
    timestamp = datetime.now(get_timezone()).isoformat()
    note = (
        f"Held by {armer_label} ({held_by}), which is itself pre-run and "
        f"waiting on {candidate_agent_name or artifacts_dir}"
    )
    notification = Notification(
        id=str(uuid4()),
        timestamp=timestamp,
        sender="runner_slot_admission",
        icon="!",
        color="#D14343",
        notes=[
            "Hold deadlock: armer and candidate are blocking each other",
            f"Candidate: {candidate_agent_name or artifacts_dir}",
            note,
            "The hold's TTL remains the forward-progress guarantee; release "
            "the hold explicitly or kill one side to resolve sooner.",
        ],
        files=[artifacts_dir, armer_record.artifact_dir],
        tags=normalize_notification_tags(["hold", "deadlock", "blocked"]),
        action_data={
            "candidate_artifact_dir": artifacts_dir,
            "armer_key": held_by,
            "armer_artifact_dir": armer_record.artifact_dir,
        },
        dedup_key=f"runner_slot:hold-deadlock:{artifacts_dir}:{held_by}",
    )
    upsert_notification(
        notification,
        plus_one_note="Still deadlocked",
        plus_one_timestamp=timestamp,
    )


def _hold_deadlock_armers(
    *,
    artifacts_dir: str,
    candidate: dict[str, Any],
    blockers: object,
    active_holds: list[dict[str, Any]],
    records: list[AgentArtifactRecordWire],
) -> list[tuple[str, str | None, str, AgentArtifactRecordWire]]:
    if not isinstance(blockers, list):
        return []
    candidate_agent_name = candidate.get("agent_name")
    if not isinstance(candidate_agent_name, str):
        candidate_agent_name = None
    found: list[tuple[str, str | None, str, AgentArtifactRecordWire]] = []
    for blocker in blockers:
        if not isinstance(blocker, dict) or blocker.get("code") != "hold-barrier":
            continue
        held_by = blocker.get("held_by")
        if not isinstance(held_by, str) or not held_by:
            continue
        armer_record = hold_deadlock_armer_record(
            held_by=held_by,
            candidate_agent_name=candidate_agent_name,
            active_holds=active_holds,
            records=records,
            candidate=candidate,
        )
        if armer_record is not None:
            found.append((artifacts_dir, candidate_agent_name, held_by, armer_record))
    return found


def try_claim_runner_slot_without_parking(
    artifacts_dir: str,
    cl_name: str,
    timestamp: str,
    agent_meta: dict[str, Any],
    *,
    wait_runners: int | None,
    wait_priority: int | None = None,
    wait_priority_implied: int | None = None,
    queue_weight: float = _DEFAULT_QUEUE_WEIGHT,
    queue_weight_explicit: bool = False,
    claim: Callable[[], str],
) -> str | None:
    """One locked claim attempt that never parks.

    Returns the claim timestamp when admitted. Returns ``None`` when blocked
    so the caller may proceed unclaimed, leaving no waiting marker and no
    phantom claim.
    """
    run_started_at, _parked = _try_claim_runner_slot(
        artifacts_dir=artifacts_dir,
        cl_name=cl_name,
        timestamp=timestamp,
        directive_threshold=wait_runners,
        directive_priority=wait_priority,
        directive_priority_implied=wait_priority_implied,
        directive_queue_weight=queue_weight,
        directive_queue_weight_explicit=queue_weight_explicit,
        agent_meta=agent_meta,
        claim=claim,
        park_on_block=False,
    )
    return run_started_at


def wait_for_runner_slot(
    artifacts_dir: str,
    cl_name: str,
    timestamp: str,
    agent_meta: dict[str, Any],
    *,
    wait_runners: int | None,
    wait_priority: int | None = None,
    wait_priority_implied: int | None = None,
    queue_weight: float = _DEFAULT_QUEUE_WEIGHT,
    queue_weight_explicit: bool = False,
    claim: Callable[[], str],
) -> str:
    """Pass the final participating-agent gate and atomically claim RUNNING.

    Serial family continuations reuse a still-live family claim under the
    runner-slot lock. Once that family has released its claim, the successor
    queues and reacquires capacity like any other launch.
    """
    poll_attempt = 0
    seen_token = runner_slot_state_token()
    next_trim_at: float | None = None
    while not was_killed():
        run_started_at, parked = _try_claim_runner_slot(
            artifacts_dir=artifacts_dir,
            cl_name=cl_name,
            timestamp=timestamp,
            directive_threshold=wait_runners,
            directive_priority=wait_priority,
            directive_priority_implied=wait_priority_implied,
            directive_queue_weight=queue_weight,
            directive_queue_weight_explicit=queue_weight_explicit,
            agent_meta=agent_meta,
            claim=claim,
        )
        if run_started_at is not None:
            return run_started_at
        if parked:
            print("Waiting for a runner slot")
            poll_attempt = 0
        # Only reached when the claim failed, so this runner is queued behind
        # the capacity budget and may sit here for hours still holding its
        # bootstrap peak. Release it, then keep it released against what each
        # further claim attempt allocates.
        now = time.monotonic()
        if next_trim_at is None or now >= next_trim_at:
            release_idle_memory()
            next_trim_at = now + IDLE_TRIM_INTERVAL_SECONDS
        poll_attempt, seen_token = advance_runner_slot_poll(
            poll_attempt,
            seen_token,
            base=float(_RUNNER_SLOT_POLL_INTERVAL),
            killed=was_killed,
            token=runner_slot_state_token,
        )

    with runner_slot_admission_lock():
        remove_waiting_marker(artifacts_dir)
    print("Agent killed while waiting for a runner slot", file=sys.stderr)
    sys.exit(128 + 15)
