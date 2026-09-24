"""Reserve a monitor-owned ToolRun hand-off before the monitor proc starts.

The caller (:func:`sase.monitor.start.start_monitor`) resolves the monitor's
proc argv with E1.5 wrapping first, then asks for the ``tool run`` words behind that
argv via :func:`sase.monitor.tool_wrap.monitor_tool_run_words`. When words
are present they are parsed with the real ``tool run`` parser: output-mode
options (``-q``/``-v``/``-T``) or an unparsable remainder keep the E1.5 argv
untouched. Otherwise the words resolve against the monitor cwd and reserve
a ``created`` hand-off run owned by the monitor, and the proc argv becomes
the adopting worker argv.

``monitor_command`` and ``monitor_execution_argv`` stay exactly as written
so prepared-completion ``-f`` bindings keep matching; the run id persists
as the flat ``monitor_tool_run_id`` meta field.
"""

from __future__ import annotations

import argparse
import contextlib
import io
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sase.main.parser_tool import register_tool_parser
from sase.tool.argv import ToolRunUsageError, resolve_run_argv
from sase.tool.handoff import HandoffReservation, reserve_handoff_run

#: One-line monitor-log prefix explaining a hand-off that fell back to E1.5
#: wrapping because its reservation could not be committed.
RESERVATION_FALLBACK_LOG_PREFIX = "sase: tool run not reserved"


def format_reservation_fallback_line(reason: str) -> str:
    """Return the single log line for a reservation that fell back to E1.5."""
    one_line = " ".join(str(reason).split()) or "unknown error"
    return f"{RESERVATION_FALLBACK_LOG_PREFIX} ({one_line}); running wrapped\n"


def _parse_monitor_tool_words(words: Sequence[str]) -> tuple[str, ...] | None:
    """Parse ``tool run`` *words* with the real parser, or return ``None``.

    ``None`` means the E1.5 argv stays untouched: the words do not parse,
    or they carry output-mode options (``-q``/``-v``/``-T``) or ``-H``,
    which a hand-off worker cannot honor.
    """
    parser = argparse.ArgumentParser(prog="sase tool")
    subparsers = parser.add_subparsers(dest="tool_subcommand")
    register_tool_parser(subparsers)
    with contextlib.redirect_stderr(io.StringIO()):
        try:
            args = parser.parse_args(["tool", "run", *[str(part) for part in words]])
        except SystemExit:
            return None
    if getattr(args, "tool_subcommand", None) != "run":
        return None
    if getattr(args, "quiet", False) or getattr(args, "verbose", False):
        return None
    if getattr(args, "tail_lines", None) is not None:
        return None
    if getattr(args, "hand_off", False):
        return None
    remainder = tuple(
        str(part) for part in (getattr(args, "tool_run_words", None) or ())
    )
    if not remainder:
        return None
    return remainder


@dataclass(frozen=True)
class _MonitorToolHandoff:
    """Outcome of attempting a monitor ToolRun reservation."""

    attempted: bool
    reservation: HandoffReservation | None = None


def maybe_reserve_monitor_tool_run(
    words: Sequence[str] | None,
    *,
    cwd: str | None,
    monitor_id: str,
    starter_agent: str | None = None,
) -> _MonitorToolHandoff:
    """Reserve a monitor-owned hand-off run for *words*, or decline.

    Returns ``attempted=False`` when there is nothing reservable (no words,
    output-mode options, or an unresolvable invocation): the caller keeps
    the E1.5 argv. Otherwise returns the shared reservation result, whose
    ``reserved`` flag tells the caller whether to adopt the worker argv or
    fall back with a reason line.

    *starter_agent* is the starter's durable (possibly just-promoted) name.
    It wins over the starter shell's ``SASE_AGENT_NAME``, which an
    agent-session promotion leaves stale, so the run is attributed exactly as an E1.5
    wrapped run is through ``SASE_TOOL_RUN_AGENT``.
    """
    if not words:
        return _MonitorToolHandoff(attempted=False)
    parsed = _parse_monitor_tool_words(words)
    if parsed is None:
        return _MonitorToolHandoff(attempted=False)
    try:
        resolved = resolve_run_argv(parsed, cwd=Path(cwd) if cwd else None)
    except ToolRunUsageError:
        return _MonitorToolHandoff(attempted=False)
    except Exception:  # noqa: BLE001 - resolution failure keeps E1.5 wrapping.
        return _MonitorToolHandoff(attempted=False)
    reservation = reserve_handoff_run(
        resolved, owner_kind="monitor", owner_id=monitor_id, agent=starter_agent
    )
    return _MonitorToolHandoff(attempted=True, reservation=reservation)


__all__ = [
    "RESERVATION_FALLBACK_LOG_PREFIX",
    "format_reservation_fallback_line",
    "maybe_reserve_monitor_tool_run",
]
