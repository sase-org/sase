"""Argument parser definition for the ``sase screenshot`` command."""

from __future__ import annotations

import argparse
from pathlib import Path

from sase.completion.kinds import ValueKind, set_completion_kind
from sase.screenshot.local import (
    DEFAULT_COLS,
    DEFAULT_ROWS,
    DEFAULT_SETTLE_MS,
    DEFAULT_TIMEOUT_SECONDS,
)


def _size(value: str) -> tuple[int, int]:
    raw_cols, sep, raw_rows = value.lower().partition("x")
    if not sep:
        raise argparse.ArgumentTypeError("must be formatted as COLSxROWS")
    try:
        cols = int(raw_cols)
        rows = int(raw_rows)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("columns and rows must be integers") from exc
    if cols <= 0 or rows <= 0:
        raise argparse.ArgumentTypeError("columns and rows must be positive")
    return cols, rows


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a non-negative integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive number") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive number")
    return parsed


def register_screenshot_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase screenshot`` command."""
    parser = subparsers.add_parser(
        "screenshot",
        help="Capture a PNG of a real live SASE TUI",
        description=(
            "Launch or reuse a real `sase tui` in tmux, drive it with keypresses, "
            "ask the live app to export SVG, and rasterize that SVG to PNG."
        ),
        epilog=(
            "Examples:\n"
            "  sase screenshot -o /tmp/shot.png\n"
            "  sase screenshot -p j -p j -w Ready -o /tmp/shot.png\n"
            "  sase screenshot --keep -- -t axe\n"
            "  sase screenshot --window sase_ace_agents:sase_tmux_1 -o /tmp/again.png"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--contract",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "-k",
        "--keep",
        action="store_true",
        help="Leave a newly launched tmux window running after capture",
    )
    output = parser.add_argument(
        "-o",
        "--output",
        metavar="PATH",
        type=Path,
        help="Output path (default: managed temporary screenshot path)",
    )
    set_completion_kind(output, ValueKind.PATH)
    parser.add_argument(
        "-p",
        "--press",
        action="append",
        default=[],
        metavar="KEY",
        help="Send one tmux key name before capture; repeat to send several",
    )
    parser.add_argument(
        "-d",
        "--settle-ms",
        type=_non_negative_int,
        default=DEFAULT_SETTLE_MS,
        metavar="MS",
        help=f"Extra settle delay before capture in milliseconds (default: {DEFAULT_SETTLE_MS})",
    )
    parser.add_argument(
        "-s",
        "--size",
        type=_size,
        default=(DEFAULT_COLS, DEFAULT_ROWS),
        metavar="COLSxROWS",
        help=f"Pane geometry for a new capture window (default: {DEFAULT_COLS}x{DEFAULT_ROWS})",
    )
    parser.add_argument(
        "-S",
        "--svg",
        action="store_true",
        help="Write SVG output and skip PNG rasterization",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=_positive_float,
        default=DEFAULT_TIMEOUT_SECONDS,
        metavar="SECONDS",
        help=f"Overall capture deadline in seconds (default: {DEFAULT_TIMEOUT_SECONDS:g})",
    )
    parser.add_argument(
        "-w",
        "--wait-for",
        action="append",
        default=[],
        metavar="REGEX",
        help="Wait for the tmux screen to match a regex before capture; repeatable",
    )
    parser.add_argument(
        "-W",
        "--window",
        metavar="TMUX_TARGET",
        help="Capture an existing tmux target instead of launching a new TUI",
    )
    parser.add_argument(
        "tui_args",
        nargs=argparse.REMAINDER,
        metavar="-- TUI_ARGS",
        help="Arguments forwarded to `sase tui` after a `--` separator",
    )


__all__ = ["register_screenshot_parser"]
