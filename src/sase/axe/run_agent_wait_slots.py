"""Runner-slot admission control for the run agent runner.

The global participating-agent cap is enforced by a check-and-claim under a
single host-wide lock: each candidate reads the shared capacity-only scan,
decides whether it may start, and either claims RUNNING atomically or
publishes a ``waiting.json`` queue marker and retries with jittered backoff.

Marker-state decoding (priority, queue weight, eligibility) lives in
``run_agent_wait_slot_state``, and candidate-decision handling (parking,
enrichment, claim publication) lives in ``run_agent_wait_slot_candidate``;
both are imported here so the admission loop below reads as one flow.
"""

import fcntl
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.agent.names import is_process_alive
from sase.axe.run_agent_wait_markers import (
    queue_capacity_marker_fields,
    read_json_dict,
    remove_waiting_marker,
    write_waiting_marker,
)
from sase.axe.run_agent_wait_slot_candidate import (
    _abandon_unclaimed_attempt,
    _candidate_blocker_codes,
    _candidate_scan_queue_weight_error,
    _decision_blocker_message,
    _enrich_candidate_from_records,
    _park_for_unavailable_limit,
    _publish_claim_ownership,
    _require_candidate_decision,
)
from sase.axe.run_agent_wait_slot_poll import advance_runner_slot_poll
from sase.axe.run_agent_wait_slot_state import (
    _RunnerSlotAdmissionError,
    _continuous_eligibility_start,
    _marker_priority_state,
    _marker_queue_weight_state,
    _marker_runner_condition_state,
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
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
)
from sase.core.paths import sase_home, sase_projects_dir
from sase.core.runner_slots import (
    DEFAULT_WAIT_PRIORITY,
    deference_window_seconds,
    load_or_refresh_runner_slot_scan,
    notify_runner_slot_state_changed,
    runner_capacity_snapshot,
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


def _runner_slot_lock_path() -> Path:
    return sase_home() / "runner_slots.lock"


def _collect_runner_slot_records() -> list[AgentArtifactRecordWire]:
    from sase.core.agent_scan_facade import scan_agent_artifacts

    return scan_agent_artifacts(sase_projects_dir(), _RUNNER_SLOT_SCAN_OPTIONS).records


def _scan_runner_slot_records() -> list[AgentArtifactRecordWire]:
    return load_or_refresh_runner_slot_scan(
        _collect_runner_slot_records,
        max_age=float(_RUNNER_SLOT_POLL_INTERVAL),
    )


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


def _try_claim_runner_slot(
    *,
    artifacts_dir: str,
    cl_name: str,
    timestamp: str,
    directive_threshold: int | None,
    directive_priority: int | None = None,
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
    """
    lock_path = _runner_slot_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            waiting_path = Path(artifacts_dir) / "waiting.json"
            waiting_data = read_json_dict(waiting_path)
            priority, priority_explicit = _marker_priority_state(
                waiting_data,
                directive_priority,
            )
            queue_weight, queue_weight_explicit = _marker_queue_weight_state(
                waiting_data,
                directive_queue_weight,
                directive_queue_weight_explicit,
            )
            queue_capacity: int | None = None
            queue_capacity_explicit = False
            try:
                queue_capacity, queue_capacity_explicit = (
                    _marker_runner_condition_state(waiting_data, directive_threshold)
                )
                effective_limit = float(get_max_running_agents())
            except Exception as error:  # noqa: BLE001 - admission fails closed.
                if not park_on_block:
                    return _abandon_unclaimed_attempt(artifacts_dir)
                return _park_for_unavailable_limit(
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
                waiting_data.get("slot_requested_at")
                if waiting_data is not None
                else None
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
            )
            records = _scan_runner_slot_records()
            queue_weight_error = _candidate_scan_queue_weight_error(
                records,
                artifacts_dir,
            )
            if queue_weight_error is not None:
                raise queue_weight_error
            candidate = _enrich_candidate_from_records(candidate, records)
            is_live = _record_liveness_probe()
            now = datetime.now(UTC)
            snapshot = runner_capacity_snapshot(
                records,
                is_live,
                effective_limit=effective_limit,
                now=now.isoformat(),
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
            )
            decision = _require_candidate_decision(snapshot, artifacts_dir)
            if decision["decision"] == "invalid":
                raise _RunnerSlotAdmissionError(_decision_blocker_message(decision))
            if decision["decision"] in ("reuse_existing_claim", "acquire_capacity"):
                _publish_claim_ownership(
                    artifacts_dir=artifacts_dir,
                    agent_meta=agent_meta,
                    queue_weight=float(decision["effective_weight"]),
                    queue_weight_explicit=queue_weight_explicit,
                    runner_claim_owner_key=decision["lineage_key"],
                )
                run_started_at = claim()
                notify_runner_slot_state_changed()
                remove_waiting_marker(artifacts_dir)
                return run_started_at, False
            if not park_on_block:
                return _abandon_unclaimed_attempt(artifacts_dir)
            eligible_since: str | None = None
            entered_deference = False
            deference_window = 0.0
            blocker_codes = _candidate_blocker_codes(decision.get("blockers"))
            if "deference-window" in blocker_codes:
                deference_window = deference_window_seconds(
                    priority,
                    seconds_per_step=get_runner_slot_deference_seconds_per_step(),
                    max_seconds=get_runner_slot_deference_max_seconds(),
                )
                eligible_since, entered_deference = _continuous_eligibility_start(
                    marker_eligible_since,
                    now,
                )
            marker = dict(waiting_data or {})
            marker.pop("runner_limit_unavailable", None)
            if eligible_since is None:
                marker.pop("eligible_since", None)
            else:
                marker["eligible_since"] = eligible_since
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
                }
            )
            parked = waiting_data is None or "slot_requested_at" not in waiting_data
            if waiting_data != marker:
                write_waiting_marker(artifacts_dir, marker)
            if entered_deference:
                print(
                    f"Deferring for up to {deference_window:g}s (priority {priority})"
                )
            return None, parked
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def try_claim_runner_slot_without_parking(
    artifacts_dir: str,
    cl_name: str,
    timestamp: str,
    agent_meta: dict[str, Any],
    *,
    wait_runners: int | None,
    wait_priority: int | None = None,
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

    lock_path = _runner_slot_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            remove_waiting_marker(artifacts_dir)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    print("Agent killed while waiting for a runner slot", file=sys.stderr)
    sys.exit(128 + 15)
