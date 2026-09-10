"""Runner-slot admission control for the run agent runner.

The global participating-agent cap is enforced by a check-and-claim under a
single host-wide lock: each candidate reads the shared capacity-only scan,
decides whether it may start, and either claims RUNNING atomically or
publishes a ``waiting.json`` queue marker and retries with jittered backoff.
"""

import fcntl
import math
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.agent.names import is_process_alive
from sase.axe.run_agent_wait_markers import (
    read_json_dict,
    remove_waiting_marker,
    write_waiting_marker,
)
from sase.axe.run_agent_wait_slot_poll import advance_runner_slot_poll
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


class _RunnerSlotAdmissionError(RuntimeError):
    """Raised when a serial continuation requests an incompatible live claim."""


def _invalid_queue_weight_error(
    source: str, value: object
) -> _RunnerSlotAdmissionError:
    return _RunnerSlotAdmissionError(
        f"Invalid queue_weight in {source}: expected a positive finite number, "
        f"got {value!r}."
    )


def _marker_runner_condition_state(
    waiting_data: dict[str, Any] | None,
    directive_threshold: int | None,
) -> tuple[int | None, bool]:
    if waiting_data is not None and "slot_requested_at" in waiting_data:
        explicit = waiting_data.get("wait_runners_explicit") is True
        marker_value = waiting_data.get("wait_runners")
        if explicit and type(marker_value) is int and marker_value >= 0:
            return marker_value, True
    if directive_threshold is not None:
        return directive_threshold, True
    return None, False


def _legacy_marker_priority_explicit(waiting_data: dict[str, Any]) -> bool:
    marker_value = waiting_data.get("wait_priority")
    # Legacy markers had no explicitness flag. A non-default priority almost
    # certainly came from a user directive or edit; the default was often written
    # implicitly by the runner and must not shadow later directive metadata.
    return (
        "wait_priority_explicit" not in waiting_data
        and type(marker_value) is int
        and marker_value >= 0
        and marker_value != DEFAULT_WAIT_PRIORITY
    )


def _marker_priority_state(
    waiting_data: dict[str, Any] | None,
    directive_priority: int | None,
) -> tuple[int, bool]:
    if waiting_data is not None and "slot_requested_at" in waiting_data:
        marker_value = waiting_data.get("wait_priority")
        marker_explicit = waiting_data.get(
            "wait_priority_explicit"
        ) is True or _legacy_marker_priority_explicit(waiting_data)
        if marker_explicit and type(marker_value) is int and marker_value >= 0:
            return marker_value, True
    if type(directive_priority) is int and directive_priority >= 0:
        return directive_priority, True
    return DEFAULT_WAIT_PRIORITY, False


