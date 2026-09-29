"""``sase tool wait`` lifecycle control: block until a run settles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import sys
import time
from typing import Any
from collections.abc import Callable

from sase.core.cli_duration import parse_cli_duration
from sase.core.tool_run import tool_run_show
from sase.tool._control_shared import (
    UnknownRunError,
    is_settled,
    load_run,
)
from sase.tool.control_outputs import output_paths_for_run
from sase.tool.liveness import reconcile_unsettled_tool_runs


_POLL_START_SECONDS = 0.05
_POLL_MAX_SECONDS = 0.5


@dataclass(frozen=True)
class ToolWaitCliRequest:
    run_id: str
    json: bool = False
    tail_lines: int | None = None
    timeout_raw: str | None = None


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
        if is_settled(run):
            return envelope
        if deadline is not None and time.monotonic() >= deadline:
            return None
        time.sleep(delay)
        delay = min(delay * 1.5, _POLL_MAX_SECONDS)


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
        run = load_run(run_id)
    except UnknownRunError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if is_settled(run):
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
            run = load_run(run_id)
        except UnknownRunError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        payload = _wait_json(run_id, run)
        payload["timed_out"] = True
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 124
    print(f"tool run {run_id} is still running", file=sys.stderr)
    try:
        run = load_run(run_id)
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
    "ToolWaitCliRequest",
    "handle_wait",
    "wait_for_settlement",
]
