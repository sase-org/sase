"""Validation and repair helpers for linked SDD prompt and plan files."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.sdd._link_models import (
    RepairAction,
    RepairReport,
    Severity,
    SddFile,
    SddIssue,
    SddValidation,
    repair_to_json,
    validation_to_json,
)
from sase.sdd.artifact_links import (
    SddArtifactLink,
    SddArtifactLinkKind,
    SddArtifactLinkType,
    canonical_sdd_artifact_link,
    parse_sdd_artifact_link,
    update_source_aware_artifact_link,
)
from sase.sdd.plan_tiers import (
    classify_plan_file,
    normalize_plan_tier,
)

PLAN_KINDS = ("tales", "epics")
PROMPT_KINDS = ("prompts", "specs")
LIST_KINDS = ("prompts", "plans", "tales", "epics")

# Closed quarantine for historical invalid SDD files only; do not add new files.
LEGACY_INVALID_SDD_ERROR_ALLOWLIST: frozenset[str] = frozenset(
    {
        "plans/202605/prompts/recover_uncommitted_audit_work_1.md",
        "plans/202605/prompts/sase_mobile_mvp_legend.md",
    }
)

_SddIssue = SddIssue
_SddFile = SddFile
_SddValidation = SddValidation
_RepairAction = RepairAction
_RepairReport = RepairReport


def resolve_sdd_root(path: str | None = None, *, cwd: Path | None = None) -> Path:
    """Resolve an SDD root from either an SDD dir or a project dir."""
    base = Path.cwd() if cwd is None else cwd
    if path is None:
        return _resolve_project_sdd_root(base).resolve()

    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    if candidate.is_dir() and _looks_like_project_root(candidate):
        candidate = _resolve_project_sdd_root(candidate)
    return candidate.resolve()


def validate_sdd_tree(
    path: str | None = None, *, strict: bool = False
) -> _SddValidation:
    """Validate artifact metadata and bidirectional links under an SDD root."""
    root = resolve_sdd_root(path)
    if not root.is_dir():
        issue = _SddIssue(
            severity="error",
            code="invalid-root",
            path=str(root),
            message=f"SDD path does not exist or is not a directory: {root}",
        )
        return _SddValidation(root=root, files=[], issues=[issue])

    files = _list_sdd_files(root, kind="all")
    by_path = {file.path.resolve(): file for file in files}
    issues: list[_SddIssue] = []

    for file in files:
        if file.parse_error is not None:
            issues.append(
                _SddIssue(
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
                _SddIssue(
                    severity="error",
                    code="plan-tier",
                    path=file.relpath,
                    message="'tier' must be either 'tale' or 'epic'",
                )
            )

        link_type = _expected_link_type(file)
        link_field = link_type.legacy_field
        link = file.artifact_link
        counterpart = _infer_counterpart(file, files)
        if len(counterpart) == 1 and link.kind is SddArtifactLinkKind.MISSING:
            issues.append(
                _SddIssue(
                    severity="error",
                    code="missing-link",
                    path=file.relpath,
                    message=f"missing {link_field!r} link to {counterpart[0].relpath}",
                )
            )
        elif len(counterpart) > 1:
            issues.append(
                _SddIssue(
                    severity=_strict_severity(strict),
                    code="ambiguous-counterpart",
                    path=file.relpath,
                    message="multiple inferable counterpart files: "
                    + ", ".join(item.relpath for item in counterpart),
                )
            )
        elif not counterpart and link.kind is SddArtifactLinkKind.MISSING:
            issues.append(
                _SddIssue(
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
                _SddIssue(
                    severity="error",
                    code="link-format",
                    path=file.relpath,
                    message=f"invalid {link_field!r} artifact link: {link.reason}",
                )
            )
            continue
        if link.link_type is not link_type:
            issues.append(
                _SddIssue(
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
                _SddIssue(
                    severity="error",
                    code="link-placement",
                    path=file.relpath,
                    message=(
                        f"{link_type.value} bullet must be the first Markdown body "
                        "element with exactly one blank line after it"
                    ),
                )
            )
        if link.kind is SddArtifactLinkKind.MIXED and not _mixed_link_agrees(
            root, file.path, link
        ):
            issues.append(
                _SddIssue(
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

        target_path = _resolve_link_path(root, file.path, link)
        if target_path is None:
            continue
        target = by_path.get(target_path.resolve())
        if target is None:
            issues.append(
                _SddIssue(
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
                _SddIssue(
                    severity="error",
                    code="link-kind",
                    path=file.relpath,
                    message=f"{link_field!r} target is not a plan file: {target.relpath}",
                )
            )
        elif file.kind in PLAN_KINDS and target.kind != "prompts":
            issues.append(
                _SddIssue(
                    severity="error",
                    code="link-kind",
                    path=file.relpath,
                    message=f"{link_field!r} target is not a prompt file: {target.relpath}",
                )
            )

        reverse_type = _expected_link_type(target)
        reverse_field = reverse_type.legacy_field
        reverse_link = target.artifact_link
        if (
            reverse_link.kind
            in {SddArtifactLinkKind.MISSING, SddArtifactLinkKind.INVALID}
            or reverse_link.link_type is not reverse_type
        ):
            issues.append(
                _SddIssue(
                    severity="error",
                    code="reverse-link",
                    path=file.relpath,
                    message=f"{target.relpath} is missing a valid {reverse_field!r} link",
                )
            )
            continue
        if reverse_link.kind is SddArtifactLinkKind.MIXED and not _mixed_link_agrees(
            root, target.path, reverse_link
        ):
            issues.append(
                _SddIssue(
                    severity="error",
                    code="reverse-link",
                    path=file.relpath,
                    message=f"{target.relpath} has conflicting {reverse_field!r} links",
                )
            )
            continue
        resolved_reverse = _resolve_link_path(root, target.path, reverse_link)
        if resolved_reverse is None:
            continue
        reverse_path = resolved_reverse.resolve()
        if reverse_path != file.path.resolve():
            issues.append(
                _SddIssue(
                    severity="error",
                    code="reverse-link",
                    path=file.relpath,
                    message=(
                        f"{target.relpath} links back to "
                        f"{_link_reference(root, target.path, reverse_link)}, "
                        f"not {file.relpath}"
                    ),
                )
            )

    return _SddValidation(
        root=root, files=files, issues=_apply_legacy_error_allowlist(issues)
    )


def _list_sdd_files(root: Path, *, kind: str = "all") -> list[_SddFile]:
    """Return known SDD markdown files under ``root``."""
    files: list[_SddFile] = []
    plans_root = root / "plans"
    if not plans_root.is_dir():
        plans_root = root
    if kind in {"all", "prompts"}:
        if plans_root.is_dir():
            for path in sorted(plans_root.glob("*/prompts/*.md")):
                sdd_file = _read_sdd_file(root, path, "prompts")
                if sdd_file is not None:
                    files.append(sdd_file)
        for physical_kind in PROMPT_KINDS:
            kind_root = root / physical_kind
            if not kind_root.is_dir():
                continue
            for path in sorted(kind_root.glob("*/*.md")):
                sdd_file = _read_sdd_file(root, path, "prompts")
                if sdd_file is not None:
                    files.append(sdd_file)
    if kind in {"all", "plans", "tales", "epics"}:
        kind_root = plans_root
        if kind_root.is_dir():
            for path in sorted(kind_root.glob("*/*.md")):
                sdd_file = _read_sdd_file(root, path, "tales")
                if sdd_file is None:
                    continue
                item_kind = f"{classify_plan_file(path, sdd_file.frontmatter)}s"
                sdd_file = replace(sdd_file, kind=item_kind)
                if kind in {"all", "plans", item_kind}:
                    files.append(sdd_file)
    return sorted(files, key=lambda file: file.relpath)


def collect_sdd_links(root: Path) -> list[dict[str, Any]]:
    """Return link rows suitable for text or JSON display."""
    files = _list_sdd_files(root, kind="all")
    by_path = {file.path.resolve(): file for file in files}
    rows: list[dict[str, Any]] = []
    for file in files:
        link_type = _expected_link_type(file)
        link = file.artifact_link
        row: dict[str, Any] = {
            "path": file.relpath,
            "kind": file.kind,
            "field": link_type.legacy_field,
            "target": _link_reference(root, file.path, link),
            "target_exists": False,
            "bidirectional": False,
        }
        if link.link_type is link_type:
            resolved = _resolve_link_path(root, file.path, link)
            target = by_path.get(resolved.resolve()) if resolved is not None else None
            row["target_exists"] = target is not None
            if target is not None:
                reverse_type = _expected_link_type(target)
                reverse_link = target.artifact_link
                reverse_path = _resolve_link_path(root, target.path, reverse_link)
                row["bidirectional"] = (
                    reverse_link.link_type is reverse_type
                    and reverse_path is not None
                    and reverse_path.resolve() == file.path.resolve()
                )
        rows.append(row)
    return rows


def repair_sdd_links(path: str | None = None, *, write: bool = False) -> _RepairReport:
    """Infer unambiguous SDD pairs and repair missing or stale link fields."""
    root = resolve_sdd_root(path)
    if not root.is_dir():
        issue = _SddIssue(
            severity="error",
            code="invalid-root",
            path=str(root),
            message=f"SDD path does not exist or is not a directory: {root}",
        )
        return _RepairReport(
            root=root, write=write, actions=[], issues=[issue], changed_files=[]
        )

    files = _list_sdd_files(root, kind="all")
    issues: list[_SddIssue] = []
    updates: dict[Path, tuple[_SddFile, _SddFile, SddArtifactLinkType, str]] = {}
    actions: list[_RepairAction] = []

    for prompt_file in [file for file in files if file.kind == "prompts"]:
        if prompt_file.parse_error is not None:
            issues.append(
                _SddIssue(
                    severity="error",
                    code="frontmatter-parse",
                    path=prompt_file.relpath,
                    message=prompt_file.parse_error,
                )
            )
            continue
        candidates = _infer_counterpart(prompt_file, files)
        if len(candidates) != 1:
            if len(candidates) > 1:
                issues.append(
                    _SddIssue(
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
                _SddIssue(
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
            changed_files.append(_relpath(root, file_path))

    return _RepairReport(
        root=root,
        write=write,
        actions=actions,
        issues=issues,
        changed_files=changed_files,
    )


def _resolve_link_path(
    root: Path,
    source: Path,
    link: SddArtifactLink,
) -> Path | None:
    """Resolve a canonical href or compatible historical representation."""
    if link.kind is SddArtifactLinkKind.INVALID:
        return None
    if link.kind is SddArtifactLinkKind.MIXED and not _mixed_link_agrees(
        root, source, link
    ):
        return None
    if link.kind in {SddArtifactLinkKind.CANONICAL, SddArtifactLinkKind.MIXED}:
        if link.target is None:
            return None
        return source.parent / Path(link.target)
    if link.kind is SddArtifactLinkKind.LEGACY and link.legacy is not None:
        return _resolve_legacy_representation(root, source, link)
    return None


def _resolve_legacy_representation(
    root: Path, source: Path, link: SddArtifactLink
) -> Path:
    assert link.legacy is not None
    if link.legacy.format == "markdown":
        return source.parent / Path(link.legacy.target)
    return _resolve_legacy_link_path(root, link.legacy.target)


def _mixed_link_agrees(root: Path, source: Path, link: SddArtifactLink) -> bool:
    """Compare mixed canonical/legacy representations by physical path."""
    if link.target is None or link.legacy is None:
        return False
    canonical = (source.parent / Path(link.target)).resolve()
    legacy = _resolve_legacy_representation(root, source, link).resolve()
    return canonical == legacy


def _link_reference(root: Path, source: Path, link: SddArtifactLink) -> str | None:
    if link.kind is SddArtifactLinkKind.MIXED and _mixed_link_agrees(
        root, source, link
    ):
        return link.label
    return link.reference


def _resolve_legacy_link_path(root: Path, link: str) -> Path:
    """Resolve a historical plain frontmatter path with legacy fallbacks."""
    link_path = Path(link)
    if link_path.is_absolute():
        return link_path

    candidates = [
        root / link_path,
        root.parent / link_path,
        root.parent.parent / link_path,
        Path.cwd() / link_path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    if link.startswith("sdd/") or link.startswith(".sase/sdd/"):
        return root.parent / link_path
    return root / link_path


def _read_sdd_file(root: Path, path: Path, kind: str) -> _SddFile | None:
    parts = path.relative_to(root).parts
    nested_prompt = (
        kind == "prompts"
        and len(parts) == 4
        and parts[0] == "plans"
        and parts[2] == "prompts"
    )
    flat_prompt = kind == "prompts" and len(parts) == 3 and parts[1] == "prompts"
    flat_plan = kind != "prompts" and len(parts) == 2
    if len(parts) != 3 and not nested_prompt and not flat_prompt and not flat_plan:
        return None
    yyyymm = parts[0] if flat_prompt or flat_plan else parts[1]
    name = path.stem
    content = path.read_text(encoding="utf-8")
    artifact_link = parse_sdd_artifact_link(content)
    frontmatter, _, had_frontmatter, parse_error = _parse_frontmatter_strict(content)
    return _SddFile(
        path=path,
        relpath=_relpath(root, path),
        kind=kind,
        yyyymm=yyyymm,
        name=name,
        frontmatter=frontmatter,
        artifact_link=artifact_link,
        body=artifact_link.body,
        had_frontmatter=had_frontmatter,
        parse_error=parse_error,
    )


def _parse_frontmatter_strict(
    content: str,
) -> tuple[dict[str, Any], str, bool, str | None]:
    if not content.startswith("---\n"):
        return {}, content, False, None
    end = content.find("\n---\n", 4)
    if end == -1:
        return {}, content, True, "frontmatter closing marker not found"
    raw = content[4:end]
    try:
        parsed = yaml.safe_load(raw) if raw.strip() else {}
    except yaml.YAMLError as exc:
        return {}, content[end + 5 :], True, f"invalid YAML frontmatter: {exc}"
    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict):
        return {}, content[end + 5 :], True, "frontmatter must be a YAML mapping"
    return dict(parsed), content[end + 5 :], True, None


def _infer_counterpart(file: _SddFile, files: list[_SddFile]) -> list[_SddFile]:
    if file.kind == "prompts":
        wanted = set(PLAN_KINDS)
    else:
        wanted = {"prompts"}
    return [
        candidate
        for candidate in files
        if candidate.kind in wanted
        and candidate.yyyymm == file.yyyymm
        and candidate.name == file.name
    ]


def _queue_update(
    root: Path,
    source: _SddFile,
    target: _SddFile,
    link_type: SddArtifactLinkType,
    label_prefix: str,
    updates: dict[Path, tuple[_SddFile, _SddFile, SddArtifactLinkType, str]],
    actions: list[_RepairAction],
    issues: list[_SddIssue],
) -> None:
    link = source.artifact_link
    field = link_type.legacy_field
    if link.kind is SddArtifactLinkKind.INVALID:
        issues.append(
            _SddIssue(
                severity="error",
                code="link-format",
                path=source.relpath,
                message=f"cannot repair malformed artifact link: {link.reason}",
            )
        )
        return
    if link.link_type is not None and link.link_type is not link_type:
        issues.append(
            _SddIssue(
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
    if link.kind is SddArtifactLinkKind.MIXED and not _mixed_link_agrees(
        root, source.path, link
    ):
        issues.append(
            _SddIssue(
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
    resolved = _resolve_link_path(root, source.path, link)
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
    old = _link_reference(root, source.path, link)
    updates[source.path] = (source, target, link_type, label_prefix)
    actions.append(_RepairAction(path=source.relpath, field=field, old=old, new=new))


def _expected_link_type(file: _SddFile) -> SddArtifactLinkType:
    return (
        SddArtifactLinkType.PLAN
        if file.kind == "prompts"
        else SddArtifactLinkType.PROMPT
    )


def _relpath(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _strict_severity(strict: bool) -> Severity:
    return "error" if strict else "warning"


def _apply_legacy_error_allowlist(issues: list[_SddIssue]) -> list[_SddIssue]:
    if not LEGACY_INVALID_SDD_ERROR_ALLOWLIST:
        return issues
    return [
        _SddIssue(
            severity="warning",
            code=f"{issue.code}-legacy-allowed",
            path=issue.path,
            message=f"{issue.message}; legacy SDD validation error allowlisted",
        )
        if issue.severity == "error"
        and issue.path in LEGACY_INVALID_SDD_ERROR_ALLOWLIST
        else issue
        for issue in issues
    ]


def _looks_like_project_root(path: Path) -> bool:
    if path.name == "sdd" and path.parent.name == ".sase":
        return False
    if (
        path.name in {"plans", "research"}
        and path.parent.name == "repos"
        and path.parent.parent.name == "sase"
    ):
        return False
    if (path / "beads").is_dir():
        return False
    has_flat_months = any(
        child.is_dir() and len(child.name) == 6 and child.name.isdigit()
        for child in path.iterdir()
    )
    if has_flat_months:
        return False
    has_project_marker = (
        (path / "sase" / "sase.yml").is_file()
        or (path / "sase.yml").is_file()
        or (path / ".git").exists()
        or (path / "sdd").is_dir()
        or (path / ".sase" / "sdd").is_dir()
    )
    return has_project_marker and not any((path / kind).is_dir() for kind in LIST_KINDS)


def _resolve_project_sdd_root(project_root: Path) -> Path:
    try:
        from sase.sdd.store import resolve_sdd_dir

        return resolve_sdd_dir(project_root, 1)
    except Exception:
        return project_root / ".sase" / "sdd"
