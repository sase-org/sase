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
    workspace = Path.cwd() if cwd is None else cwd

    from sase.sdd._link_files import (
        nested_repo_open_checkout_root,
        nested_repo_open_plans_root,
        nested_repo_open_sdd_root,
    )

    nested_checkout = nested_repo_open_checkout_root(workspace)
    if nested_checkout is not None:
        nested_sdd_root = nested_repo_open_sdd_root(workspace)
        if nested_sdd_root is not None:
            nested_plans_root = nested_repo_open_plans_root(workspace)
            if nested_plans_root is not None:
                return nested_plans_root.resolve()

        from sase.linked_repos import sidecar_repo_clone_dir

        return Path(sidecar_repo_clone_dir(nested_checkout, "plans")).resolve()

    configured = os.environ.get("SASE_SDD_PLANS_DIR")
    if configured:
        return Path(configured).expanduser().resolve()

    from sase.sdd.store import resolve_sdd_kind_dir

    return resolve_sdd_kind_dir(workspace, 1, "plans").resolve()


def _missing_plans_root_issue(
    plans_root: Path,
    *,
    cwd: Path | None = None,
) -> CommittedPlanIssue:
    """Describe a missing plans root and explain how nested clones are provisioned."""
    from sase.sdd._link_files import nested_repo_open_plans_remedy

    message = "plans root does not exist or is not a directory"
    remedy = nested_repo_open_plans_remedy(cwd)
    if remedy is not None:
        message = f"{message}. {remedy}"
    return CommittedPlanIssue(
        path=str(plans_root),
        severity="error",
        code="invalid-plans-root",
        message=message,
    )


def _sweep_committed_plans(
    plans_root: Path,
    *,
    cwd: Path | None = None,
) -> _CommittedPlanSweep:
    """Validate every direct ``YYYYMM/*.md`` plan under ``plans_root``."""
    root = plans_root.expanduser().resolve()
    workspace = Path.cwd() if cwd is None else cwd
    from sase.sdd._link_files import (
        nested_repo_open_checkout_root,
        nested_repo_open_plans_root,
    )

    nested_checkout = nested_repo_open_checkout_root(workspace)
    nested_plans_root = nested_repo_open_plans_root(workspace)
    if (nested_checkout is not None and nested_plans_root is None) or not root.is_dir():
        return _CommittedPlanSweep(
            plans_root=root,
            checked_files=0,
            strict_files=0,
            legacy_files=0,
            issues=(_missing_plans_root_issue(root, cwd=workspace),),
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
    workspace = Path.cwd()
    sweep = _sweep_committed_plans(
        _resolve_committed_plans_root(),
        cwd=workspace,
    )
    _render_committed_plan_sweep(sweep)
    return 0 if sweep.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
