"""Handler for the ``sase screenshot`` command."""

from __future__ import annotations

import argparse
import json
import sys

from sase.screenshot.local import (
    SCREENSHOT_CONTRACT_SCHEMA_VERSION,
    ScreenshotCaptureError,
    ScreenshotOptions,
    capture_local_screenshot,
)


def handle_screenshot_command(args: argparse.Namespace) -> None:
    """Run the top-level screenshot command."""
    if getattr(args, "contract", False):
        print(json.dumps({"schema_version": SCREENSHOT_CONTRACT_SCHEMA_VERSION}))
        return

    options = ScreenshotOptions(
        output=args.output,
        size=args.size,
        presses=tuple(args.press or ()),
        wait_for=tuple(args.wait_for or ()),
        settle_ms=args.settle_ms,
        svg_only=args.svg,
        keep=args.keep,
        window=args.window,
        timeout=args.timeout,
        tui_args=tuple(args.tui_args or ()),
    )
    try:
        result = capture_local_screenshot(options)
    except ScreenshotCaptureError as exc:
        print(f"sase screenshot: {exc}", file=sys.stderr)
        sys.exit(2)

    if result.png is not None:
        print(f"png={result.png}")
    print(f"svg={result.svg}")
    print(f"sase_tmux_window={result.tmux_window}")
    print(f"sase_tmux_session={result.tmux_session}")
    print(f"sase_tmux_target={result.tmux_target}")
    print(f"sase_tmux_pid={result.tmux_pid}")
    print(f"sase_screenshot_dir={result.screenshot_dir}")


__all__ = ["handle_screenshot_command"]
