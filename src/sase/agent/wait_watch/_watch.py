"""Polling engine for resolved wait targets."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
import time

from sase.agent.names._common import is_process_alive
from sase.core.agent_scan_wire import AgentArtifactScanWire

from ._classify import classify_wait_targets
from ._resolve import LivenessChecker
from ._types import (
    WaitSettlement,
    WaitTarget,
    WaitTargetState,
    WaitTick,
    WaitWatchConfig,
    is_stop_state,
    make_settlement,
)

SnapshotProvider = Callable[[], AgentArtifactScanWire]
Clock = Callable[[], float]
Sleeper = Callable[[float], None]


def watch_wait_targets(
    config: WaitWatchConfig,
    snapshot_provider: SnapshotProvider,
    *,
    clock: Clock = time.monotonic,
    sleep: Sleeper = time.sleep,
    liveness_checker: LivenessChecker = is_process_alive,
) -> Iterator[WaitTick]:
    """Yield wait ticks until targets settle, time out, or are interrupted."""

    start = clock()
    index = 0
    while True:
        snapshot = snapshot_provider()
        elapsed = max(0.0, clock() - start)
        target_states = classify_wait_targets(
            config.targets,
            snapshot,
            wait_blocked=config.wait_blocked,
            liveness_checker=liveness_checker,
        )
        timed_out = _timed_out(elapsed, config.timeout_seconds)
        interrupted = bool(
            config.stop_requested is not None and config.stop_requested()
        )
        settlement = settle_wait_tick(
            config.targets,
            target_states,
            elapsed_seconds=elapsed,
            wait_blocked=config.wait_blocked,
            timed_out=timed_out,
            interrupted=interrupted,
        )
        yield WaitTick(
            index=index,
            elapsed_seconds=elapsed,
            target_states=target_states,
            settlement=settlement,
        )
        if settlement is not None:
            return
        sleep(_sleep_interval(config, elapsed))
        index += 1


def settle_wait_tick(
    targets: Sequence[WaitTarget],
    target_states: Sequence[WaitTargetState],
    *,
    elapsed_seconds: float,
    wait_blocked: bool,
    timed_out: bool = False,
    interrupted: bool = False,
) -> WaitSettlement | None:
    """Return a settlement when the current tick should end the wait."""

    states = tuple(target_states)
    all_stopped = all(
        is_stop_state(state.state, wait_blocked=wait_blocked) for state in states
    )
    if not targets:
        all_stopped = True
    if not (all_stopped or timed_out or interrupted):
        return None
    reason = None
    if interrupted:
        reason = "interrupted"
    elif timed_out:
        reason = "timeout"
    return make_settlement(
        states,
        elapsed_seconds=elapsed_seconds,
        timed_out=timed_out,
        interrupted=interrupted,
        reason=reason,
    )


def adaptive_poll_interval(elapsed_seconds: float) -> float:
    """Return the default poll interval for elapsed wait time."""

    if elapsed_seconds < 30.0:
        return 1.0
    if elapsed_seconds < 300.0:
        return 2.0
    return 5.0


def _sleep_interval(config: WaitWatchConfig, elapsed_seconds: float) -> float:
    interval = (
        config.interval_seconds
        if config.interval_seconds is not None
        else adaptive_poll_interval(elapsed_seconds)
    )
    if config.timeout_seconds is None:
        return max(0.0, interval)
    remaining = config.timeout_seconds - elapsed_seconds
    return max(0.0, min(interval, remaining))


def _timed_out(elapsed_seconds: float, timeout_seconds: float | None) -> bool:
    return timeout_seconds is not None and elapsed_seconds >= timeout_seconds
