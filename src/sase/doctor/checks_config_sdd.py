"""SDD validation checks for ``sase doctor``."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import yaml  # type: ignore[import-untyped]

from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.doctor.checks_config_common import MAX_DETAIL_ROWS
from sase.sdd.links import resolve_sdd_root, validate_sdd_tree

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


@dataclass(frozen=True)
class _StorageIssue:
    severity: str
    code: str
    message: str


def check_config_sdd(context: DoctorContext) -> DiagnosticCheck:
    """Validate SDD links when an SDD tree exists in this checkout."""
    root = _existing_sdd_root(context.cwd)
    storage_issues = _sdd_storage_issues(context)
    if root is None:
        if storage_issues:
            return _storage_only_check(storage_issues)
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
    storage_error_count = sum(
        1 for issue in storage_issues if issue.severity == "error"
    )
    storage_warning_count = sum(
        1 for issue in storage_issues if issue.severity == "warning"
    )
    status: CheckStatus = (
        "ERROR"
        if storage_error_count
        else "WARN"
        if validation.issues or storage_issues
        else "OK"
    )
    summary = (
        f"SDD validation passed: {len(validation.files)} files"
        if not validation.issues and not storage_issues
        else (
            "SDD validation/storage found "
            f"{error_count + storage_error_count} errors and "
            f"{warning_count + storage_warning_count} warnings"
        )
    )
    details = (
        *(
            f"{issue.severity}: {issue.path}: {issue.message} ({issue.code})"
            for issue in validation.issues[:MAX_DETAIL_ROWS]
        ),
        *(
            f"{issue.severity}: {issue.message} ({issue.code})"
            for issue in storage_issues[:MAX_DETAIL_ROWS]
        ),
    )[:MAX_DETAIL_ROWS]

    next_steps: tuple[str, ...] = ()
    if validation.issues:
        next_steps += (f"Run `sase sdd validate -p {root} -W`.",)
    if storage_issues:
        next_steps += ("Run `sase sdd migrate` or update sdd.storage in sase.yml.",)

    storage_issue_rows = [
        {
            "severity": issue.severity,
            "code": issue.code,
            "message": issue.message,
        }
        for issue in storage_issues
    ]

    return DiagnosticCheck(
        id="config.sdd",
        group="config",
        status=status,
        title="SDD validation",
        summary=summary,
        details=details,
        next_steps=next_steps,
        data={
            "sdd_root": str(validation.root),
            "file_count": len(validation.files),
            "error_count": error_count + storage_error_count,
            "warning_count": warning_count + storage_warning_count,
            "issues": issue_rows[:MAX_DETAIL_ROWS],
            "storage_issues": storage_issue_rows[:MAX_DETAIL_ROWS],
        },
    )


def _storage_only_check(storage_issues: list[_StorageIssue]) -> DiagnosticCheck:
    error_count = sum(1 for issue in storage_issues if issue.severity == "error")
    warning_count = sum(1 for issue in storage_issues if issue.severity == "warning")
    status: CheckStatus = "ERROR" if error_count else "WARN"
    return DiagnosticCheck(
        id="config.sdd",
        group="config",
        status=status,
        title="SDD validation",
        summary=(
            f"SDD storage found {error_count} errors and {warning_count} warnings"
        ),
        details=tuple(
            f"{issue.severity}: {issue.message} ({issue.code})"
            for issue in storage_issues[:MAX_DETAIL_ROWS]
        ),
        next_steps=("Run `sase sdd migrate` or update sdd.storage in sase.yml.",),
        data={
            "sdd_root": None,
            "storage_issues": [
                {
                    "severity": issue.severity,
                    "code": issue.code,
                    "message": issue.message,
                }
                for issue in storage_issues[:MAX_DETAIL_ROWS]
            ],
        },
    )


def _sdd_storage_issues(context: DoctorContext) -> list[_StorageIssue]:
    from sase.sdd._paths import get_primary_workspace_dir
    from sase.sdd.store import read_sdd_store_record

    cwd = context.cwd.expanduser().resolve(strict=False)
    primary = Path(get_primary_workspace_dir(str(cwd), 1)).resolve(strict=False)
    config = _read_sdd_config(primary / "sase.yml")
    issues: list[_StorageIssue] = []

    if "version_controlled" in config:
        issues.append(
            _StorageIssue(
                "warning",
                "deprecated-version-controlled",
                "sdd.version_controlled is deprecated; use sdd.storage instead",
            )
        )

    storage = config.get("storage")
    configured_storage = storage if isinstance(storage, str) else "auto"
    record = read_sdd_store_record(primary)
    materialized_record = (
        record is not None
        and record.storage == "separate_repo"
        and record.discovery != "not_found"
    )
    clone = primary / ".sase" / "sdd"

    if configured_storage == "separate_repo" and not materialized_record:
        issues.append(
            _StorageIssue(
                "error",
                "separate-repo-not-materialized",
                "sdd.storage is separate_repo but no materialized store record exists",
            )
        )
    if materialized_record and configured_storage in {"in_tree", "local"}:
        issues.append(
            _StorageIssue(
                "warning",
                "record-ignored-by-config",
                (
                    "a companion SDD record exists but explicit "
                    f"sdd.storage={configured_storage} ignores it"
                ),
            )
        )
    if materialized_record and not (clone / ".git").is_dir():
        issues.append(
            _StorageIssue(
                "error",
                "orphaned-store-record",
                f"SDD store record exists but clone is missing: {clone}",
            )
        )

    if materialized_record and (clone / ".git").is_dir():
        assert record is not None
        issues.extend(_companion_git_issues(clone, record.remote_url))
        issues.extend(_duplicate_remote_issues(context, primary, record.remote_url))

    return issues


def _read_sdd_config(config_path: Path) -> dict[str, object]:
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    sdd = raw.get("sdd", {})
    return sdd if isinstance(sdd, dict) else {}


def _companion_git_issues(
    clone: Path, record_remote_url: str | None
) -> list[_StorageIssue]:
    issues: list[_StorageIssue] = []
    origin = _git_stdout(clone, ["remote", "get-url", "origin"])
    if record_remote_url and origin and origin != record_remote_url:
        issues.append(
            _StorageIssue(
                "warning",
                "record-origin-mismatch",
                f"SDD record remote {record_remote_url} differs from git origin {origin}",
            )
        )
    elif record_remote_url and not origin:
        issues.append(
            _StorageIssue(
                "warning",
                "missing-origin",
                "SDD companion clone has no origin remote",
            )
        )

    divergence = _git_stdout(
        clone, ["rev-list", "--left-right", "--count", "@{upstream}...HEAD"]
    )
    if divergence:
        parts = divergence.split()
        if len(parts) == 2 and all(part.isdigit() for part in parts):
            behind, ahead = (int(parts[0]), int(parts[1]))
            if ahead or behind:
                issues.append(
                    _StorageIssue(
                        "warning",
                        "companion-diverged",
                        f"SDD companion repo is {ahead} ahead and {behind} behind upstream",
                    )
                )
    return issues


def _duplicate_remote_issues(
    context: DoctorContext, primary: Path, remote_url: str | None
) -> list[_StorageIssue]:
    if not remote_url:
        return []
    try:
        from sase.doctor.checks_project import resolve_current_project_record
        from sase.sdd.store import read_sdd_store_record

        records = resolve_current_project_record(context).records
    except Exception:
        return []

    matches: list[str] = []
    for project in records:
        workspace_dir = getattr(project, "workspace_dir", "")
        if not workspace_dir:
            continue
        workspace = Path(workspace_dir).expanduser().resolve(strict=False)
        if workspace == primary:
            continue
        record = read_sdd_store_record(workspace)
        if (
            record is not None
            and record.discovery != "not_found"
            and record.remote_url == remote_url
        ):
            matches.append(getattr(project, "project_name", str(workspace)))
    if not matches:
        return []
    return [
        _StorageIssue(
            "warning",
            "duplicate-companion-remote",
            "another project claims the same SDD companion remote: "
            + ", ".join(sorted(matches)),
        )
    ]


def _git_stdout(cwd: Path, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _existing_sdd_root(cwd: Path) -> Path | None:
    for candidate in (cwd / "sdd", cwd / ".sase" / "sdd"):
        if candidate.is_dir():
            return resolve_sdd_root(str(candidate), cwd=cwd)
    return None
