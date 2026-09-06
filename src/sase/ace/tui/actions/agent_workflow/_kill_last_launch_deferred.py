"""Deferred kill-on-completion helpers for ``,X`` last-launch actions."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, cast

from ._kill_last_launch_targets import (
    agent_for_launch_result,
    all_record_results,
    ensure_agent_visible,
    launch_result_key,
    notify_app,
    record_results_are_handled,
    schedule_launch_target_refresh,
    synthetic_agent_from_launch_result,
    unhandled_launch_results,
)
from ._launch_records import (
    LaunchRecord,
    LaunchRecordState,
    consume_launch_record,
    launch_record_for_proc_id,
    record_procs_are_terminal,
    release_kill_pending_launch_record,
)
from ._relaunch_barrier import (
    PENDING_LAUNCH_KILL_TIMEOUT_SECONDS,
    open_relaunch_cleanup_barrier,
    release_relaunch_holds_if_idle,
    settle_relaunch_cleanup_barrier,
)
from ._types import RelaunchOperation

if TYPE_CHECKING:
    from sase.agent.launch_types import AgentLaunchResult

    from ...models import Agent

_ADMISSION_DEFERRED_STATUSES = frozenset({"WAITING", "QUEUED"})


def apply_deferred_launch_kill_on_completion(
    app: object,
    proc_id: str,
    results: Sequence[AgentLaunchResult | None],
    *,
    failed: bool,
    admission_complete: bool = True,
) -> None:
    """Kill or abandon a ``KILL_PENDING`` record when *proc_id* becomes terminal.

    Called from the launch-completion callback after record stamping. A
    successful payload kills every returned result through the ordinary
    kill/dismiss path; a failure with no results discards the pending
    intent. The replacement-launch hold stays up until every proc on the
    record is terminal and any cleanup barrier opened here settles.
    """
    record = launch_record_for_proc_id(app, proc_id)
    if record is None or record.state is not LaunchRecordState.KILL_PENDING:
        return

    present = tuple(result for result in results if result is not None)
    if present:
        _execute_deferred_kill_for_results(
            app,
            record,
            present,
            admission_complete=admission_complete,
        )
    elif failed:
        notify_app(
            app,
            f'Launch of "{record.display_name}" failed; kill-on-finish was cancelled',
            severity="warning",
        )

    if record_procs_are_terminal(record):
        _finish_pending_launch_kill(app, record)


def register_pending_launch_kill(
    app: object,
    record: LaunchRecord,
    *,
    operation: RelaunchOperation,
) -> None:
    """Mark *record* ``KILL_PENDING`` and start its warn-and-release timer."""
    if record.state is LaunchRecordState.KILL_PENDING:
        return
    record.relaunch_operation = operation
    record.state = LaunchRecordState.KILL_PENDING
    timers = getattr(app, "_pending_launch_kill_timers", None)
    if timers is None:
        timers = {}
        cast(Any, app)._pending_launch_kill_timers = timers
    if record.proc_ids in timers:
        return
    set_timer = getattr(app, "set_timer", None)
    timer = None
    if callable(set_timer):
        timer = set_timer(
            PENDING_LAUNCH_KILL_TIMEOUT_SECONDS,
            lambda: _pending_launch_kill_timed_out(app, record),
            name="pending-launch-kill-timeout",
        )
    timers[record.proc_ids] = timer
    _execute_deferred_kill_for_results(
        app,
        record,
        all_record_results(record),
        admission_complete=True,
    )
    if record_procs_are_terminal(record):
        _finish_pending_launch_kill(app, record)


def _pending_launch_kill_timed_out(app: object, record: LaunchRecord) -> None:
    """Abandon auto-kill after the in-flight budget and release parked launches."""
    if record.state is not LaunchRecordState.KILL_PENDING:
        return
    _stop_pending_kill_timer(app, record)
    release_kill_pending_launch_record(record)
    notify_app(
        app,
        f'"{record.display_name}" took too long to finish launching; '
        "it will appear and can be killed with ,x",
        severity="warning",
    )
    release_relaunch_holds_if_idle(app, operation=record.relaunch_operation)


def _finish_pending_launch_kill(app: object, record: LaunchRecord) -> None:
    """Clear pending-kill bookkeeping once every proc on *record* is terminal."""
    _stop_pending_kill_timer(app, record)
    if record.state is LaunchRecordState.KILL_PENDING:
        if record_results_are_handled(record):
            consume_launch_record(record)
        else:
            release_kill_pending_launch_record(record)
    release_relaunch_holds_if_idle(app, operation=record.relaunch_operation)


def _stop_pending_kill_timer(app: object, record: LaunchRecord) -> None:
    timers = getattr(app, "_pending_launch_kill_timers", None)
    if not timers:
        return
    timer = timers.pop(record.proc_ids, None)
    if timer is None:
        return
    stop = getattr(timer, "stop", None)
    if callable(stop):
        try:
            stop()
        except Exception:
            pass


def _execute_deferred_kill_for_results(
    app: object,
    record: LaunchRecord,
    results: Sequence[AgentLaunchResult],
    *,
    admission_complete: bool,
) -> None:
    pending = unhandled_launch_results(record, results)
    if not pending:
        return
    pending_keys = {launch_result_key(result) for result in pending}
    record.kill_in_progress_result_keys.update(pending_keys)

    agents = _agents_for_deferred_kill(app, pending)
    if not agents:
        record.kill_in_progress_result_keys.difference_update(pending_keys)
        schedule_launch_target_refresh(app, pending)
        notify_app(
            app,
            f'Could not find launched agent(s) of "{record.display_name}" to kill',
            severity="warning",
        )
        return

    killable, dismissable = _split_deferred_kill_targets(agents)
    barrier = open_relaunch_cleanup_barrier(
        app,
        f"deferred kill {record.display_name}",
        operation=record.relaunch_operation,
    )
    settle: Callable[[], None] = lambda: settle_relaunch_cleanup_barrier(  # noqa: E731
        app, barrier
    )
    initiated = _initiate_deferred_kill(app, killable, dismissable, settle)
    record.kill_in_progress_result_keys.difference_update(pending_keys)
    if not initiated:
        record.kill_failed_result_keys.update(pending_keys)
        settle()
        notify_app(
            app,
            f'Could not start cleanup for launched agent(s) of "{record.display_name}"',
            severity="warning",
        )
        return
    record.handled_result_keys.update(pending_keys)
    record.kill_failed_result_keys.difference_update(pending_keys)
    if not admission_complete:
        notify_app(
            app,
            f'Killed launched units of "{record.display_name}"; '
            "gated units continue in the background",
            severity="warning",
        )


def _initiate_deferred_kill(
    app: object,
    killable: list[Agent],
    dismissable: list[Agent],
    settle: Callable[[], None],
) -> bool:
    """Start the ordinary kill/dismiss path. Return whether *settle* will fire."""
    if len(killable) + len(dismissable) == 1 and len(dismissable) == 1:
        dismiss = getattr(app, "_dismiss_done_agent", None)
        if callable(dismiss):
            return bool(dismiss(dismissable[0], on_settled=settle))
        return False
    if len(killable) + len(dismissable) == 1 and len(killable) == 1:
        kill = getattr(app, "_do_kill_agent", None)
        if callable(kill):
            return bool(kill(killable[0], on_settled=settle))
        return False
    bulk = getattr(app, "_do_bulk_kill_agents", None)
    if callable(bulk):
        return bool(bulk(killable, dismissable, on_settled=settle))
    return False


def _agents_for_deferred_kill(
    app: object, results: Sequence[AgentLaunchResult]
) -> list[Agent]:
    loaded = tuple(
        getattr(app, "_agents_with_children", None)
        or getattr(app, "_agents", None)
        or ()
    )
    matched: list[Agent] = []
    seen: set[object] = set()
    for result in results:
        agent = agent_for_launch_result(loaded, result)
        if agent is None:
            agent = synthetic_agent_from_launch_result(result)
            if agent is not None:
                ensure_agent_visible(app, agent)
                loaded = tuple(
                    getattr(app, "_agents_with_children", None)
                    or getattr(app, "_agents", None)
                    or ()
                )
        if agent is None:
            continue
        identity = getattr(agent, "identity", id(agent))
        if identity in seen:
            continue
        seen.add(identity)
        matched.append(agent)
    return matched


def _split_deferred_kill_targets(
    agents: Sequence[Agent],
) -> tuple[list[Agent], list[Agent]]:
    from ..agents._core import DISMISSABLE_STATUSES

    killable: list[Agent] = []
    dismissable: list[Agent] = []
    for agent in agents:
        status = getattr(agent, "status", "")
        if (
            status in _ADMISSION_DEFERRED_STATUSES
            or status in DISMISSABLE_STATUSES
            or getattr(agent, "pid", None) is None
        ):
            dismissable.append(agent)
        else:
            killable.append(agent)
    return killable, dismissable
