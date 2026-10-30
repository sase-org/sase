"""The monitor-start flow: identity, the lane lock, and the launch transaction.

Immediate ``start_monitor`` composes shared preparation and launch. Staging
lives in :mod:`sase.monitor.start_stage`.
"""

from __future__ import annotations

from sase.finalizers.owned_turn import (
    finalizer_owned_turn_is_active,
    finalizer_owned_turn_refusal,
)
from sase.logs._bounded import log_file_lock

from .models import (
    MonitorError,
    MonitorRecord,
)
from .request import StartMonitorRequest
from .start_lane import (
    StartIdentity,
    resolve_start_identity,
)
from .start_launch import launch_monitor
from .start_prepare import prepare_monitor_locked
from .start_timing import StartTimer
from .transaction import monitor_lane_lock_path


def _finalizer_owned_monitor_refusal() -> str:
    """Return the refusal for ``sase monitor start`` in a finalizer turn."""
    return finalizer_owned_turn_refusal(
        "sase monitor start",
        inline_hint=(
            "Re-wait inline with the printed `sase tool wait <run-id>` form, "
            "or run the command in the foreground instead, then finish the "
            "repair in this turn."
        ),
    )


def refuse_finalizer_owned_monitor_start() -> None:
    """Raise before any monitor state exists when a finalizer owns this turn.

    Runs before identity resolution, replay lookup, member creation, proc
    submit, claim moves, and the handoff marker, so a refused start leaves
    no monitor record, proc, transferred claim, or pending handoff behind.
    """
    if finalizer_owned_turn_is_active():
        raise MonitorError(_finalizer_owned_monitor_refusal())


def start_monitor(request: StartMonitorRequest) -> MonitorRecord:
    """Start (or return the existing) monitor for *request*'s lane.

    An omitted ``request.lane`` is an implicit start: the calling agent
    shell is resolved metadata-first -- its own artifacts dir, then an
    exact ``SASE_AGENT_NAME`` match, then the newest non-monitor member of
    its own agent session -- and the durable agent session is taken from that artifact.
    An explicit lane still resolves to the newest matching agent-session member.
    """
    refuse_finalizer_owned_monitor_start()
    timer = StartTimer()
    identity = resolve_start_identity(request)
    timer.mark("resolve_identity")
    with log_file_lock(
        monitor_lane_lock_path(request.project_name, identity.lock_lane)
    ):
        timer.mark("lane_lock")
        return _start_monitor_locked(request, identity, timer)


def _start_monitor_locked(
    request: StartMonitorRequest, identity: StartIdentity, timer: StartTimer
) -> MonitorRecord:
    """Start one monitor while the caller holds the lane start lock."""
    prepared = prepare_monitor_locked(request, identity, timer)
    if prepared.replayed is not None:
        return prepared.replayed
    if prepared.context is None:
        raise MonitorError("monitor preparation produced no launch context")
    return launch_monitor(prepared.context, timer)


__all__ = [
    "_finalizer_owned_monitor_refusal",
    "refuse_finalizer_owned_monitor_start",
    "start_monitor",
]
