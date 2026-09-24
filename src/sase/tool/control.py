"""``sase tool stop`` and ``sase tool wait`` lifecycle controls.

Both commands are ownership-aware facades over a run's execution owner:
a hand-off run stops through its proc or monitor owner, an inline run
signals only its identity-matched wrapper, and a nested foreground run
is refused with a pointer to the owner that must be stopped instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import signal
import sys
import time
from typing import Any
from collections.abc import Callable

from sase.core.cli_duration import parse_cli_duration
from sase.core.process_identity import process_identity_token
from sase.core.tool_run import (
    tool_run_finish,
    tool_run_request_stop,
    tool_run_show,
)
from sase.tool.liveness import current_boot_id, reconcile_unsettled_tool_runs


TERMINAL_RUN_STATES = frozenset(
    {"succeeded", "failed", "signaled", "interrupted", "lost"}
)
UNSETTLED_RUN_STATES = frozenset({"created", "running"})

_POLL_START_SECONDS = 0.05
_POLL_MAX_SECONDS = 0.5


class UnknownRunError(ValueError):
    """The requested run id is not in the ledger (exit 2)."""


@dataclass(frozen=True)
class ToolStopCliRequest:
    run_id: str
    json: bool = False


@dataclass(frozen=True)
class ToolWaitCliRequest:
    run_id: str
    json: bool = False
    tail_lines: int | None = None
    timeout_raw: str | None = None


def _requested_by() -> str:
    return (
        (os.environ.get("SASE_AGENT_NAME") or "").strip()
        or (os.environ.get("USER") or "").strip()
        or "cli"
    )


def _load_run(run_id: str) -> dict[str, Any]:
    """Return the stored run dict, or raise :class:`UnknownRunError`."""

    envelope = tool_run_show(run_id)
    run = envelope.get("run")
    if not isinstance(run, dict) or str(run.get("run_id") or "") != run_id:
        diagnostic = "; ".join(str(item) for item in envelope.get("diagnostics") or ())
        raise UnknownRunError(diagnostic or f"tool run {run_id} was not found")
    return run


def _is_settled(run: dict[str, Any]) -> bool:
    return str(run.get("state") or "") not in UNSETTLED_RUN_STATES


def _is_handoff(run: dict[str, Any]) -> bool:
    return str(run.get("launch_mode") or "") == "handoff"


def wait_for_settlement(
    run_id: str,
    *,
    timeout_s: float | None = None,
    on_poll: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any] | None:
    """Poll the ledger until *run_id* settles.

    Runs a read-only reconcile on every poll (no reaping) so a dead owner
    settles while someone watches. Returns the final ``tool_run_show``
    envelope, or ``None`` when *timeout_s* passes first. Raises
    :class:`UnknownRunError` for an unknown id. Never affects the run.
    """

    deadline = None if timeout_s is None else time.monotonic() + timeout_s
    delay = _POLL_START_SECONDS
    last: dict[str, Any] | None = None
    while True:
        reconcile_unsettled_tool_runs()
        try:
            envelope = tool_run_show(run_id)
        except Exception:  # noqa: BLE001 - a transient read retries.
            if deadline is not None and time.monotonic() >= deadline:
                return last
            time.sleep(delay)
            delay = min(delay * 1.5, _POLL_MAX_SECONDS)
            continue
        run = envelope.get("run")
        if not isinstance(run, dict):
            raise UnknownRunError(
                "; ".join(str(i) for i in envelope.get("diagnostics") or ())
                or f"tool run {run_id} was not found"
            )
        last = envelope
        if on_poll is not None:
            on_poll(envelope)
        if _is_settled(run):
            return envelope
        if deadline is not None and time.monotonic() >= deadline:
            return None
        time.sleep(delay)
        delay = min(delay * 1.5, _POLL_MAX_SECONDS)


def _owner_terminal(run: dict[str, Any]) -> bool | None:
    """Return True when the run's owner is terminal, False when active.

    ``None`` means unknown: no owner, an unreadable store, or a state that
    cannot be classified. Only hand-off runs have a meaningful owner.
    """

    kind = str(run.get("owner_kind") or "")
    owner_id = str(run.get("owner_id") or "")
    if not kind or not owner_id:
        return None
    if kind == "proc":
        try:
            from sase.procs.models import TERMINAL_PROC_STATUSES
            from sase.procs.store import get_proc
        except Exception:  # noqa: BLE001 - unknown owner is not proof.
            return None
        try:
            proc = get_proc(owner_id)
        except Exception:  # noqa: BLE001 - unreadable store is unknown.
            return None
        if proc is None:
            return True
        return proc.status in TERMINAL_PROC_STATUSES
    if kind == "monitor":
        try:
            from sase.monitor.store import list_monitors, resolve_monitor_ref
        except Exception:  # noqa: BLE001 - unknown owner is not proof.
            return None
        try:
            records = list_monitors()
            record = resolve_monitor_ref(owner_id, records)
        except Exception:  # noqa: BLE001 - expired owners are missing.
            return True
        return bool(record.is_terminal)
    return None


def handle_stop(request: ToolStopCliRequest) -> int:
    """Record a durable stop request, then route through the run's owner."""

    run_id = request.run_id.strip()
    if not run_id:
        print("Usage: sase tool stop RUN", file=sys.stderr)
        return 2
    try:
        stop_result = tool_run_request_stop(
            {
                "schema_version": 1,
                "run_id": run_id,
                "requested_by": _requested_by(),
                "reason": "stop",
            }
        )
    except Exception as exc:  # noqa: BLE001 - unknown runs exit 2.
        if "not found" in str(exc).lower() or "notfound" in type(exc).__name__.lower():
            print(f"tool run {run_id} was not found", file=sys.stderr)
            return 2
        print(f"sase tool stop {run_id}: {exc}", file=sys.stderr)
        return 1
    outcome = str(stop_result.get("outcome") or "")
    try:
        run = _load_run(run_id)
    except UnknownRunError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    state = str(run.get("state") or "")
    if state not in UNSETTLED_RUN_STATES:
        return _report_stop_outcome(
            request, run_id, f"already {state}", state, already=True
        )
    if outcome == "already_settled":
        shown = _load_run(run_id)
        return _report_stop_outcome(
            request,
            run_id,
            f"already {shown.get('state')}",
            str(shown.get("state") or ""),
            already=True,
        )
    control_error = _route_owner_stop(run)
    if control_error is not None:
        return control_error
    try:
        settled = _load_run(run_id)
    except UnknownRunError as exc:  # noqa: BLE001 - the ledger lost the run.
        print(str(exc), file=sys.stderr)
        return 1
    if _is_settled(settled):
        return _report_stop_outcome(
            request, run_id, "stopped", str(settled.get("state") or "")
        )
    return _report_stop_outcome(
        request, run_id, "stop requested", str(settled.get("state") or "")
    )


