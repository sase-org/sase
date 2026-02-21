#!/usr/bin/env python3
"""Orphaned workspace claims cleanup chop script."""

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
    all_cs = load_changespecs_from_file(ctx.all_changespecs_file)

    def log(message: str, style: str | None = None) -> None:
        print(message)

    runner = HookJobRunner(
        RunnerPool(ctx.max_runners),
        AxeMetrics(),
        ctx.zombie_timeout_seconds,
        ctx.max_runners,
        log,
    )
    runner.run_orphan_cleanup(all_cs)


if __name__ == "__main__":
    main()
