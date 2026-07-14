"""Sweep the committed plans store with cutover-aware schema validation."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import sys
from typing import TextIO

from sase.sdd.committed_plan_validation import (
    CommittedPlanIssue,
    inspect_committed_plan,
    requires_full_plan_schema,
)
from sase.sdd.plan_tiers import read_plan_tier_from_content

_YYYYMM_RE = re.compile(r"^\d{6}$")


@dataclass(frozen=True)
class _CommittedPlanSweep:
    """Aggregate result for one committed plans root."""

    plans_root: Path
    checked_files: int
    strict_files: int
    legacy_files: int
    issues: tuple[CommittedPlanIssue, ...]

    @property
    def ok(self) -> bool:
        """Return whether the sweep found no blocking errors."""
        return not any(issue.is_error for issue in self.issues)


def _resolve_committed_plans_root(*, cwd: Path | None = None) -> Path:
    """Resolve the plans root from agent env or provider-owned SDD state."""
    configured = os.environ.get("SASE_SDD_PLANS_DIR")
    if configured:
        return Path(configured).expanduser().resolve()

    from sase.sdd.store import resolve_sdd_kind_dir

    workspace = Path.cwd() if cwd is None else cwd
    return resolve_sdd_kind_dir(workspace, 1, "plans").resolve()


def _sweep_committed_plans(plans_root: Path) -> _CommittedPlanSweep:
    """Validate every direct ``YYYYMM/*.md`` plan under ``plans_root``."""
    root = plans_root.expanduser().resolve()
    if not root.is_dir():
        return _CommittedPlanSweep(
            plans_root=root,
            checked_files=0,
            strict_files=0,
            legacy_files=0,
            issues=(
                CommittedPlanIssue(
                    path=str(root),
                    severity="error",
                    code="invalid-plans-root",
                    message="plans root does not exist or is not a directory",
                ),
            ),
        )

    checked_files = 0
    strict_files = 0
    legacy_files = 0
    issues: list[CommittedPlanIssue] = []
    for month_dir in sorted(root.iterdir(), key=lambda path: path.name):
        yyyymm = month_dir.name
        if not month_dir.is_dir() or _YYYYMM_RE.fullmatch(yyyymm) is None:
            continue
        strict = requires_full_plan_schema(yyyymm)
        for plan_path in sorted(month_dir.glob("*.md"), key=lambda path: path.name):
            checked_files += 1
            if strict:
                strict_files += 1
            else:
                legacy_files += 1
            relative_path = plan_path.relative_to(root).as_posix()
            try:
                content = plan_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                issues.append(
                    CommittedPlanIssue(
                        path=relative_path,
                        severity="error",
                        code="read-error",
                        message=str(exc),
                    )
                )
                continue
            issues.extend(
                inspect_committed_plan(
                    content,
                    tier=read_plan_tier_from_content(content),
                    path=relative_path,
                    yyyymm=yyyymm,
                )
            )

    return _CommittedPlanSweep(
        plans_root=root,
        checked_files=checked_files,
        strict_files=strict_files,
        legacy_files=legacy_files,
        issues=tuple(issues),
    )


def _render_committed_plan_sweep(
    sweep: _CommittedPlanSweep,
    *,
    stream: TextIO | None = None,
) -> None:
    """Print aggregate diagnostics and a compact summary."""
    output = sys.stdout if stream is None else stream
    for issue in sweep.issues:
        print(issue.format(), file=output)

    error_count = sum(issue.is_error for issue in sweep.issues)
    warning_count = len(sweep.issues) - error_count
    status = "passed" if sweep.ok else "failed"
    print(
        f"Committed plan validation {status}: {sweep.checked_files} files "
        f"({sweep.strict_files} strict, {sweep.legacy_files} legacy), "
        f"{error_count} errors, {warning_count} warnings.",
        file=output,
    )


def main() -> int:
    """Run the committed-plan sweep against the resolved plans root."""
    sweep = _sweep_committed_plans(_resolve_committed_plans_root())
    _render_committed_plan_sweep(sweep)
    return 0 if sweep.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
