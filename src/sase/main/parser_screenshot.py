"""Argument parser definition for the ``sase screenshot`` command."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from sase.completion.kinds import ValueKind, set_completion_kind
from sase.screenshot.local import (
    DEFAULT_COLS,
    DEFAULT_ROWS,
    DEFAULT_SETTLE_MS,
    DEFAULT_TIMEOUT_SECONDS,
    ScreenshotScriptKind,
    ScreenshotScriptStep,
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


class _AppendScreenshotScriptAction(argparse._AppendAction):
    """Append one press, type, or wait step, preserving argv order."""

    def __init__(
        self,
        option_strings: list[str],
        dest: str,
        **kwargs: Any,
    ) -> None:
        self.kind = cast(ScreenshotScriptKind, kwargs.pop("kind"))
        super().__init__(option_strings, dest, **kwargs)

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        del parser, option_string
        items = list(getattr(namespace, self.dest, None) or ())
        items.append(ScreenshotScriptStep(self.kind, str(values)))
        setattr(namespace, self.dest, items)


def register_screenshot_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase screenshot`` command."""
    parser = subparsers.add_parser(
        "screenshot",
        help="Capture a PNG of a real live SASE TUI",
        description=(
            "Launch or reuse a real `sase tui` in tmux, drive it with keypresses "
            "and typed text, ask the live app to export SVG, and rasterize that "
            "SVG to PNG. Repeatable -p/--press, -T/--type, and -w/--wait-for "
            "form one argv-ordered input script."
        ),
        epilog=(
            "Examples:\n"
            "  sase screenshot -o /tmp/shot.png\n"
            "  sase screenshot -p j -p j -w Ready -o /tmp/shot.png\n"
            "  sase screenshot -p / -w INSERT --type machine:apollo "
            "-w machine:apollo -p enter -o /tmp/shot.png\n"
            "  sase screenshot --host apollo -o /tmp/remote.png\n"
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
        "-H",
        "--host",
        metavar="ALIAS_OR_SSH",
        help="Run the SVG capture on an enrolled machine alias or raw SSH destination",
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
        action=_AppendScreenshotScriptAction,
        dest="script",
        kind="press",
        default=[],
        metavar="KEY",
        help=(
            "Send one tmux key name; repeats interleave with --type and -w in argv order"
        ),
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
        "-T",
        "--type",
        action=_AppendScreenshotScriptAction,
        dest="script",
        kind="type",
        default=[],
        metavar="TEXT",
        help=(
            "Send literal TUI text (tmux send-keys -l); repeats interleave with "
            "-p and -w in argv order"
        ),
    )
    parser.add_argument(
        "-w",
        "--wait-for",
        action=_AppendScreenshotScriptAction,
        dest="script",
        kind="wait",
        default=[],
        metavar="REGEX",
        help=(
            "Wait for tmux screen text to match a regex; repeats interleave with "
            "-p and --type in argv order"
        ),
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
