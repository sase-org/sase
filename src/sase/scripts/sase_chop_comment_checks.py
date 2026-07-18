#!/usr/bin/env python3
"""Comment check cycle chop script."""

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop


@builtin_chop("comment_checks")
def _run(runtime: BuiltinChopRuntime) -> None:
    runtime.check_cycle_runner.run_comment_check_cycle()


def main() -> None:
    run_builtin_chop("comment_checks")


if __name__ == "__main__":
    main()
