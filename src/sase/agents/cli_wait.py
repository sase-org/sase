"""``sase agent wait`` — block until named agents reach a terminal state."""

from __future__ import annotations

import argparse
import difflib
import os
import re
import signal
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from rich.console import Console

from sase.agent.wait_watch import (
    WAIT_EXIT_INTERRUPTED,
    WAIT_EXIT_SUCCESS,
    WAIT_EXIT_USAGE,
    WaitSettlementOutcome,
    WaitTargetResolutionError,
    WaitWatchConfig,
    load_wait_caller_from_env,
    resolve_all_wait_targets,
    resolve_wait_targets,
    wait_scan_options,
    watch_wait_targets,
)
from sase.core.agent_scan_facade import scan_agent_artifacts
from sase.core.agent_scan_wire import AgentArtifactScanWire
from sase.core.cli_duration import parse_cli_duration
from sase.core.paths import sase_projects_dir

from ._wait_json import print_wait_json, wait_settlement_envelope
from ._wait_render_plain import (
    HEARTBEAT_SECONDS,
    WaitProgressTracker,
    render_heartbeat_line,
    render_initial_line,
    render_settle_summary_line,
    render_transition_line,
)

SnapshotProvider = Callable[[], AgentArtifactScanWire]
_UNKNOWN_TARGET_RE = re.compile(r"^no agent wait target found for '(.*)'$")


