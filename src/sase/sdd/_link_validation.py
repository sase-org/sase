"""Validation and display helpers for linked SDD artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.sdd._link_files import list_sdd_files, resolve_sdd_root
from sase.sdd._link_models import SddIssue, SddValidation
from sase.sdd._link_parent import LocalPlanChanges, parent_section_issue
from sase.sdd._legacy_prompt_files import list_plans_store_prompt_files
from sase.sdd._link_support import (
    PLAN_KINDS,
    expected_link_type,
    link_reference,
    mixed_link_agrees,
    resolve_link_path,
)
from sase.sdd.artifact_links import SddArtifactLinkKind
from sase.sdd.plan_header_block import (
    PlanHeaderDisposition,
    parse_plan_header_block,
)
from sase.sdd.plan_tiers import normalize_plan_tier


def validate_sdd_tree(
    path: str | None = None,
    *,
    legacy_error_allowlist: frozenset[str] = frozenset(),
) -> SddValidation:
    """Validate artifact metadata and a plan's own PROMPT bullet."""
    root = resolve_sdd_root(path)
    if not root.is_dir():
        issue = SddIssue(
            severity="error",
            code="invalid-root",
            path=str(root),
            message=f"SDD path does not exist or is not a directory: {root}",
        )
        return SddValidation(root=root, files=[], issues=[issue])

    files = list_sdd_files(root, kind="all")
    issues: list[SddIssue] = []
    local_changes = LocalPlanChanges(root)

    for prompt_path, _month in list_plans_store_prompt_files(root):
        issues.append(
            SddIssue(
                severity="error",
                code="prompt-in-plans-store",
                path=prompt_path.relative_to(root).as_posix(),
                message=(
                    "prompt Markdown remains in the plans store; migrate it "
                    "to the canonical agents-sidecar archive"
                ),
            )
        )

    for file in files:
        if file.parse_error is not None:
            issues.append(
                SddIssue(
                    severity="error",
                    code="frontmatter-parse",
                    path=file.relpath,
                    message=file.parse_error,
                )
            )
            continue

        if (
            file.kind in PLAN_KINDS
            and normalize_plan_tier(file.frontmatter.get("tier")) is None
        ):
            issues.append(
                SddIssue(
                    severity="error",
                    code="plan-tier",
                    path=file.relpath,
                    message="'tier' must be either 'tale' or 'epic'",
                )
            )

        if file.kind in PLAN_KINDS:
            header = parse_plan_header_block(file.path.read_text(encoding="utf-8"))
            if header.disposition is PlanHeaderDisposition.INVALID:
                issues.append(
                    SddIssue(
                        severity="error",
                        code="header-invalid",
                        path=file.relpath,
                        message=header.reason or "plan header block is malformed",
                    )
                )
            else:
                parent_issue = parent_section_issue(
                    root, file, header.sections, local_changes
                )
                if parent_issue is not None:
                    issues.append(parent_issue)

        link_type = expected_link_type(file)
        link_field = link_type.legacy_field
        link = file.artifact_link

        if link.kind is SddArtifactLinkKind.MISSING:
            continue
        if link.kind is SddArtifactLinkKind.INVALID:
            issues.append(
                SddIssue(
                    severity="error",
                    code="link-format",
                    path=file.relpath,
                    message=f"invalid {link_field!r} artifact link: {link.reason}",
                )
            )
            continue
        if link.link_type is not link_type:
            issues.append(
                SddIssue(
                    severity="error",
                    code="link-kind",
                    path=file.relpath,
                    message=(
                        f"artifact uses {link.link_type or 'unknown'} link; "
                        f"expected {link_type.value}"
                    ),
                )
            )
            continue
        if (
            link.kind in {SddArtifactLinkKind.CANONICAL, SddArtifactLinkKind.MIXED}
            and not link.canonical_layout
        ):
            issues.append(
                SddIssue(
                    severity="error",
                    code="link-placement",
                    path=file.relpath,
                    message=(
                        f"{link_type.value} bullet must be the first Markdown body "
                        "element with exactly one blank line after it"
                    ),
                )
            )
        if link.kind is SddArtifactLinkKind.MIXED and not mixed_link_agrees(
            root, file.path, link
        ):
            issues.append(
                SddIssue(
                    severity="error",
                    code="link-conflict",
                    path=file.relpath,
                    message=(
                        "canonical bullet and legacy frontmatter link resolve to "
                        "different targets"
                    ),
                )
            )

    return SddValidation(
        root=root,
        files=files,
        issues=_apply_legacy_error_allowlist(issues, legacy_error_allowlist),
    )


def collect_sdd_links(root: Path) -> list[dict[str, Any]]:
    """Return link rows suitable for text or JSON display."""
    files = list_sdd_files(root, kind="all")
    by_path = {file.path.resolve(): file for file in files}
    rows: list[dict[str, Any]] = []
    for file in files:
        link_type = expected_link_type(file)
        link = file.artifact_link
        row: dict[str, Any] = {
            "path": file.relpath,
            "kind": file.kind,
            "field": link_type.legacy_field,
            "target": link_reference(root, file.path, link),
            "target_exists": False,
            "bidirectional": False,
        }
        if link.link_type is link_type:
            resolved = resolve_link_path(root, file.path, link)
            target = by_path.get(resolved.resolve()) if resolved is not None else None
            row["target_exists"] = target is not None
            if target is not None:
                reverse_type = expected_link_type(target)
                reverse_link = target.artifact_link
                reverse_path = resolve_link_path(root, target.path, reverse_link)
                row["bidirectional"] = (
                    reverse_link.link_type is reverse_type
                    and reverse_path is not None
                    and reverse_path.resolve() == file.path.resolve()
                )
        rows.append(row)
    return rows


def _apply_legacy_error_allowlist(
    issues: list[SddIssue], allowlist: frozenset[str]
) -> list[SddIssue]:
    if not allowlist:
        return issues
    return [
        SddIssue(
            severity="warning",
            code=f"{issue.code}-legacy-allowed",
            path=issue.path,
            message=f"{issue.message}; legacy SDD validation error allowlisted",
        )
        if issue.severity == "error" and issue.path in allowlist
        else issue
        for issue in issues
    ]
