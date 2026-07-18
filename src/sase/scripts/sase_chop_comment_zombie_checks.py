#!/usr/bin/env python3
"""Comment zombie detection chop script."""

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop


@builtin_chop("comment_zombie_checks")
def _run(runtime: BuiltinChopRuntime) -> None:
    runtime.hook_runner.run_comment_zombie_checks(runtime.filtered_changespecs)


def main() -> None:
    run_builtin_chop("comment_zombie_checks")


if __name__ == "__main__":
    main()
