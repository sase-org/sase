"""Runner-slot admission control for the run agent runner.

The global participating-agent cap is enforced by a check-and-claim under a
single host-wide lock: each candidate rescans live agents, decides whether it
may start, and either claims RUNNING atomically or publishes a ``waiting.json``
queue marker and retries.
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
    read_json_dict,
    remove_waiting_marker,
    write_waiting_marker,
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
    better_priority_agent_pending,
    deference_satisfied,
    deference_window_seconds,
    live_runner_slot_waiters,
    may_start,
    running_agent_slot_count,
)

_RUNNER_SLOT_POLL_INTERVAL = 2
_RUNNER_SLOT_SCAN_OPTIONS = AgentArtifactScanOptionsWire(
    include_prompt_step_markers=False,
    include_raw_prompt_snippets=False,
    only_workflow_dirs=("ace-run",),
    include_done_markers=False,
)


def _runner_slot_lock_path() -> Path:
    return sase_home() / "runner_slots.lock"


def _scan_runner_slot_records() -> list[AgentArtifactRecordWire]:
    from sase.core.agent_scan_facade import scan_agent_artifacts

    return scan_agent_artifacts(sase_projects_dir(), _RUNNER_SLOT_SCAN_OPTIONS).records


def _record_liveness_probe() -> Callable[[AgentArtifactRecordWire], bool]:
    cache: dict[str, bool] = {}

    def is_live(record: AgentArtifactRecordWire) -> bool:
        if record.artifact_dir in cache:
            return cache[record.artifact_dir]
        meta = record.agent_meta
        pid = None if meta is None else meta.pid
        if pid is None and record.running is not None:
            pid = record.running.pid
        alive = is_process_alive(
            {
                "pid": pid,
                "stopped_at": None if meta is None else meta.stopped_at,
            },
            Path(record.artifact_dir),
        )
        cache[record.artifact_dir] = alive
        return alive

    return is_live


def _marker_threshold(
    waiting_data: dict[str, Any] | None,
    directive_threshold: int | None,
) -> tuple[int, bool]:
    if waiting_data is not None and "slot_requested_at" in waiting_data:
        explicit = waiting_data.get("wait_runners_explicit") is True
        marker_value = waiting_data.get("wait_runners")
        if explicit and type(marker_value) is int and marker_value >= 0:
            return marker_value, True
        if not explicit:
            return get_max_running_agents() - 1, False
    if directive_threshold is not None:
        return directive_threshold, True
    return get_max_running_agents() - 1, False


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
    error: Exception,
) -> tuple[None, bool]:
    """Republish the queue marker when the runner limit cannot be read."""
    requested_at = (
        waiting_data.get("slot_requested_at") if waiting_data is not None else None
    )
    if not isinstance(requested_at, str) or not requested_at:
        requested_at = datetime.now(UTC).isoformat()
    marker = dict(waiting_data or {})
    previous_threshold = marker.get("wait_runners")
    if type(previous_threshold) is not int or previous_threshold < 0:
        previous_threshold = 0
    marker.update(
        {
            "patch_name": cl_name,
            "cl_name": cl_name,
            "timestamp": timestamp,
            "wait_runners": previous_threshold,
            "wait_runners_explicit": False,
            "wait_priority": priority,
            "wait_priority_explicit": priority_explicit,
            "slot_requested_at": requested_at,
            "runner_limit_unavailable": str(error),
        }
    )
    parked = waiting_data is None or "slot_requested_at" not in waiting_data
    if waiting_data != marker:
        write_waiting_marker(artifacts_dir, marker)
    return None, parked


def _try_claim_runner_slot(
    *,
    artifacts_dir: str,
    cl_name: str,
    timestamp: str,
    directive_threshold: int | None,
    directive_priority: int | None = None,
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
            try:
                threshold, explicit = _marker_threshold(
                    waiting_data, directive_threshold
                )
            except Exception as error:  # noqa: BLE001 - admission fails closed.
                return _park_for_unavailable_limit(
                    artifacts_dir=artifacts_dir,
                    cl_name=cl_name,
                    timestamp=timestamp,
                    waiting_data=waiting_data,
                    priority=priority,
                    priority_explicit=priority_explicit,
                    error=error,
                )
            records = _scan_runner_slot_records()
            is_live = _record_liveness_probe()
            queue = live_runner_slot_waiters(records, is_live)
            running_count = running_agent_slot_count(records, is_live)
            eligible = may_start(running_count, threshold, queue, artifacts_dir)
            eligible_since: str | None = None
            entered_deference = False
            deference_window = 0.0
            if eligible:
                if priority <= DEFAULT_WAIT_PRIORITY:
                    run_started_at = claim()
                    remove_waiting_marker(artifacts_dir)
                    return run_started_at, False
                deference_window = deference_window_seconds(
                    priority,
                    seconds_per_step=get_runner_slot_deference_seconds_per_step(),
                    max_seconds=get_runner_slot_deference_max_seconds(),
                )
                if deference_window <= 0 or not better_priority_agent_pending(
                    records,
                    is_live,
                    priority=priority,
                    me=artifacts_dir,
                ):
                    run_started_at = claim()
                    remove_waiting_marker(artifacts_dir)
                    return run_started_at, False
                now = datetime.now(UTC)
                marker_eligible_since = (
                    waiting_data.get("eligible_since")
                    if waiting_data is not None
                    else None
                )
                if deference_satisfied(
                    marker_eligible_since
                    if isinstance(marker_eligible_since, str)
                    else None,
                    now,
                    deference_window,
                ):
                    run_started_at = claim()
                    remove_waiting_marker(artifacts_dir)
                    return run_started_at, False
                eligible_since, entered_deference = _continuous_eligibility_start(
                    marker_eligible_since,
                    now,
                )

            requested_at = (
                waiting_data.get("slot_requested_at")
                if waiting_data is not None
                else None
            )
            if not isinstance(requested_at, str) or not requested_at:
                requested_at = datetime.now(UTC).isoformat()
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
                    "wait_runners": threshold,
                    "wait_runners_explicit": explicit,
                    "wait_priority": priority,
                    "wait_priority_explicit": priority_explicit,
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
    claim: Callable[[], str],
) -> str:
    """Pass the final participating-agent gate and atomically claim RUNNING.

    Serial family follow-ups are exempt so a parent waiting on its children can
    never deadlock while holding a slot. Parallel family members participate in
    the global cap independently.

    This exemption is now purely about *waiting*, not about *occupancy*: the
    family's slot is already counted by `running_agent_slot_count` off
    whichever of its shells is currently live (root, serial child, monitor,
    or monitor follow-up), so an exempt member here is riding a slot its
    family already holds rather than escaping the cap. Making it wait too
    would reintroduce the deadlock this exemption exists to prevent, and
    would strand a monitor follow-up whose starter root is already dead no
    matter what the gate decides.
    """
    if (
        agent_meta.get("parent_timestamp")
        and agent_meta.get("agent_family_parallel") is not True
    ):
        return claim()

    while not was_killed():
        run_started_at, parked = _try_claim_runner_slot(
            artifacts_dir=artifacts_dir,
            cl_name=cl_name,
            timestamp=timestamp,
            directive_threshold=wait_runners,
            directive_priority=wait_priority,
            claim=claim,
        )
        if run_started_at is not None:
            return run_started_at
        if parked:
            print("Waiting for a runner slot")
        time.sleep(_RUNNER_SLOT_POLL_INTERVAL)

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
