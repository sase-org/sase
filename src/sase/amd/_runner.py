"""Command application for ``sase amd init``."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from ._planner import build_amd_init_plan, plan_amd_init_for_check
from ._shared import COMMAND_LABEL, apply_planned_delete


def _print_blockers(blockers: tuple[str, ...]) -> None:
    for blocker in blockers:
        print(f"{COMMAND_LABEL}: {blocker}", file=sys.stderr)


def run_amd_init(args: argparse.Namespace) -> int:
    """Apply ``sase amd init`` and return a process exit code."""
    if getattr(args, "check", False):
        from sase.main.init_onboarding import run_init_check
        from sase.main.init_registry import InitCommandSpec

        return run_init_check(
            args,
            specs=(
                InitCommandSpec(
                    name="amd",
                    label="AMD",
                    plan=plan_amd_init_for_check,
                    run=run_amd_init,
                ),
            ),
        )

    onboarding = bool(getattr(args, "onboarding", False))
    built = build_amd_init_plan(explicit=not onboarding, onboarding=onboarding)
    if built.plan.blockers:
        _print_blockers(built.plan.blockers)
        return 1

    written: list[Path] = []
    deleted: list[Path] = []
    for write in built.writes:
        write.path.parent.mkdir(parents=True, exist_ok=True)
        write.path.write_text(write.content, encoding="utf-8")
        written.append(write.path)
    for delete in built.deletes:
        did_delete, delete_error = apply_planned_delete(delete)
        if delete_error is not None:
            print(f"{COMMAND_LABEL}: {delete_error}", file=sys.stderr)
            return 1
        if did_delete:
            deleted.append(delete.path)

    if written or deleted:
        print(f"{COMMAND_LABEL}: initialized agent markdown documents")
        for path in written:
            print(f"  {path}")
        for path in deleted:
            print(f"  deleted {path}")
    else:
        print(f"{COMMAND_LABEL}: agent markdown documents are current")
    return 0
