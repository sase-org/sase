"""Validation and display helpers for linked SDD artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.sdd._link_files import list_sdd_files, resolve_sdd_root
from sase.sdd._link_models import Severity, SddFile, SddIssue, SddValidation
from sase.sdd._link_support import (
    PLAN_KINDS,
    expected_link_type,
    infer_counterpart,
    link_reference,
    mixed_link_agrees,
    resolve_link_path,
)
from sase.sdd.artifact_links import SddArtifactLinkKind
from sase.sdd.plan_header_block import (
    PlanHeaderDisposition,
    PlanHeaderSection,
    PlanHeaderSectionKind,
    parse_plan_header_block,
)
from sase.sdd.plan_tiers import normalize_plan_tier


def validate_sdd_tree(
    path: str | None = None,
    *,
    strict: bool = False,
    legacy_error_allowlist: frozenset[str] = frozenset(),
) -> SddValidation:
    """Validate artifact metadata and bidirectional links under an SDD root."""
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
    by_path = {file.path.resolve(): file for file in files}
    issues: list[SddIssue] = []

    for file in files:
        if file.kind == "prompts":
            issues.append(
                SddIssue(
                    severity="warning",
                    code="prompt-in-plans-store",
                    path=file.relpath,
                    message=(
                        "prompt Markdown remains in the plans store; migrate it "
                        "to the canonical agents-sidecar archive"
                    ),
                )
            )
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
            if header.disposition is not PlanHeaderDisposition.INVALID:
                _validate_parent_section(root, file, header.sections, issues)

        link_type = expected_link_type(file)
        link_field = link_type.legacy_field
        link = file.artifact_link
        counterpart = infer_counterpart(file, files)
        if len(counterpart) == 1 and link.kind is SddArtifactLinkKind.MISSING:
            issues.append(
                SddIssue(
                    severity="error",
                    code="missing-link",
                    path=file.relpath,
                    message=f"missing {link_field!r} link to {counterpart[0].relpath}",
                )
            )
        elif len(counterpart) > 1:
            issues.append(
                SddIssue(
                    severity=_strict_severity(strict),
                    code="ambiguous-counterpart",
                    path=file.relpath,
                    message="multiple inferable counterpart files: "
                    + ", ".join(item.relpath for item in counterpart),
                )
            )
        elif not counterpart and link.kind is SddArtifactLinkKind.MISSING:
            issues.append(
                SddIssue(
                    severity=_strict_severity(strict),
                    code="unpaired-file",
                    path=file.relpath,
                    message="no inferable counterpart file",
                )
            )

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
            continue

        target_path = resolve_link_path(root, file.path, link)
        if target_path is None:
            continue
        target = by_path.get(target_path.resolve())
        if target is None:
            issues.append(
                SddIssue(
                    severity="error",
                    code="link-missing-target",
                    path=file.relpath,
                    message=f"{link_field!r} target does not exist: "
                    f"{link.resolution_target}",
                )
            )
            continue

        if file.kind == "prompts" and target.kind not in PLAN_KINDS:
            issues.append(
                SddIssue(
                    severity="error",
                    code="link-kind",
                    path=file.relpath,
                    message=f"{link_field!r} target is not a plan file: {target.relpath}",
                )
            )
        elif file.kind in PLAN_KINDS and target.kind != "prompts":
            issues.append(
                SddIssue(
                    severity="error",
                    code="link-kind",
                    path=file.relpath,
                    message=f"{link_field!r} target is not a prompt file: {target.relpath}",
                )
            )

        reverse_type = expected_link_type(target)
        reverse_field = reverse_type.legacy_field
        reverse_link = target.artifact_link
        if (
            reverse_link.kind
            in {SddArtifactLinkKind.MISSING, SddArtifactLinkKind.INVALID}
            or reverse_link.link_type is not reverse_type
        ):
            issues.append(
                SddIssue(
                    severity="error",
                    code="reverse-link",
                    path=file.relpath,
                    message=f"{target.relpath} is missing a valid {reverse_field!r} link",
                )
            )
            continue
        if reverse_link.kind is SddArtifactLinkKind.MIXED and not mixed_link_agrees(
            root, target.path, reverse_link
        ):
            issues.append(
                SddIssue(
                    severity="error",
                    code="reverse-link",
                    path=file.relpath,
                    message=f"{target.relpath} has conflicting {reverse_field!r} links",
                )
            )
            continue
        resolved_reverse = resolve_link_path(root, target.path, reverse_link)
        if resolved_reverse is None:
            continue
        reverse_path = resolved_reverse.resolve()
        if reverse_path != file.path.resolve():
            issues.append(
                SddIssue(
                    severity="error",
                    code="reverse-link",
                    path=file.relpath,
                    message=(
                        f"{target.relpath} links back to "
                        f"{link_reference(root, target.path, reverse_link)}, "
                        f"not {file.relpath}"
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


def _strict_severity(strict: bool) -> Severity:
    return "error" if strict else "warning"


def _validate_parent_section(
    root: Path,
    file: SddFile,
    sections: tuple[PlanHeaderSection, ...],
    issues: list[SddIssue],
) -> None:
    parent = next(
        (
            section
            for section in sections
            if section.kind is PlanHeaderSectionKind.PARENT
        ),
        None,
    )
    if parent is None or parent.label is None:
        return
    from sase.sdd._paths import has_month_dirs
    from sase.sdd.plan_refs import resolve_plan_reference_from_roots

    plans_root = root / "plans" if has_month_dirs(root / "plans") else root
    resolution = resolve_plan_reference_from_roots(
        parent.label,
        roots=(plans_root,),
    )
    if resolution.resolved_path is not None and resolution.resolved_path.is_file():
        return
    issues.append(
        SddIssue(
            severity="error",
            code="parent-missing-target",
            path=file.relpath,
            message=(f"PARENT target does not resolve to a plan file: {parent.label}"),
        )
    )


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
