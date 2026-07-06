"""SDD validation checks for ``sase doctor``."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.doctor.checks_config_common import MAX_DETAIL_ROWS
from sase.sdd.links import resolve_sdd_root, validate_sdd_tree

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


def check_config_sdd(context: DoctorContext) -> DiagnosticCheck:
    """Validate SDD links when an SDD tree exists in this checkout."""
    root = _existing_sdd_root(context.cwd)
    if root is None:
        return DiagnosticCheck(
            id="config.sdd",
            group="config",
            status="SKIP",
            title="SDD validation",
            summary="no SDD tree found in this checkout",
            data={"sdd_root": None},
        )

    validation = validate_sdd_tree(str(root), strict=False)
    issue_rows = [
        {
            "severity": issue.severity,
            "code": issue.code,
            "path": issue.path,
            "message": issue.message,
        }
        for issue in validation.issues
    ]
    error_count = sum(1 for issue in validation.issues if issue.severity == "error")
    warning_count = sum(1 for issue in validation.issues if issue.severity == "warning")
    status: CheckStatus = "WARN" if validation.issues else "OK"
    summary = (
        f"SDD validation passed: {len(validation.files)} files"
        if not validation.issues
        else f"SDD validation found {error_count} errors and {warning_count} warnings"
    )
    details = tuple(
        f"{issue.severity}: {issue.path}: {issue.message} ({issue.code})"
        for issue in validation.issues[:MAX_DETAIL_ROWS]
    )

    return DiagnosticCheck(
        id="config.sdd",
        group="config",
        status=status,
        title="SDD validation",
        summary=summary,
        details=details,
        next_steps=(f"Run `sase sdd validate -p {root} -W`.",)
        if validation.issues
        else (),
        data={
            "sdd_root": str(validation.root),
            "file_count": len(validation.files),
            "error_count": error_count,
            "warning_count": warning_count,
            "issues": issue_rows[:MAX_DETAIL_ROWS],
        },
    )


def _existing_sdd_root(cwd: Path) -> Path | None:
    for candidate in (cwd / "sdd", cwd / ".sase" / "sdd"):
        if candidate.is_dir():
            return resolve_sdd_root(str(candidate), cwd=cwd)
    return None
