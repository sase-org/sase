#!/usr/bin/env python3
"""Hook completion and startup checks chop script."""

import argparse

from sase.axe.chop_script_context import (
    load_changespecs_from_file,
    read_chop_context,
)
from sase.axe.hook_jobs import HookJobRunner
from sase.axe.runner_pool import RunnerPool
from sase.axe.state import AxeMetrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    args = parser.parse_args()

    ctx = read_chop_context(args.context)
    filtered = load_changespecs_from_file(ctx.filtered_changespecs_file)

    def log(message: str, style: str | None = None) -> None:
        print(message)

    runner = HookJobRunner(
        RunnerPool(ctx.max_runners),
        AxeMetrics(),
        ctx.zombie_timeout_seconds,
        ctx.max_runners,
        log,
    )
    runner.run_hook_checks(filtered)


if __name__ == "__main__":
    main()
