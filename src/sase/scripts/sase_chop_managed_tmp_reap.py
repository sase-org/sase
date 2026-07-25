#!/usr/bin/env python3
"""Managed SASE temp root reaping chop script.

Runs on the hourly ``housekeeping`` lumberjack rather than on an interactive
path: the first pass over a long-neglected root walks tens of thousands of
entries, which must never sit in front of a TUI startup or a CLI command.
"""

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.core.managed_tmp_reaper import reap_managed_tmpdir


@builtin_chop("managed_tmp_reap")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    result = reap_managed_tmpdir()
    if result.removed:
        runtime.log(result.describe(), "cyan")
    return runtime.emit_summary(
        {
            "scanned": result.scanned,
            "removed": result.removed,
            "subdirs": len(result.removed_by_subdir),
            "deindexed": result.deindexed,
            "capped": int(result.capped),
        },
        reason="nothing_stale" if not result.removed else None,
    )


def main() -> None:
    run_builtin_chop("managed_tmp_reap")


if __name__ == "__main__":
    main()
