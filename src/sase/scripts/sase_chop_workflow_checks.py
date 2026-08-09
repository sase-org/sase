#!/usr/bin/env python3
"""CRS/fix-hook workflow checks chop script."""

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop


@builtin_chop("workflow_checks")
def _run(runtime: BuiltinChopRuntime) -> None:
    runtime.hook_runner.run_workflow_checks(runtime.filtered_patches)


def main() -> None:
    run_builtin_chop("workflow_checks")


if __name__ == "__main__":
    main()
