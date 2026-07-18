#!/usr/bin/env python3
"""Hook completion and startup checks chop script."""

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop


@builtin_chop("hook_checks")
def _run(runtime: BuiltinChopRuntime) -> None:
    runtime.hook_runner.run_hook_checks(runtime.filtered_changespecs)


def main() -> None:
    run_builtin_chop("hook_checks")


if __name__ == "__main__":
    main()
