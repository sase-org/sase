#!/usr/bin/env python3
"""PR submitted check cycle chop script."""

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop


@builtin_chop("pr_submitted_checks")
def _run(runtime: BuiltinChopRuntime) -> None:
    runtime.check_cycle_runner.run_full_check_cycle()


def main() -> None:
    run_builtin_chop("pr_submitted_checks")


if __name__ == "__main__":
    main()