def _report_stop_outcome(
    request: ToolStopCliRequest,
    run_id: str,
    outcome: str,
    state: str,
    *,
    already: bool = False,
) -> int:
    if request.json:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "outcome": outcome,
                    "state": state,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if already:
        print(f"tool run {run_id} is {outcome}; nothing to do")
    else:
        print(f"tool run {run_id}: {outcome}")
    return 0


def _route_owner_stop(run: dict[str, Any]) -> int | None:
    """Stop through the run's owner. Returns an exit code, or None to report."""

    run_id = str(run.get("run_id") or "")
    owner_kind = str(run.get("owner_kind") or "")
    owner_id = str(run.get("owner_id") or "")
    parent_id = str(run.get("parent_run_id") or "")
    if _is_handoff(run) and owner_kind == "proc" and owner_id:
        return _stop_proc_owner(run_id, owner_id)
    if _is_handoff(run) and owner_kind == "monitor" and owner_id:
        return _stop_monitor_owner(run_id, owner_id)
    if _is_handoff(run) and owner_kind and owner_id:
        print(
            f"sase tool stop {run_id}: unknown owner {owner_kind}:{owner_id}",
            file=sys.stderr,
        )
        return 1
    if parent_id or owner_kind:
        return _refuse_nested(run)
    return _signal_inline_wrapper(run)