class _WaitSignalState:
    """Track the first SIGINT/SIGTERM delivered while a wait is polling."""

    def __init__(self) -> None:
        self.signum: int | None = None
        self._previous: dict[int, object] = {}

    def install(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                self._previous[sig] = signal.getsignal(sig)
                signal.signal(sig, self._handle)
            except (ValueError, OSError):
                continue

    def restore(self) -> None:
        for sig, handler in self._previous.items():
            try:
                signal.signal(sig, handler)  # type: ignore[arg-type]
            except (ValueError, OSError):
                continue

    def _handle(self, signum: int, _frame: object) -> None:
        self.signum = signum

    def requested(self) -> bool:
        return self.signum is not None

    def exit_code_override(self) -> int | None:
        if self.signum == signal.SIGTERM:
            return 143
        if self.signum == signal.SIGINT:
            return WAIT_EXIT_INTERRUPTED
        return None


def handle_agents_wait(
    args: argparse.Namespace,
    *,
    projects_root: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    snapshot_provider: SnapshotProvider | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    install_signal_handlers: bool = True,
    signal_state: _WaitSignalState | None = None,
) -> int:
    """Resolve targets, poll until settle, render output, and return the exit code."""
    names = list(getattr(args, "names", None) or [])
    include_all = bool(getattr(args, "all", False))
    project = getattr(args, "project", None)
    as_json = bool(getattr(args, "json", False))
    quiet = bool(getattr(args, "quiet", False))
    wait_blocked = bool(getattr(args, "wait_blocked", False))

    err_console = Console(stderr=True)

    if include_all and names:
        err_console.print(
            "sase agent wait: -a/--all cannot be combined with NAME arguments",
            style="red",
            soft_wrap=True,
        )
        return WAIT_EXIT_USAGE
    if not include_all and not names:
        err_console.print(
            "sase agent wait: provide at least one agent name or use -a/--all",
            style="red",
            soft_wrap=True,
        )
        return WAIT_EXIT_USAGE

    try:
        interval_seconds = _parse_duration_arg(
            getattr(args, "interval", None), flag="-i/--interval"
        )
        timeout_seconds = _parse_duration_arg(
            getattr(args, "timeout", None), flag="-t/--timeout"
        )
    except ValueError as exc:
        err_console.print(f"sase agent wait: {exc}", style="red", soft_wrap=True)
        return WAIT_EXIT_USAGE

    root = Path(projects_root) if projects_root is not None else sase_projects_dir()
    scan_options = wait_scan_options(project_name=project)
    provider = snapshot_provider or (lambda: scan_agent_artifacts(root, scan_options))
    caller = load_wait_caller_from_env(env if env is not None else os.environ)

    initial_snapshot = provider()
    try:
        if include_all:
            targets = resolve_all_wait_targets(
                initial_snapshot, project_name=project, caller=caller
            )
        else:
            targets = resolve_wait_targets(
                names, initial_snapshot, project_name=project, caller=caller
            )
    except WaitTargetResolutionError as exc:
        return _usage_error(
            str(exc), known_names=_known_names(initial_snapshot), err=err_console
        )

    if not targets:
        return _nothing_to_wait_for(as_json=as_json)

    state = signal_state or _WaitSignalState()
    if install_signal_handlers:
        state.install()

    config = WaitWatchConfig(
        targets=targets,
        interval_seconds=interval_seconds,
        timeout_seconds=timeout_seconds,
        wait_blocked=wait_blocked,
        stop_requested=state.requested,
    )

    show_progress = not as_json and not quiet
    if show_progress:
        err_console.print(render_initial_line(targets), soft_wrap=True)

    tracker = WaitProgressTracker()
    try:
        last_tick = None
        for tick in watch_wait_targets(config, provider, clock=clock, sleep=sleep):
            changed = tracker.observe(tick)
            if show_progress:
                for target_state in changed:
                    err_console.print(
                        render_transition_line(tick.elapsed_seconds, target_state),
                        markup=False,
                        soft_wrap=True,
                    )
                if (
                    not changed
                    and tick.elapsed_seconds - tracker.last_heartbeat_elapsed
                    >= HEARTBEAT_SECONDS
                ):
                    tracker.last_heartbeat_elapsed = tick.elapsed_seconds
                    err_console.print(
                        render_heartbeat_line(tick.elapsed_seconds, tick.target_states),
                        soft_wrap=True,
                    )
            last_tick = tick
            if tick.settled:
                break
    finally:
        if install_signal_handlers:
            state.restore()

    assert last_tick is not None and last_tick.settlement is not None
    settlement = last_tick.settlement
    exit_code = state.exit_code_override()
    if exit_code is None:
        exit_code = settlement.exit_code

    if as_json:
        durations = {
            target.key: tracker.duration_for(target, default=settlement.elapsed_seconds)
            for target in targets
        }
        print_wait_json(
            wait_settlement_envelope(
                settlement, durations=durations, exit_code=exit_code
            )
        )
    else:
        print(render_settle_summary_line(settlement, exit_code=exit_code))

    return exit_code


def _parse_duration_arg(raw: str | None, *, flag: str) -> float | None:
    if not raw:
        return None
    seconds, _label = parse_cli_duration(raw, flag=flag)
    return seconds


def _usage_error(message: str, *, known_names: Sequence[str], err: Console) -> int:
    full_message = f"sase agent wait: {message}"
    match = _UNKNOWN_TARGET_RE.match(message)
    if match:
        suggestions = difflib.get_close_matches(
            match.group(1), known_names, n=3, cutoff=0.4
        )
        if suggestions:
            full_message += f" (did you mean: {', '.join(suggestions)}?)"
    err.print(full_message, style="red", markup=False, soft_wrap=True)
    return WAIT_EXIT_USAGE


def _nothing_to_wait_for(*, as_json: bool) -> int:
    if as_json:
        print_wait_json(
            {
                "settled": WaitSettlementOutcome.SUCCEEDED.value,
                "exit_code": WAIT_EXIT_SUCCESS,
                "waited_seconds": 0.0,
                "timed_out": False,
                "targets": [],
            }
        )
    else:
        print("nothing to wait for: no matching agents are currently running")
    return WAIT_EXIT_SUCCESS


def _known_names(snapshot: AgentArtifactScanWire) -> tuple[str, ...]:
    names: list[str] = []
    for record in snapshot.records:
        meta = record.agent_meta
        if meta is not None and meta.name:
            names.append(meta.name)
        elif record.done is not None and record.done.name:
            names.append(record.done.name)
    return tuple(dict.fromkeys(names))


__all__ = [
    "handle_agents_wait",
]
