"""Realtime and JSON rendering for ``sase axe restart``."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from types import TracebackType
from typing import TextIO

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from .process import (
    AxeRestartEvent,
    AxeStartAttempt,
    AxeStartResult,
    AxeStopResult,
    RestartFinished,
    RestartPlanned,
    RetryScheduled,
    StartAttemptBegan,
    StartAttemptSettled,
    StartAttemptSpawned,
    StopBegan,
    StopFinished,
    VerifyProgress,
)

#: Bump when the JSON result payload shape changes incompatibly.
RESTART_JSON_SCHEMA_VERSION = 1

_BORDER_STYLE = "cyan"
_SUCCESS_STYLE = "bold green"
_FAILURE_STYLE = "bold red"


def should_render_restart_live(
    *,
    as_json: bool,
    stdout_isatty: bool | None = None,
) -> bool:
    """Return whether the refreshing TTY restart panel should be used."""
    if as_json:
        return False
    if stdout_isatty is not None:
        return stdout_isatty
    return sys.stdout.isatty()


@dataclass
class _RestartLiveState:
    """Mutable view of restart progress folded from an event stream."""

    lumberjacks: tuple[str, ...] = ()
    max_attempts: int = 1
    attempt_number: int = 0
    stop_result: AxeStopResult | None = None
    stop_elapsed: float = 0.0
    start_status: str | None = None
    start_pid: int | None = None
    start_message: str = ""
    verify_fresh: tuple[str, ...] = ()
    verify_pending: tuple[str, ...] = ()
    verify_elapsed: float = 0.0
    verify_timeout: float = 0.0
    attempts: list[AxeStartAttempt] = field(default_factory=list)
    retry_delay: float | None = None


def _apply_restart_event(state: _RestartLiveState, event: AxeRestartEvent) -> None:
    """Fold one restart event into *state* (pure mutation, no I/O)."""
    if isinstance(event, RestartPlanned):
        state.lumberjacks = event.lumberjacks
        state.max_attempts = event.max_attempts
    elif isinstance(event, StopFinished):
        state.stop_result = event.result
        state.stop_elapsed = event.elapsed_seconds
    elif isinstance(event, StartAttemptBegan):
        state.attempt_number = event.number
        state.max_attempts = event.max_attempts
        state.start_status = None
        state.start_pid = None
        state.start_message = ""
        state.verify_fresh = ()
        state.verify_pending = state.lumberjacks
        state.verify_elapsed = 0.0
        state.retry_delay = None
    elif isinstance(event, StartAttemptSpawned):
        state.start_status = event.status
        state.start_pid = event.pid
        state.start_message = event.message
    elif isinstance(event, VerifyProgress):
        state.verify_fresh = event.fresh
        state.verify_pending = event.pending
        state.verify_elapsed = event.elapsed_seconds
        state.verify_timeout = event.timeout_seconds
    elif isinstance(event, StartAttemptSettled):
        state.attempts.append(event.attempt)
    elif isinstance(event, RetryScheduled):
        state.retry_delay = event.delay_seconds
    elif isinstance(event, (StopBegan, RestartFinished)):
        pass


def _stop_summary_text(result: AxeStopResult) -> str:
    if not result.terminated_anything:
        return "AXE was not running — nothing to stop"
    parts: list[str] = []
    if result.orchestrator_signaled:
        label = (
            "orchestrator" if result.orchestrator_stopped else "orchestrator signaled"
        )
        if result.orchestrator_pid is not None:
            label = f"{label} (pid {result.orchestrator_pid})"
        parts.append(label)
    if result.lumberjacks_stopped:
        parts.append(f"{result.lumberjacks_stopped} lumberjack(s)")
    if result.force_killed_processes:
        parts.append(f"{result.force_killed_processes} matched axe process(es)")
    if not parts:
        return result.summary()
    return "Stopped " + " + ".join(parts)


def _start_status_text(status: str | None, pid: int | None) -> str:
    if status == "started":
        return f"Started orchestrator (pid {pid})"
    return f"Orchestrator already running (pid {pid})"


def _attempt_line(attempt: AxeStartAttempt) -> str:
    detail = attempt.verification_error or attempt.message or attempt.status
    return f"Attempt {attempt.number}: {detail}"


def _format_clock(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}"


def _stop_row(state: _RestartLiveState) -> Text:
    if state.stop_result is None:
        return Text("◐ Stopping orchestrator…", style="cyan")
    if not state.stop_result.terminated_anything:
        return Text("○ AXE was not running — nothing to stop", style="dim")
    return Text(
        f"✓ {_stop_summary_text(state.stop_result)}   {state.stop_elapsed:.1f}s",
        style="green",
    )


def _start_row(state: _RestartLiveState) -> Text:
    if state.start_status is None:
        return Text(
            f"◐ Starting orchestrator (attempt {state.attempt_number}/"
            f"{state.max_attempts})…",
            style="cyan",
        )
    if state.start_status in {"started", "already_running"}:
        return Text(
            f"✓ {_start_status_text(state.start_status, state.start_pid)}",
            style="green",
        )
    return Text(f"✗ {state.start_message or state.start_status}", style="red")


def _verify_row(state: _RestartLiveState) -> Text:
    total = len(state.verify_fresh) + len(state.verify_pending)
    if not state.verify_pending:
        return Text(
            f"✓ Verified {total}/{total} lumberjack heartbeats fresh", style="green"
        )
    return Text(
        f"◐ Verifying lumberjack heartbeats · {len(state.verify_fresh)}/{total} fresh"
        f"   {state.verify_elapsed:.1f}s / {state.verify_timeout:g}s",
        style="cyan",
    )


def _lumberjack_rows(state: _RestartLiveState) -> list[Text]:
    rows: list[Text] = []
    for name in state.lumberjacks:
        if name in state.verify_fresh:
            rows.append(Text(f"    ✓ {name}   fresh", style="green"))
        else:
            rows.append(Text(f"    ◌ {name}   waiting…", style="dim"))
    return rows


def _render_restart_live_panel(
    state: _RestartLiveState, *, elapsed_seconds: float
) -> Panel:
    """Return the in-flight restart panel for *state* (pure, no I/O)."""
    rows: list[Text] = [_stop_row(state), _start_row(state)]
    if state.start_status in {"started", "already_running"}:
        rows.append(_verify_row(state))
        rows.extend(_lumberjack_rows(state))
    if state.retry_delay is not None:
        rows.append(
            Text(
                f"Attempt {state.attempt_number} failed; "
                f"retrying in {state.retry_delay:g}s…",
                style="yellow",
            )
        )
    title = (
        f"Restarting AXE · attempt {max(state.attempt_number, 1)}/"
        f"{state.max_attempts} · {_format_clock(elapsed_seconds)}"
    )
    return Panel(
        Group(*rows),
        title=title,
        title_align="left",
        border_style=_BORDER_STYLE,
        box=box.ROUNDED,
    )


def render_restart_settle_panel(
    result: AxeStartResult,
    state: _RestartLiveState,
    *,
    elapsed_seconds: float,
) -> Panel:
    """Return the post-teardown settle panel for a finished restart."""
    if result.succeeded and result.verified:
        total = len(state.lumberjacks)
        body = Text()
        body.append(
            f"✓ Verified running · orchestrator pid {result.pid} · "
            f"{elapsed_seconds:.1f}s total\n",
            style=_SUCCESS_STYLE,
        )
        body.append(
            f"  {total}/{total} lumberjack heartbeats fresh: "
            f"{', '.join(state.lumberjacks) or '-'}"
        )
        return Panel(body, title="AXE restarted", border_style="green", box=box.ROUNDED)

    body = Text()
    for attempt in result.attempts:
        body.append(f"{_attempt_line(attempt)}\n", style="red")
    body.append(f"{result.message}\n\n", style=_FAILURE_STYLE)
    body.append("AXE may be down. Next steps:\n", style="yellow")
    body.append("  $ sase axe status", style="bold cyan")
    body.append(" — inspect the health snapshot\n")
    body.append("  $ sase axe ensure", style="bold cyan")
    body.append(" — let the watchdog attempt to heal")
    return Panel(body, title="AXE restart failed", border_style="red", box=box.ROUNDED)


class RestartLiveRenderer:
    """Refreshing ``rich.Live`` panel torn down in ``finally``."""

    def __init__(
        self,
        console: Console,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._console = console
        self._clock = clock
        self._live: Live | None = None
        self._start_time = 0.0
        self.state = _RestartLiveState()

    def __enter__(self) -> RestartLiveRenderer:
        self._start_time = self._clock()
        self._live = Live(
            Text(""),
            console=self._console,
            transient=True,
            refresh_per_second=4,
        )
        self._live.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        live = self._live
        self._live = None
        if live is not None:
            live.__exit__(exc_type, exc, tb)

    def handle_event(self, event: AxeRestartEvent) -> None:
        _apply_restart_event(self.state, event)
        if self._live is not None:
            elapsed = self._clock() - self._start_time
            self._live.update(
                _render_restart_live_panel(self.state, elapsed_seconds=elapsed)
            )


class RestartPlainRenderer:
    """Print restart milestone lines immediately as events arrive."""

    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console()
        self._attempt_number = 1
        self._max_attempts = 1
        self._verify_announced = False
        self._printed_fresh: set[str] = set()

    def handle_event(self, event: AxeRestartEvent) -> None:
        if isinstance(event, RestartPlanned):
            self._max_attempts = event.max_attempts
        elif isinstance(event, StopBegan):
            self._console.print("Stopping AXE…")
        elif isinstance(event, StopFinished):
            self._print_stop_finished(event)
        elif isinstance(event, StartAttemptBegan):
            self._attempt_number = event.number
            self._max_attempts = event.max_attempts
            self._verify_announced = False
            self._printed_fresh = set()
            self._console.print(
                f"Starting AXE (attempt {event.number}/{event.max_attempts})…"
            )
        elif isinstance(event, StartAttemptSpawned):
            self._print_start_spawned(event)
        elif isinstance(event, VerifyProgress):
            self._print_verify_progress(event)
        elif isinstance(event, RetryScheduled):
            self._console.print(
                f"Attempt {self._attempt_number} failed; "
                f"retrying in {event.delay_seconds:g}s…"
            )
        elif isinstance(event, RestartFinished):
            self._print_finished(event)

    def _print_stop_finished(self, event: StopFinished) -> None:
        if not event.result.terminated_anything:
            self._console.print("AXE was not running — nothing to stop")
            return
        self._console.print(
            f"{_stop_summary_text(event.result)} in {event.elapsed_seconds:.1f}s"
        )

    def _print_start_spawned(self, event: StartAttemptSpawned) -> None:
        if event.status in {"started", "already_running"}:
            self._console.print(_start_status_text(event.status, event.pid))
        else:
            self._console.print(
                f"Attempt {event.number} failed to start: "
                f"{event.message or event.status}"
            )

    def _print_verify_progress(self, event: VerifyProgress) -> None:
        total = len(event.fresh) + len(event.pending)
        if not self._verify_announced:
            self._verify_announced = True
            noun = "heartbeat" if total == 1 else "heartbeats"
            self._console.print(
                f"Verifying {total} lumberjack {noun} "
                f"(timeout {event.timeout_seconds:g}s)…"
            )
        newly_fresh = sorted(
            name for name in event.fresh if name not in self._printed_fresh
        )
        if not newly_fresh:
            return
        self._printed_fresh.update(newly_fresh)
        names = " · ".join(f"{name} fresh" for name in newly_fresh)
        self._console.print(f"  {names}")

    def _print_finished(self, event: RestartFinished) -> None:
        result = event.result
        if result.succeeded and result.verified:
            self._console.print(
                f"AXE restarted and verified (pid {result.pid}) "
                f"in {event.elapsed_seconds:.1f}s"
            )
            return
        self._console.print(result.message)
        self._console.print(
            "AXE may be down. Run `sase axe status` or `sase axe ensure`."
        )


def render_restart_json(
    result: AxeStartResult,
    elapsed_seconds: float,
    *,
    stream: TextIO | None = None,
) -> None:
    """Write the deterministic schema-version-1 restart result as plain JSON."""
    target = stream or sys.stdout
    payload = {
        "schema_version": RESTART_JSON_SCHEMA_VERSION,
        "status": result.status,
        "pid": result.pid,
        "message": result.message,
        "verified": result.verified,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "attempts": [
            {
                "number": attempt.number,
                "status": attempt.status,
                "pid": attempt.pid,
                "message": attempt.message,
                "verified": attempt.verified,
                "verification_error": attempt.verification_error,
            }
            for attempt in result.attempts
        ],
    }
    json.dump(payload, target, indent=2, sort_keys=True, ensure_ascii=False)
    target.write("\n")


__all__ = [
    "RESTART_JSON_SCHEMA_VERSION",
    "RestartLiveRenderer",
    "RestartPlainRenderer",
    "render_restart_json",
    "render_restart_settle_panel",
    "should_render_restart_live",
]
