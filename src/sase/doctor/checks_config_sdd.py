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
        if error_count or storage_error_count
        else "WARN"
        if storage_issues
        else "OK"
    )
    summary = (
        _validation_passed_summary(len(validation.files), warning_count)
        if not error_count and not storage_issues
        else (
            "SDD validation/storage found "
            f"{error_count + storage_error_count} errors and "
            f"{warning_count + storage_warning_count} warnings"
        )
    )
    reported_validation_issues = [
        issue for issue in validation.issues if issue.severity == "error"
    ]
    details = (
        *(
            f"{issue.severity}: {issue.path}: {issue.message} ({issue.code})"
            for issue in reported_validation_issues[:MAX_DETAIL_ROWS]
        ),
        *(
            f"{issue.severity}: {issue.message} ({issue.code})"
            for issue in storage_issues[:MAX_DETAIL_ROWS]
        ),
    )[:MAX_DETAIL_ROWS]

    next_steps: tuple[str, ...] = ()
    if reported_validation_issues:
        next_steps += (f"Run `sase plan links validate -p {root} -W`.",)
    if storage_issues:
        next_steps += (
            "Run `sase repo init` after fixing provider access; remove any retired "
            "sdd.storage/sdd.version_controlled keys reported above.",
        )

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
        next_steps=(
            "Run `sase repo init` after fixing provider access; remove any retired "
            "sdd.storage/sdd.version_controlled keys reported above.",
        ),
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


def _validation_passed_summary(file_count: int, warning_count: int) -> str:
    if warning_count:
        return f"SDD validation passed: {file_count} files, {warning_count} warnings"
    return f"SDD validation passed: {file_count} files"


def _sdd_storage_issues(context: DoctorContext) -> list[_StorageIssue]:
    from sase.sdd._paths import get_primary_workspace_dir
    from sase.sdd.store import SddMaterializationError, read_sdd_store_record

    cwd = context.cwd.expanduser().resolve(strict=False)
    primary = Path(get_primary_workspace_dir(str(cwd), 1)).resolve(strict=False)
    from sase.content_layout import (
        LayoutCollisionError,
        resolve_project_config_read_path,
    )

    try:
        config_path = resolve_project_config_read_path(primary)
    except LayoutCollisionError as exc:
        return [_StorageIssue("error", "project-config-collision", str(exc))]
    config = _read_sdd_config(config_path) if config_path is not None else {}
    issues: list[_StorageIssue] = []

    for key in ("storage", "version_controlled"):
        if key in config:
            issues.append(
                _StorageIssue(
                    "warning",
                    f"retired-{key.replace('_', '-')}",
                    f"sdd.{key} is retired and ignored; remove it from sase.yml",
                )
            )

    policy = _provider_sdd_policy(primary)
    try:
        record = read_sdd_store_record(primary)
    except SddMaterializationError as exc:
        issues.append(
            _StorageIssue(
                "error",
                "incompatible-sdd-store-record",
                str(exc),
            )
        )
        return issues
    materialized_record = (
        record is not None
        and record.storage in {"separate_repo", "sidecar_repos"}
        and record.discovery != "not_found"
    )
    clone = primary / ".sase" / "sdd"

    if (
        record is None
        or record.discovery == "not_found"
        or record.storage == "separate_repo"
    ):
        regressed = _regressed_split_sidecar_paths(primary)
        if regressed is not None:
            plans, research = regressed
            issues.append(
                _StorageIssue(
                    "error",
                    "sdd-record-regressed",
                    "the SDD store record is missing or legacy while split sidecar "
                    f"clones exist ({plans}, {research}); the record may have been "
                    "clobbered by an older sase process. Run `sase repo init` to "
                    "restore sidecar routing",
                )
            )

    if policy == "separate_repo" and not materialized_record:
        issues.append(
            _StorageIssue(
                "error",
                "separate-repo-not-materialized",
                "the provider requires a sidecar SDD repository, but no positive "
                "materialized store record exists",
            )
        )
    if policy == "separate_repo" and not materialized_record:
        from sase.sdd._store_adoption import has_durable_artifacts

        legacy_paths = [
            path for path in (clone, primary / "sdd") if has_durable_artifacts(path)
        ]
        if legacy_paths:
            issues.append(
                _StorageIssue(
                    "warning",
                    "legacy-sdd-awaiting-import",
                    "legacy SDD artifacts will be imported during materialization: "
                    + ", ".join(str(path) for path in legacy_paths),
                )
            )
    if materialized_record and record is not None and record.is_sidecar_storage:
        from sase.sdd.store import resolve_sdd_store

        store = resolve_sdd_store(primary, 1)
        for kind in store.split_sidecar_roles():
            sidecar_clone = store.repo_root_for_kind(kind)
            remote_url = store.remote_url_for_kind(kind)
            if not (sidecar_clone / ".git").is_dir():
                issues.append(
                    _StorageIssue(
                        "error",
                        f"missing-{kind}-sidecar-clone",
                        f"sidecar SDD record exists but {kind} clone is missing: "
                        f"{sidecar_clone}",
                    )
                )
                continue
            issues.extend(_sidecar_git_issues(sidecar_clone, remote_url))
            issues.extend(_duplicate_remote_issues(context, primary, remote_url))

        if clone.exists():
            issues.append(
                _StorageIssue(
                    "warning",
                    "legacy-sdd-after-migration",
                    f"legacy SDD clone remains after sidecar migration: {clone}",
                )
            )
    elif materialized_record and not (clone / ".git").is_dir():
        issues.append(
            _StorageIssue(
                "error",
                "orphaned-store-record",
                f"SDD store record exists but clone is missing: {clone}",
            )
        )

    if (
        materialized_record
        and record is not None
        and not record.is_sidecar_storage
        and (clone / ".git").is_dir()
    ):
        assert record is not None
        issues.extend(_sidecar_git_issues(clone, record.remote_url))
        issues.extend(_duplicate_remote_issues(context, primary, record.remote_url))

    return issues


