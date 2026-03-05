#!/usr/bin/env python3
"""Stale RUNNING entries cleanup chop script."""

import argparse

from sase.axe.chop_script_context import read_chop_context
from sase.axe.hook_jobs import HookJobRunner
from sase.axe.state import AxeMetrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    args = parser.parse_args()

    ctx = read_chop_context(args.context)

    def log(message: str, style: str | None = None) -> None:
        print(message)

    runner = HookJobRunner(
        AxeMetrics(),
        ctx.zombie_timeout_seconds,
        ctx.max_hook_runners,
        ctx.max_agent_runners,
        log,
    )
    runner.run_stale_running_cleanup()


if __name__ == "__main__":
    main()