def _valid_queue_weight(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    weight = float(value)
    if not math.isfinite(weight) or weight <= 0:
        return None
    return weight


def _marker_queue_weight_state(
    waiting_data: dict[str, Any] | None,
    directive_weight: float,
    directive_explicit: bool,
) -> tuple[float, bool]:
    if waiting_data is not None and "slot_requested_at" in waiting_data:
        if waiting_data.get("queue_weight_invalid") is True:
            raise _invalid_queue_weight_error(
                "waiting marker",
                waiting_data.get("queue_weight"),
            )
        if "queue_weight" in waiting_data:
            marker_weight = _valid_queue_weight(waiting_data.get("queue_weight"))
            if marker_weight is None:
                raise _invalid_queue_weight_error(
                    "waiting marker",
                    waiting_data.get("queue_weight"),
                )
            return marker_weight, waiting_data.get("queue_weight_explicit") is True
    weight = _valid_queue_weight(directive_weight)
    if weight is None:
        raise _invalid_queue_weight_error("agent metadata", directive_weight)
    return weight, directive_explicit


def _continuous_eligibility_start(
    eligible_since: object,
    now: datetime,
) -> tuple[str, bool]:
    """Return a valid non-future start and whether it had to be reset."""
    if isinstance(eligible_since, str) and eligible_since:
        try:
            started = datetime.fromisoformat(eligible_since.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            else:
                started = started.astimezone(UTC)
            normalized_now = (
                now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
            )
            if started <= normalized_now:
                return eligible_since, False
    return now.isoformat(), True


def _park_for_unavailable_limit(
    *,
    artifacts_dir: str,
    cl_name: str,
    timestamp: str,
    waiting_data: dict[str, Any] | None,
    priority: int,
    priority_explicit: bool,
    queue_weight: float,
    queue_weight_explicit: bool,
    wait_runners: int | None,
    wait_runners_explicit: bool,
    error: Exception,
) -> tuple[None, bool]:
    """Republish the queue marker when the runner limit cannot be read."""
    requested_at = (
        waiting_data.get("slot_requested_at") if waiting_data is not None else None
    )
    if not isinstance(requested_at, str) or not requested_at:
        requested_at = datetime.now(UTC).isoformat()
    marker = dict(waiting_data or {})
    marker_wait_runners = wait_runners if wait_runners is not None else 0
    marker.update(
        {
            "patch_name": cl_name,
            "cl_name": cl_name,
            "timestamp": timestamp,
            "wait_runners": marker_wait_runners,
            "wait_runners_explicit": wait_runners_explicit,
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


def _candidate_waiter(
    snapshot: dict[str, Any],
    artifacts_dir: str,
) -> dict[str, Any] | None:
    for waiter in snapshot.get("waiters", []):
        if isinstance(waiter, dict) and waiter.get("artifact_dir") == artifacts_dir:
            return waiter
    return None


def _candidate_blocker_codes(waiter: dict[str, Any] | None) -> set[str]:
    if waiter is None:
        return set()
    return {
        str(blocker.get("code"))
        for blocker in waiter.get("blockers", [])
        if isinstance(blocker, dict) and blocker.get("code")
    }


def _weight_equal(left: float, right: float) -> bool:
    limit = max(abs(left), abs(right), 1.0)
    return abs(left - right) <= 4.0 * math.ulp(limit)


def _serial_family_owner_key(candidate: dict[str, Any]) -> str | None:
    if (
        candidate.get("parent_timestamp") is None
        or candidate.get("agent_family_parallel") is True
    ):
        return None
    project = str(candidate.get("project_name") or "")
    family = candidate.get("agent_family")
    if not isinstance(family, str) or not family:
        return None
    return f"{project}:{family}"


def _active_serial_claim(
    snapshot: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any] | None:
    owner_key = _serial_family_owner_key(candidate)
    if owner_key is None:
        return None
    for claim in snapshot.get("claims", []):
        if (
            isinstance(claim, dict)
            and claim.get("claim_kind") == "serial_family"
            and claim.get("owner_key") == owner_key
        ):
            return claim
    return None


def _enrich_candidate_from_records(
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
            }
        )
        return enriched
    return candidate


def _candidate_scan_queue_weight_error(
    records: list[AgentArtifactRecordWire],
    artifacts_dir: str,
) -> _RunnerSlotAdmissionError | None:
    for record in records:
        if record.artifact_dir != artifacts_dir:
            continue
        waiting = record.waiting
        if waiting is not None:
            if waiting.queue_weight_invalid:
                return _invalid_queue_weight_error(
                    "waiting marker",
                    waiting.queue_weight,
                )
            if (
                waiting.queue_weight is not None
                and _valid_queue_weight(waiting.queue_weight) is None
            ):
                return _invalid_queue_weight_error(
                    "waiting marker",
                    waiting.queue_weight,
                )
        meta = record.agent_meta
        if meta is None:
            return None
        if meta.queue_weight_invalid:
            return _invalid_queue_weight_error("agent metadata", meta.queue_weight)
        if (
            meta.queue_weight is not None
            and _valid_queue_weight(meta.queue_weight) is None
        ):
            return _invalid_queue_weight_error("agent metadata", meta.queue_weight)
        return None
    return None


def _assert_active_family_weight_is_compatible(
    *,
    claim: dict[str, Any],
    requested_weight: float,
    requested_weight_explicit: bool,
) -> None:
    if not requested_weight_explicit:
        return
    occupied = claim.get("occupied_capacity")
    if not isinstance(occupied, (int, float)) or not math.isfinite(float(occupied)):
        raise _RunnerSlotAdmissionError(
            "Active serial family has an invalid runner capacity claim."
        )
    if not _weight_equal(requested_weight, float(occupied)):
        raise _RunnerSlotAdmissionError(
            "Serial continuation requested queue_weight "
            f"{requested_weight:g}, but its active family already holds "
            f"{float(occupied):g}; use the existing family weight or start an "
            "independent agent."
        )


def _active_claim_weight(claim: dict[str, Any]) -> float:
    occupied = claim.get("occupied_capacity")
    if not isinstance(occupied, (int, float)) or isinstance(occupied, bool):
        raise _RunnerSlotAdmissionError(
            "Active serial family has an invalid runner capacity claim."
        )
    weight = float(occupied)
    if not math.isfinite(weight) or weight <= 0:
        raise _RunnerSlotAdmissionError(
            "Active serial family has an invalid runner capacity claim."
        )
    return weight


def _publish_claim_queue_weight(
    *,
    artifacts_dir: str,
    agent_meta: dict[str, Any] | None,
    queue_weight: float,
    queue_weight_explicit: bool,
) -> None:
    fields = {
        "queue_weight": queue_weight,
        "queue_weight_explicit": queue_weight_explicit,
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
) -> tuple[str | None, bool]:
    """Try one check-and-claim under the global lock.

    Returns ``(run_started_at, parked)``. ``parked`` is true when this call
    first published the slot queue marker.
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
            wait_runners: int | None = None
            wait_runners_explicit = False
            try:
                wait_runners, wait_runners_explicit = _marker_runner_condition_state(
                    waiting_data, directive_threshold
                )
                effective_limit = float(get_max_running_agents())
            except Exception as error:  # noqa: BLE001 - admission fails closed.
                return _park_for_unavailable_limit(
                    artifacts_dir=artifacts_dir,
                    cl_name=cl_name,
                    timestamp=timestamp,
                    waiting_data=waiting_data,
                    priority=priority,
                    priority_explicit=priority_explicit,
                    queue_weight=queue_weight,
                    queue_weight_explicit=queue_weight_explicit,
                    wait_runners=wait_runners,
                    wait_runners_explicit=wait_runners_explicit,
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
                wait_runners=wait_runners,
                wait_runners_explicit=wait_runners_explicit,
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
            active_claim = _active_serial_claim(snapshot, candidate)
            if active_claim is not None:
                claim_weight = _active_claim_weight(active_claim)
                _assert_active_family_weight_is_compatible(
                    claim=active_claim,
                    requested_weight=queue_weight,
                    requested_weight_explicit=queue_weight_explicit,
                )
                _publish_claim_queue_weight(
                    artifacts_dir=artifacts_dir,
                    agent_meta=agent_meta,
                    queue_weight=(
                        queue_weight if queue_weight_explicit else claim_weight
                    ),
                    queue_weight_explicit=queue_weight_explicit,
                )
                run_started_at = claim()
                notify_runner_slot_state_changed()
                remove_waiting_marker(artifacts_dir)
                return run_started_at, False
            candidate_waiter = _candidate_waiter(snapshot, artifacts_dir)
            eligible = snapshot.get("first_eligible_artifact_dir") == artifacts_dir
            eligible_since: str | None = None
            entered_deference = False
            deference_window = 0.0
            if eligible:
                _publish_claim_queue_weight(
                    artifacts_dir=artifacts_dir,
                    agent_meta=agent_meta,
                    queue_weight=queue_weight,
                    queue_weight_explicit=queue_weight_explicit,
                )
                run_started_at = claim()
                notify_runner_slot_state_changed()
                remove_waiting_marker(artifacts_dir)
                return run_started_at, False
            blocker_codes = _candidate_blocker_codes(candidate_waiter)
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
                    "wait_runners": wait_runners if wait_runners is not None else 0,
                    "wait_runners_explicit": wait_runners_explicit,
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