def _stop_proc_owner(run_id: str, proc_id: str) -> int | None:
    try:
        from sase.procs.runner import ProcControlError, kill_proc
    except Exception as exc:  # noqa: BLE001 - control failures exit 1.
        print(
            f"sase tool stop {run_id}: proc control unavailable ({exc})",
            file=sys.stderr,
        )
        return 1
    try:
        kill_proc(proc_id)
    except Exception as exc:
        message = str(exc)
        # Completion racing the stop surfaces as a terminal-status refusal
        # from the proc store; the stop still happened.
        if "terminal" in message.lower():
            return _settle_unstarted(run_id)
        from sase.procs.runner import ProcControlError

        if isinstance(exc, ProcControlError) and "no proc with id" in message:
            return _settle_unstarted(run_id)
        print(f"sase tool stop {run_id}: {message}", file=sys.stderr)
        return 1
    return _settle_unstarted(run_id)


def _stop_monitor_owner(run_id: str, monitor_id: str) -> int | None:
    try:
        from sase.monitor.store import (
            list_monitors,
            resolve_monitor_ref,
            stop_monitor,
        )
    except Exception as exc:  # noqa: BLE001 - control failures exit 1.
        print(
            f"sase tool stop {run_id}: monitor control unavailable ({exc})",
            file=sys.stderr,
        )
        return 1
    try:
        record = resolve_monitor_ref(monitor_id, list_monitors())
    except Exception:
        # An expired or pruned owner cannot be signaled; a run that never
        # started still settles so the stop is observable.
        return _settle_unstarted(run_id)
    try:
        # stop_monitor suppresses the follow-up by design: a stopped
        # monitor never launches its next action.
        current = stop_monitor(record)
    except Exception as exc:  # noqa: BLE001 - control failures exit 1.
        print(f"sase tool stop {run_id}: {exc}", file=sys.stderr)
        return 1
    if current.monitor_state == "running":
        print(
            f"sase tool stop {run_id}: monitor {monitor_id} is still running",
            file=sys.stderr,
        )
        return 1
    return _settle_unstarted(run_id)


def _settle_unstarted(run_id: str) -> int | None:
    """Settle a still-``created`` run whose owner is gone as stopped."""

    try:
        run = _load_run(run_id)
    except UnknownRunError:
        return None
    if str(run.get("state") or "") != "created":
        return None
    terminal = _owner_terminal(run)
    if terminal is not True:
        return None
    try:
        tool_run_finish(
            {
                "schema_version": 1,
                "run_id": run_id,
                "state": "signaled",
                "terminal_cause": "stop_requested",
                "diagnostics": ["command was not run"],
                "duration_ms": 0,
            }
        )
    except Exception:  # noqa: BLE001 - reconcile settles what finish raced.
        pass
    return None


def _refuse_nested(run: dict[str, Any]) -> int:
    run_id = str(run.get("run_id") or "")
    parent_id = str(run.get("parent_run_id") or "")
    owner_kind = str(run.get("owner_kind") or "")
    owner_id = str(run.get("owner_id") or "")
    if parent_id:
        pointer = f"parent tool run {parent_id}"
        command = f"sase tool stop {parent_id}"
    elif owner_kind == "proc":
        pointer = f"proc {owner_id}"
        command = f"sase proc kill {owner_id}"
    elif owner_kind == "monitor":
        pointer = f"monitor {owner_id}"
        command = f"sase monitor stop {owner_id}"
    else:
        pointer = "its enclosing owner"
        command = "the owner command"
    print(
        f"sase tool stop {run_id}: refusing to stop a nested foreground run; "
        f"stop {pointer} with `{command}` instead",
        file=sys.stderr,
    )
    return 2


