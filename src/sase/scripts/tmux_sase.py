"""Launch sase ace in a tmux window, send keys, and capture the screen.

Enables automated TUI testing from Claude Code by bridging the gap
between agent tooling and the interactive sase ace interface.
"""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
import time
from typing import NoReturn


def main(argv: list[str] | None = None) -> NoReturn:
    """Entry point for the tmux_sase script."""
    args = _parse_args(argv)
    _run(args)
    sys.exit(0)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tmux_sase",
        description="Launch sase ace in a tmux window, send keys, and capture output.",
    )
    parser.add_argument(
        "keys",
        nargs="*",
        metavar="KEY",
        help="Keys to send via tmux send-keys (tmux syntax: j, Enter, C-c, etc.)",
    )
    parser.add_argument(
        "--startup-delay",
        type=float,
        default=3.0,
        help="Seconds to wait for sase ace to render (default: 3.0)",
    )
    parser.add_argument(
        "--key-delay",
        type=float,
        default=0.1,
        help="Seconds between key presses (default: 0.1)",
    )
    parser.add_argument(
        "--capture-delay",
        type=float,
        default=0.5,
        help="Seconds after last key before capture (default: 0.5)",
    )
    parser.add_argument(
        "--ace-args",
        default="",
        help="Extra args for sase ace (shell-split string)",
    )
    parser.add_argument(
        "--window-name",
        default="tmux_sase",
        help='tmux window name (default: "tmux_sase")',
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Don't kill tmux window after capture",
    )
    parser.add_argument(
        "--no-capture",
        action="store_true",
        help="Send keys but skip capture",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Diagnostic output to stderr",
    )
    return parser.parse_args(argv)


def _log(args: argparse.Namespace, msg: str) -> None:
    if args.verbose:
        print(f"[tmux_sase] {msg}", file=sys.stderr)


def _run(args: argparse.Namespace) -> None:
    import os

    # Pre-flight checks
    if not os.environ.get("TMUX"):
        print("error: not running inside tmux (TMUX not set)", file=sys.stderr)
        sys.exit(1)

    for tool in ("tmux", "sase"):
        if not shutil.which(tool):
            print(f"error: {tool!r} not found on PATH", file=sys.stderr)
            sys.exit(1)

    target = args.window_name
    ace_extra = shlex.split(args.ace_args) if args.ace_args else []
    ace_cmd = " ".join(["sase", "ace", "--refresh-interval", "0", *ace_extra])

    # Create tmux window
    _log(args, f"creating window {target!r}: {ace_cmd}")
    try:
        subprocess.run(
            ["tmux", "new-window", "-n", target, "-d", ace_cmd],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"error: tmux new-window failed: {exc.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    try:
        # Wait for startup
        _wait_for_startup(args, target)

        # Send keys
        for key in args.keys:
            _log(args, f"send-keys: {key}")
            try:
                subprocess.run(
                    ["tmux", "send-keys", "-t", target, key],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                print(
                    f"error: send-keys {key!r} failed: {exc.stderr.strip()}",
                    file=sys.stderr,
                )
                sys.exit(1)
            time.sleep(args.key_delay)

        # Capture
        if not args.no_capture:
            time.sleep(args.capture_delay)
            output = _capture_pane(target)
            if output is not None:
                print(output, end="")
            else:
                print("warning: capture-pane failed", file=sys.stderr)
    except KeyboardInterrupt:
        _log(args, "interrupted")
        sys.exit(130)
    finally:
        if not args.keep:
            _log(args, f"killing window {target!r}")
            subprocess.run(
                ["tmux", "kill-window", "-t", target],
                capture_output=True,
            )


def _wait_for_startup(args: argparse.Namespace, target: str) -> None:
    """Sleep for startup_delay, then poll capture-pane for TUI content."""
    _log(args, f"waiting {args.startup_delay}s for startup")
    time.sleep(args.startup_delay)

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        output = _capture_pane(target)
        if output and output.strip():
            _log(args, "TUI content detected, ready")
            return
        _log(args, "no content yet, polling...")
        time.sleep(0.5)

    print("warning: startup timeout (10s), proceeding best-effort", file=sys.stderr)


def _capture_pane(target: str) -> str | None:
    """Capture the visible contents of a tmux pane."""
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", target, "-p"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


if __name__ == "__main__":
    main()
