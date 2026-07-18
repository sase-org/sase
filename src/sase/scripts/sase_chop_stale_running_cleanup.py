#!/usr/bin/env python3
"""Stale RUNNING entries cleanup chop script."""

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop


@builtin_chop("stale_running_cleanup")
def _run(runtime: BuiltinChopRuntime) -> None:
    runtime.hook_runner.run_stale_running_cleanup()


def main() -> None:
    run_builtin_chop("stale_running_cleanup")


if __name__ == "__main__":
    main()
