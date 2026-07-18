#!/usr/bin/env python3
"""Suffix transformation checks chop script."""

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop


@builtin_chop("suffix_transforms")
def _run(runtime: BuiltinChopRuntime) -> None:
    runtime.hook_runner.run_suffix_transforms(
        runtime.all_changespecs,
        runtime.filtered_changespecs,
    )


def main() -> None:
    run_builtin_chop("suffix_transforms")


if __name__ == "__main__":
    main()