def _regressed_split_sidecar_paths(primary: Path) -> tuple[Path, Path] | None:
    """Return split clone paths when they contradict the effective record."""

    from sase.linked_repos import sidecar_repo_clone_dir

    plans = Path(sidecar_repo_clone_dir(primary, "plans"))
    research = Path(sidecar_repo_clone_dir(primary, "research"))
    beads = Path(sidecar_repo_clone_dir(primary, "beads"))
    if ((plans / "beads").is_dir() or beads.is_dir()) and research.is_dir():
        return plans, research
    return None


def _provider_sdd_policy(project_root: Path) -> str | None:
    try:
        from sase.vcs_provider import detect_vcs
        from sase.workspace_provider import get_sdd_storage_policy_by_vcs

        vcs_name = detect_vcs(str(project_root))
        if not vcs_name:
            return None
        policy = get_sdd_storage_policy_by_vcs(vcs_name)
    except Exception:
        return None
    return policy if policy in {"in_tree", "local", "separate_repo"} else None


def _read_sdd_config(config_path: Path) -> dict[str, object]:
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    sdd = raw.get("sdd", {})
    return sdd if isinstance(sdd, dict) else {}


def _sidecar_git_issues(
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
                "SDD sidecar clone has no origin remote",
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
                        "sidecar-diverged",
                        f"SDD sidecar repo is {ahead} ahead and {behind} behind upstream",
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
        remote_urls = _record_remote_urls(record)
        if (
            record is not None
            and record.discovery != "not_found"
            and remote_url in remote_urls
        ):
            matches.append(getattr(project, "project_name", str(workspace)))
    if not matches:
        return []
    return [
        _StorageIssue(
            "warning",
            "duplicate-sidecar-remote",
            "another project claims the same SDD sidecar remote: "
            + ", ".join(sorted(matches)),
        )
    ]


def _record_remote_urls(record: object) -> set[str]:
    if record is None:
        return set()
    urls = {
        value
        for value in (
            getattr(record, "remote_url", None),
            getattr(getattr(record, "plans", None), "remote_url", None),
            getattr(getattr(record, "research", None), "remote_url", None),
        )
        if isinstance(value, str) and value
    }
    return urls


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
    try:
        from sase.sdd.store import resolve_sdd_store

        store = resolve_sdd_store(cwd, 1)
        if store.is_sidecar_storage and store.repo_root.is_dir():
            return store.repo_root
    except Exception:
        pass
    candidate = resolve_sdd_root(None, cwd=cwd)
    if candidate.is_dir():
        return candidate
    return None
