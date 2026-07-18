#!/usr/bin/env python3
"""Pending checks polling chop script."""

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop


@builtin_chop("pending_checks_poll")
def _run(runtime: BuiltinChopRuntime) -> None:
    runtime.hook_runner.run_pending_checks_poll(runtime.filtered_changespecs)


def main() -> None:
    run_builtin_chop("pending_checks_poll")


if __name__ == "__main__":
    main()
