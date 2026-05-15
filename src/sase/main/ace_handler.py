"""Handler for the 'sase ace' command."""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from sase.ace.query import QueryParseError
from sase.core.clipboard import copy_to_system_clipboard
from sase.core.paths import get_sase_tmpdir, shorten_path


def _profile_output_path(profile_arg: str) -> str:
    """Return the profile output path for an enabled ``--profile`` argument."""
    if profile_arg:
        output_path = os.path.expanduser(profile_arg)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        return output_path

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ace_profile_{timestamp}.txt"
    tmpdir = get_sase_tmpdir()
    return os.path.join(tmpdir, filename) if tmpdir else filename


def _write_profile_output(profiler: Any, profile_arg: str) -> str:
    """Write profiler output and report a short, clipboard-friendly path."""
    output_path = _profile_output_path(profile_arg)
    Path(output_path).write_text(
        profiler.output_text(unicode=True, color=False, show_all=True)
    )

    display_path = shorten_path(output_path)
    print(f"Profile written to: {display_path}", file=sys.stderr)
    if copy_to_system_clipboard(display_path):
        print("Profile path copied to clipboard.", file=sys.stderr)
    else:
        print(
            "Profile path not copied: clipboard command not available.",
            file=sys.stderr,
        )
    return output_path


def handle_ace_command(args: argparse.Namespace) -> None:
    """Handle the 'sase ace' command."""
    from sase.ace.tui import AceApp
    from sase.config.core import set_include_local_config

    # Don't load repo-level sase.yml for the TUI — local config should
    # only apply to agent runs (which are separate processes).
    set_include_local_config(False)

    # Wire --vcs-provider to env var for downstream resolution
    vcs_provider = getattr(args, "vcs_provider", None)
    if vcs_provider is not None:
        os.environ["SASE_VCS_PROVIDER"] = vcs_provider

    profiler = None
    if args.profile is not None:
        try:
            import pyinstrument
        except ImportError:
            print(
                "Error: pyinstrument is not installed. "
                "Install it with: pip install sase[dev]",
                file=sys.stderr,
            )
            sys.exit(1)

        profiler = pyinstrument.Profiler(async_mode="enabled")
        profiler.start()

    try:
        # Resolve model tier: prefer --model-tier, fall back to --model-size
        model_tier_override = getattr(args, "model_tier", None)
        if model_tier_override is None:
            old_size = getattr(args, "model_size", None)
            if old_size is not None:
                model_tier_override = {"big": "large", "little": "small"}[old_size]

        app = AceApp(
            query=args.query,
            model_tier_override=cast(
                Literal["large", "small"] | None, model_tier_override
            ),
            refresh_interval=args.refresh_interval,
            auto_start_axe=not getattr(args, "no_axe", False),
            restart_axe=getattr(args, "restart_axe", False),
            initial_tab=args.tab,
        )
    except QueryParseError as e:
        print(f"Error: Invalid query: {e}")
        sys.exit(1)

    if profiler is not None:
        app.run()
        profiler.stop()
        _write_profile_output(profiler, args.profile)
    else:
        app.run()

    sys.exit(0)
