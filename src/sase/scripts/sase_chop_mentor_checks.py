#!/usr/bin/env python3
"""Mentor completion and startup checks chop script."""

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop


@builtin_chop("mentor_checks")
def _run(runtime: BuiltinChopRuntime) -> None:
    runtime.hook_runner.run_mentor_checks(runtime.filtered_changespecs)


def main() -> None:
    run_builtin_chop("mentor_checks")


if __name__ == "__main__":
    main()
