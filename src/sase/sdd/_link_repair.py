"""Repair helpers for linked SDD artifacts."""

from __future__ import annotations

from pathlib import Path

from sase.sdd._link_files import list_sdd_files, resolve_sdd_root
from sase.sdd._link_models import RepairAction, RepairReport, SddFile, SddIssue
from sase.sdd._link_parent import LocalPlanChanges, parent_section_issue
from sase.sdd._link_support import (
    PLAN_KINDS,
    infer_counterpart,
    link_reference,
    mixed_link_agrees,
    relpath,
    resolve_link_path,
)
from sase.sdd.artifact_links import (
    SddArtifactLinkKind,
    SddArtifactLinkType,
    canonical_sdd_artifact_link,
    update_source_aware_artifact_link,
)


def repair_sdd_links(path: str | None = None, *, write: bool = False) -> RepairReport:
    """Infer unambiguous SDD pairs and repair missing or stale link fields."""
    root = resolve_sdd_root(path)
    if not root.is_dir():
        issue = SddIssue(
            severity="error",
            code="invalid-root",
            path=str(root),
            message=f"SDD path does not exist or is not a directory: {root}",
        )
        return RepairReport(
            root=root, write=write, actions=[], issues=[issue], changed_files=[]
        )

    files = list_sdd_files(root, kind="all")
    issues: list[SddIssue] = _parent_section_issues(root, files)
    updates: dict[Path, tuple[SddFile, SddFile, SddArtifactLinkType, str]] = {}
    actions: list[RepairAction] = []

    for prompt_file in [file for file in files if file.kind == "prompts"]:
        if prompt_file.parse_error is not None:
            issues.append(
                SddIssue(
                    severity="error",
                    code="frontmatter-parse",
                    path=prompt_file.relpath,
                    message=prompt_file.parse_error,
                )
            )
            continue
        candidates = infer_counterpart(prompt_file, files)
        if len(candidates) != 1:
            if len(candidates) > 1:
                issues.append(
                    SddIssue(
                        severity="warning",
                        code="ambiguous-counterpart",
                        path=prompt_file.relpath,
                        message="skipping ambiguous counterparts: "
                        + ", ".join(item.relpath for item in candidates),
                    )
                )
            continue
        plan_file = candidates[0]
        if plan_file.parse_error is not None:
            issues.append(
                SddIssue(
                    severity="error",
                    code="frontmatter-parse",
                    path=plan_file.relpath,
                    message=plan_file.parse_error,
                )
            )
            continue
        _queue_update(
            root,
            prompt_file,
            plan_file,
            SddArtifactLinkType.PLAN,
            "../",
            updates,
            actions,
            issues,
        )
        _queue_update(
            root,
            plan_file,
            prompt_file,
            SddArtifactLinkType.PROMPT,
            "",
            updates,
            actions,
            issues,
        )

    changed_files: list[str] = []
    if write:
        for file_path, update in sorted(updates.items(), key=lambda item: str(item[0])):
            source, target, link_type, label_prefix = update
            content = file_path.read_text(encoding="utf-8")
            file_path.write_text(
                update_source_aware_artifact_link(
                    content,
                    root,
                    source.path,
                    target.path,
                    link_type,
                    label_prefix=label_prefix,
                    remove_legacy=True,
                ),
                encoding="utf-8",
            )
            changed_files.append(relpath(root, file_path))

    return RepairReport(
        root=root,
        write=write,
        actions=actions,
        issues=issues,
        changed_files=changed_files,
    )


def _parent_section_issues(root: Path, files: list[SddFile]) -> list[SddIssue]:
    """Report every plan whose PARENT header does not resolve under *root*.

    Repair cannot invent a parent plan, but reporting the condition keeps it
    from staying silent while ``validate`` fails on it. The published-parent
    case self-heals: ``--write`` refreshes the plans store first, so a parent
    that has since landed resolves by the time this runs.
    """

    from sase.sdd.plan_header_block import (
        PlanHeaderDisposition,
        parse_plan_header_block,
    )

    local_changes = LocalPlanChanges(root)
    issues: list[SddIssue] = []
    for file in files:
        if file.kind not in PLAN_KINDS or file.parse_error is not None:
            continue
        header = parse_plan_header_block(file.path.read_text(encoding="utf-8"))
        if header.disposition is PlanHeaderDisposition.INVALID:
            continue
        issue = parent_section_issue(root, file, header.sections, local_changes)
        if issue is not None:
            issues.append(issue)
    return issues


def _queue_update(
    root: Path,
    source: SddFile,
    target: SddFile,
    link_type: SddArtifactLinkType,
    label_prefix: str,
    updates: dict[Path, tuple[SddFile, SddFile, SddArtifactLinkType, str]],
    actions: list[RepairAction],
    issues: list[SddIssue],
) -> None:
    link = source.artifact_link
    field = link_type.legacy_field
    if link.kind is SddArtifactLinkKind.INVALID:
        issues.append(
            SddIssue(
                severity="error",
                code="link-format",
                path=source.relpath,
                message=f"cannot repair malformed artifact link: {link.reason}",
            )
        )
        return
    if link.link_type is not None and link.link_type is not link_type:
        issues.append(
            SddIssue(
                severity="error",
                code="link-kind",
                path=source.relpath,
                message=(
                    f"cannot replace {link.link_type.value} link with "
                    f"required {link_type.value} link"
                ),
            )
        )
        return
    if link.kind is SddArtifactLinkKind.MIXED and not mixed_link_agrees(
        root, source.path, link
    ):
        issues.append(
            SddIssue(
                severity="error",
                code="link-conflict",
                path=source.relpath,
                message=(
                    "canonical bullet and legacy frontmatter link resolve to "
                    "different targets; refusing repair"
                ),
            )
        )
        return

    new_label, new_href, new = canonical_sdd_artifact_link(
        root,
        source.path,
        target.path,
        link_type,
        label_prefix=label_prefix,
    )
    resolved = resolve_link_path(root, source.path, link)
    is_current = (
        link.kind is SddArtifactLinkKind.CANONICAL
        and link.canonical_layout
        and link.label == new_label
        and link.target == new_href
        and resolved is not None
        and resolved.resolve() == target.path.resolve()
    )
    if is_current:
        return
    old = link_reference(root, source.path, link)
    updates[source.path] = (source, target, link_type, label_prefix)
    actions.append(RepairAction(path=source.relpath, field=field, old=old, new=new))
