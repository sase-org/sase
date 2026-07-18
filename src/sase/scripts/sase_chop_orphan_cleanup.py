#!/usr/bin/env python3
"""Orphaned workspace claims cleanup chop script."""

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop


@builtin_chop("orphan_cleanup")
def _run(runtime: BuiltinChopRuntime) -> None:
    runtime.hook_runner.run_orphan_cleanup(runtime.all_changespecs)


def main() -> None:
    run_builtin_chop("orphan_cleanup")


if __name__ == "__main__":
    main()
