"""Execute planned editable-install dev updates."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace

from sase.dev_update.code_swap_lock import code_swap_writer_lock
from sase.dev_update.command import (
    DEV_UPDATE_COMMAND_TIMEOUT_SECONDS as DEV_UPDATE_COMMAND_TIMEOUT_SECONDS,
    run_dev_update_command as run_dev_update_command,
)
from sase.dev_update.models import (
    DevCommandRunner,
    DevExecutedCommand,
    DevRustPrebuildResult,
    DevUpdatePlan,
    DevUpdateResult,
)
from sase.dev_update.outcomes import failed_result, skipped_outcomes, success_outcomes
from sase.dev_update.reconcile import run_reconcile_steps
from sase.dev_update.roots import (
    fetch_actionable_roots,
    merge_actionable_roots,
    preflight_actionable_roots,
)

__all__ = [
    "DEV_UPDATE_COMMAND_TIMEOUT_SECONDS",
    "execute_dev_update",
    "run_dev_update_command",
]


def execute_dev_update(
    plan: DevUpdatePlan,
    *,
    run: DevCommandRunner,
    clock: Callable[[], float] = time.monotonic,
) -> DevUpdateResult:
    """Execute ``plan`` with a fully injected subprocess runner."""
    start = clock()
    commands: list[DevExecutedCommand] = []
    rust_prebuild = DevRustPrebuildResult()

    def finish(result: DevUpdateResult) -> DevUpdateResult:
        return replace(result, duration_seconds=max(0.0, clock() - start))

    # Reconcile steps can exist without actionable checkouts (for example a
    # dev install restoring the editable sase-core-rs build over a published
    # wheel), so an empty root set alone does not make the plan a no-op.
    if not plan.actionable_roots and not plan.reconcile_steps:
        return finish(
            DevUpdateResult(
                changed=False,
                outcomes=skipped_outcomes(plan),
                commands=(),
                rust_prebuild=rust_prebuild,
            )
        )

    fetch_failure = fetch_actionable_roots(plan.actionable_roots, run, commands, clock)
    if fetch_failure is not None:
        return finish(
            failed_result(
                plan,
                fetch_failure,
                commands,
                changed=False,
                rust_prebuild=rust_prebuild,
            )
        )

    preflight_failure = preflight_actionable_roots(
        plan.actionable_roots, run, commands, clock
    )
    if preflight_failure is not None:
        return finish(
            failed_result(
                plan,
                preflight_failure,
                commands,
                changed=False,
                rust_prebuild=rust_prebuild,
            )
        )

    with code_swap_writer_lock() as lock:
        if not lock.acquired:
            return finish(
                failed_result(
                    plan,
                    _code_swap_deferred_reason(lock.blocked_by),
                    commands,
                    changed=False,
                    rust_prebuild=rust_prebuild,
                )
            )

        (
            merge_failure,
            merged_any,
            root_diffstats,
            root_commits,
        ) = merge_actionable_roots(plan.actionable_roots, run, commands, clock)
        if merge_failure is not None:
            return finish(
                failed_result(
                    plan,
                    merge_failure,
                    commands,
                    changed=merged_any,
                    rust_prebuild=rust_prebuild,
                )
            )

        reconcile_failure, rust_prebuild = run_reconcile_steps(
            plan.reconcile_steps, run, commands, clock
        )
        if reconcile_failure is not None:
            return finish(
                failed_result(
                    plan,
                    reconcile_failure,
                    commands,
                    changed=merged_any or bool(commands),
                    rust_prebuild=rust_prebuild,
                )
            )

        return finish(
            DevUpdateResult(
                changed=True,
                outcomes=success_outcomes(plan, root_diffstats, root_commits),
                commands=tuple(commands),
                rust_prebuild=rust_prebuild,
            )
        )


def _code_swap_deferred_reason(blocked_by: str | None) -> str:
    detail = blocked_by or "a running sase process"
    return (
        f"deferred: {detail} is running against this checkout; "
        "re-run `sase update` when it finishes"
    )
