"""Handler for the 'sase ace' command."""

import argparse
import os
import sys
from datetime import datetime
from typing import Literal, cast

from sase.ace.query import QueryParseError


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
        )
    except QueryParseError as e:
        print(f"Error: Invalid query: {e}")
        sys.exit(1)

    if getattr(args, "profile", False):
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
        app.run()
        profiler.stop()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"ace_profile_{timestamp}.txt"
        with open(output_path, "w") as f:
            f.write(profiler.output_text(unicode=True, color=False))
        print(f"Profile written to: {output_path}", file=sys.stderr)
    else:
        app.run()

    sys.exit(0)