def _signal_inline_wrapper(run: dict[str, Any]) -> int | None:
    run_id = str(run.get("run_id") or "")
    pid_raw = run.get("wrapper_pid")
    if pid_raw is None:
        print(
            f"sase tool stop {run_id}: wrapper pid was not recorded; nothing signaled",
            file=sys.stderr,
        )
        return 1
    try:
        pid = int(pid_raw)
    except (TypeError, ValueError):
        print(
            f"sase tool stop {run_id}: wrapper pid is not an integer; nothing signaled",
            file=sys.stderr,
        )
        return 1
    recorded = run.get("process_start_identity")
    if isinstance(recorded, str) and recorded:
        current = process_identity_token(pid)
        if not current:
            print(
                f"sase tool stop {run_id}: wrapper identity is unreadable; "
                "not signaling (PID reuse is never proof)",
                file=sys.stderr,
            )
            return 1
        if current != recorded:
            print(
                f"sase tool stop {run_id}: wrapper identity no longer matches; "
                "not signaling (stale pid, PID reuse?)",
                file=sys.stderr,
            )
            return 1
    recorded_boot = str(run.get("boot_id") or "")
    if recorded_boot:
        boot = current_boot_id()
        if boot and recorded_boot != boot:
            print(
                f"sase tool stop {run_id}: wrapper is from a previous boot; "
                "not signaling",
                file=sys.stderr,
            )
            return 1
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return None
    except PermissionError:
        print(
            f"sase tool stop {run_id}: permission denied signaling pid {pid}",
            file=sys.stderr,
        )
        return 1
    except OSError as exc:
        print(
            f"sase tool stop {run_id}: cannot signal pid {pid} ({exc})",
            file=sys.stderr,
        )
        return 1
    return None


def handle_wait(request: ToolWaitCliRequest) -> int:
    """Block until the run settles, mirroring its exit code."""

    run_id = request.run_id.strip()
    if not run_id:
        print("Usage: sase tool wait RUN", file=sys.stderr)
        return 2
    timeout_s: float | None = None
    if request.timeout_raw is not None:
        try:
            timeout_s, _ = parse_cli_duration(request.timeout_raw, flag="--timeout")
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    tail_lines: int | None = None
    if request.tail_lines is not None:
        if request.tail_lines < 0:
            print("-T/--tail-lines must be >= 0", file=sys.stderr)
            return 2
        tail_lines = request.tail_lines
    try:
        run = _load_run(run_id)
    except UnknownRunError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if _is_settled(run):
        return _report_wait_outcome(request, run_id, run)
    try:
        envelope = wait_for_settlement(run_id, timeout_s=timeout_s)
    except UnknownRunError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("sase tool wait: interrupted; the run continues", file=sys.stderr)
        return 130
    if envelope is None:
        return _report_wait_timeout(request, run_id, tail_lines)
    final = envelope.get("run")
    if not isinstance(final, dict):
        print(f"tool run {run_id} was not found", file=sys.stderr)
        return 2
    return _report_wait_outcome(request, run_id, final)


def _report_wait_outcome(
    request: ToolWaitCliRequest, run_id: str, run: dict[str, Any]
) -> int:
    if request.json:
        print(json.dumps(_wait_json(run_id, run), indent=2, sort_keys=True))
    exit_code = run.get("exit_code")
    if type(exit_code) is int:
        if not request.json:
            _print_wait_tail(run_id, run, request.tail_lines)
        return exit_code
    cause = str(run.get("terminal_cause") or run.get("state") or "unknown")
    if not request.json:
        print(
            f"tool run {run_id} settled without an exit code ({cause})", file=sys.stderr
        )
        _print_wait_tail(run_id, run, request.tail_lines)
    return 1


def _report_wait_timeout(
    request: ToolWaitCliRequest, run_id: str, tail_lines: int | None
) -> int:
    if request.json:
        try:
            run = _load_run(run_id)
        except UnknownRunError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        payload = _wait_json(run_id, run)
        payload["timed_out"] = True
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 124
    print(f"tool run {run_id} is still running", file=sys.stderr)
    try:
        run = _load_run(run_id)
    except UnknownRunError:
        return 124
    _print_wait_tail(run_id, run, tail_lines)
    return 124


