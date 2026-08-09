"""Build package outcomes for executed dev updates."""

from __future__ import annotations

from sase.dev_update.models import (
    DevExecutedCommand,
    DevRustPrebuildResult,
    DevUpdateOutcome,
    DevUpdatePackagePlan,
    DevUpdatePlan,
    DevUpdateResult,
    RepoCommitLog,
    RepoDiffStat,
)


def success_outcomes(
    plan: DevUpdatePlan,
    root_diffstats: dict[str, RepoDiffStat | None],
    root_commits: dict[str, RepoCommitLog | None],
) -> tuple[DevUpdateOutcome, ...]:
    """Return updated and skipped outcomes for a successful execution."""
    outcomes = [
        DevUpdateOutcome(
            record=pkg.record,
            status="updated",
            reason=pkg.reason,
            old_version=pkg.current_version,
            new_version=pkg.latest_version,
            git_root=pkg.git_root,
            diffstat=root_diffstats.get(pkg.git_root) if pkg.git_root else None,
            commits=root_commits.get(pkg.git_root) if pkg.git_root else None,
        )
        for pkg in plan.actionable
    ]
    outcomes.extend(skipped_outcomes(plan))
    return tuple(outcomes)


def skipped_outcomes(plan: DevUpdatePlan) -> tuple[DevUpdateOutcome, ...]:
    """Return outcomes for packages skipped by the plan."""
    return tuple(_skipped_outcome(pkg) for pkg in plan.skipped)


def failed_result(
    plan: DevUpdatePlan,
    reason: str,
    commands: list[DevExecutedCommand],
    *,
    changed: bool,
    rust_prebuild: DevRustPrebuildResult | None = None,
) -> DevUpdateResult:
    """Build a failed execution result while retaining skipped outcomes."""
    rust_prebuild = rust_prebuild or DevRustPrebuildResult()
    outcomes = [
        DevUpdateOutcome(
            record=pkg.record,
            status="failed",
            reason=reason,
            old_version=pkg.current_version,
            new_version=pkg.latest_version,
            git_root=pkg.git_root,
        )
        for pkg in plan.actionable
    ]
    outcomes.extend(skipped_outcomes(plan))
    return DevUpdateResult(
        changed=changed,
        outcomes=tuple(outcomes),
        commands=tuple(commands),
        rust_prebuild=rust_prebuild,
    )


def _skipped_outcome(pkg: DevUpdatePackagePlan) -> DevUpdateOutcome:
    return DevUpdateOutcome(
        record=pkg.record,
        status="skipped",
        reason=pkg.reason,
        old_version=pkg.current_version,
        new_version=pkg.latest_version,
        git_root=pkg.git_root,
    )
