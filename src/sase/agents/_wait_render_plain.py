"""Non-TTY and quiet-mode rendering for ``sase agent wait``."""

from __future__ import annotations

from sase.agent.wait_watch import (
    WaitSettlement,
    WaitState,
    WaitTarget,
    WaitTargetState,
    WaitTick,
)

WaitTargetKey = tuple[str, str, str | None, str | None]

HEARTBEAT_SECONDS = 60.0

_NAME_COLUMN_WIDTH = 24
_STATUS_COLUMN_WIDTH = 14


def render_initial_line(targets: tuple[WaitTarget, ...]) -> str:
    """Return the one-time line announcing what a wait is watching."""
    noun = "agent" if len(targets) == 1 else "agents"
    names = ", ".join(target.name for target in targets)
    return f"waiting on {len(targets)} {noun}: {names}"


def _format_elapsed_prefix(seconds: float) -> str:
    """Return a ``[+HH:MM:SS]`` prefix for *seconds* elapsed."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"[+{hours:02d}:{minutes:02d}:{secs:02d}]"


def format_duration(seconds: float) -> str:
    """Return a compact ``1h2m3s`` style duration for *seconds*."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes}m{secs}s"
    if minutes:
        return f"{minutes}m{secs}s"
    return f"{secs}s"


def wait_state_label(state: WaitState) -> str:
    """Return the uppercase status label used in plain and JSON output."""
    return state.value.upper()


def render_transition_line(elapsed_seconds: float, state: WaitTargetState) -> str:
    """Return one progress line for a target that just changed state."""
    label = wait_state_label(state.state)
    detail = f"  {state.reason}" if state.reason and (state.failed) else ""
    return (
        f"{_format_elapsed_prefix(elapsed_seconds)} "
        f"{state.target.name:<{_NAME_COLUMN_WIDTH}} "
        f"{label:<{_STATUS_COLUMN_WIDTH}} "
        f"({format_duration(elapsed_seconds)}){detail}"
    )


def render_heartbeat_line(
    elapsed_seconds: float, target_states: tuple[WaitTargetState, ...]
) -> str:
    """Return a periodic line reporting how many targets are still pending."""
    pending = sum(
        1 for state in target_states if not state.succeeded and not state.failed
    )
    return (
        f"{_format_elapsed_prefix(elapsed_seconds)} "
        f"still waiting on {pending} of {len(target_states)}"
    )


def render_settle_summary_line(settlement: WaitSettlement, *, exit_code: int) -> str:
    """Return the one-line settle summary printed to stdout."""
    succeeded = sum(1 for state in settlement.target_states if state.succeeded)
    failed = sum(1 for state in settlement.target_states if state.failed)
    blocked = sum(1 for state in settlement.target_states if state.blocked)
    return (
        f"settled: {succeeded} succeeded, {failed} failed, {blocked} blocked "
        f"in {format_duration(settlement.elapsed_seconds)} (exit {exit_code})"
    )


class WaitProgressTracker:
    """Track per-target state changes across ticks for progress rendering."""

    def __init__(self) -> None:
        self._last_state: dict[WaitTargetKey, WaitState] = {}
        self.last_change_elapsed: dict[WaitTargetKey, float] = {}
        self.last_heartbeat_elapsed = 0.0

    def observe(self, tick: WaitTick) -> list[WaitTargetState]:
        """Record *tick* and return the target states that just changed."""
        changed: list[WaitTargetState] = []
        for state in tick.target_states:
            key = state.target.key
            if self._last_state.get(key) != state.state:
                self._last_state[key] = state.state
                self.last_change_elapsed[key] = tick.elapsed_seconds
                changed.append(state)
        return changed

    def duration_for(self, target: WaitTarget, *, default: float) -> float:
        return self.last_change_elapsed.get(target.key, default)


__all__ = [
    "HEARTBEAT_SECONDS",
    "WaitProgressTracker",
    "WaitTargetKey",
    "format_duration",
    "render_heartbeat_line",
    "render_initial_line",
    "render_settle_summary_line",
    "render_transition_line",
    "wait_state_label",
]