def _wait_json(run_id: str, run: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "state": run.get("state"),
        "exit_code": run.get("exit_code"),
        "terminal_cause": run.get("terminal_cause"),
        "settled_by": run.get("settled_by"),
        "timed_out": False,
    }


def _print_wait_tail(run_id: str, run: dict[str, Any], tail_lines: int | None) -> None:
    if tail_lines is None:
        return
    tail = _read_output_tail(run, tail_lines)
    if tail:
        print(f"--- last {tail_lines} lines of {run_id} ---", file=sys.stderr)
        sys.stderr.write(tail if tail.endswith("\n") else tail + "\n")


def output_paths_for_run(run: dict[str, Any]) -> list[Path]:
    """Return the output-of-record paths for *run*, in read order."""

    logs = run.get("logs")
    logs_map = logs if isinstance(logs, dict) else {}
    owner_log = logs_map.get("owner_log_path")
    if owner_log:
        return [Path(str(owner_log))]
    kind = str(run.get("owner_kind") or "")
    owner_id = str(run.get("owner_id") or "")
    if kind == "proc" and owner_id:
        try:
            from sase.procs.store import get_proc

            proc = get_proc(owner_id)
        except Exception:  # noqa: BLE001 - fall through to retained logs.
            proc = None
        if proc is not None and proc.log_path:
            return [Path(proc.log_path)]
    if kind == "monitor" and owner_id:
        path = monitor_output_path(run, owner_id)
        if path is not None:
            return [path]
    paths: list[Path] = []
    for key in ("stdout_path", "stderr_path"):
        raw = logs_map.get(key)
        if raw:
            paths.append(Path(str(raw)))
    return paths


def monitor_output_path(run: dict[str, Any], monitor_id: str) -> Path | None:
    try:
        from sase.monitor.logs import monitor_log_path
        from sase.monitor.store import list_monitors, resolve_monitor_ref
    except Exception:  # noqa: BLE001 - no monitor reader available.
        return None
    try:
        records = list_monitors(project=str(run.get("project") or "") or None)
        record = resolve_monitor_ref(monitor_id, records)
    except Exception:  # noqa: BLE001 - expired owners have no log.
        return None
    raw = record.output_path or None
    if raw:
        return Path(raw)
    try:
        return Path(monitor_log_path(record.artifacts_dir))
    except Exception:  # noqa: BLE001 - unresolvable log path.
        return None


def _read_output_tail(run: dict[str, Any], lines: int) -> str:
    """Return the last *lines* lines of the run's output of record."""

    if lines <= 0:
        return ""
    chunks: list[str] = []
    remaining = lines
    for path in reversed(output_paths_for_run(run)):
        text = _read_tail_lines(path, remaining)
        if text:
            chunks.append(text)
            remaining -= len(text.splitlines())
            if remaining <= 0:
                break
    return "".join(reversed(chunks))


def _read_tail_lines(path: Path, lines: int) -> str:
    if lines <= 0:
        return ""
    try:
        if not path.is_file():
            return ""
        # Proc logs rotate to a `.1` sibling; the query replay path reads
        # both segments, so tails do too.
        rotated = path.with_name(f"{path.name}.1")
        prior = ""
        if rotated.is_file():
            prior = _tail_of_file(rotated, lines)
        current = _tail_of_file(path, lines)
        merged = "".join((prior, current)).splitlines(keepends=True)[-lines:]
        return "".join(merged)
    except OSError:
        return ""


def _tail_of_file(path: Path, lines: int) -> str:
    try:
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            block = 8192
            data = b""
            while len(data.splitlines()) <= lines and size > 0:
                step = min(block, size)
                size -= step
                handle.seek(size)
                data = handle.read(step) + data
                if size == 0:
                    break
                block *= 2
    except OSError:
        return ""
    return data.decode("utf-8", "replace")


__all__ = [
    "UnknownRunError",
    "ToolStopCliRequest",
    "ToolWaitCliRequest",
    "handle_stop",
    "handle_wait",
    "monitor_output_path",
    "output_paths_for_run",
    "wait_for_settlement",
]
