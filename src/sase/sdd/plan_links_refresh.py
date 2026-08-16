"""Tree-wide reconciliation for projected plan provenance headers."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING

from sase.sdd._plan_links_refresh_models import (
    PlanLinksRefreshAction,
    PlanLinksRefreshIssue,
    PlanLinksRefreshReport,
    plan_links_refresh_to_json,
)
from sase.sdd.plan_header_block import (
    PlanHeaderDisposition,
    PlanHeaderSectionKind,
    parse_plan_header_block,
)

if TYPE_CHECKING:
    from sase.sdd.associations import PlanAssociationIndex
    from sase.sdd.store import SddStore


def refresh_plan_links(
    store: SddStore,
    *,
    primary_root: Path | str,
    plan_ref: str | None = None,
    write: bool = False,
    project: str | None = None,
    association_index: PlanAssociationIndex | None = None,
) -> PlanLinksRefreshReport:
    """Rebuild plan header projections, optionally writing one batched commit."""

    root = store.kind_root("plans").resolve(strict=False)
    primary = Path(primary_root).resolve(strict=False)
    if not root.is_dir():
        return _report_with_root_error(root, write, plan_ref)

    from sase.sdd._git_contention import store_git_write_lock

    lock = (
        store_git_write_lock(
            store.repo_root_for_kind("plans"),
            op="sdd.plan_links.refresh",
            mutates_worktree=True,
        )
        if write
        else nullcontext(True)
    )
    with lock as acquired:
        if not acquired:
            return _report_with_lock_error(root, write, plan_ref)
        return _refresh_locked(
            store,
            root=root,
            primary=primary,
            plan_ref=plan_ref,
            write=write,
            project=project,
            association_index=association_index,
        )


def _refresh_locked(
    store: SddStore,
    *,
    root: Path,
    primary: Path,
    plan_ref: str | None,
    write: bool,
    project: str | None,
    association_index: PlanAssociationIndex | None,
) -> PlanLinksRefreshReport:
    issues: list[PlanLinksRefreshIssue] = []
    paths = _plan_paths(root)
    if plan_ref is not None:
        selected = _resolve_real_plan(plan_ref, root)
        if selected is None or selected not in paths:
            issues.append(
                PlanLinksRefreshIssue(
                    "error",
                    "plan-unresolved",
                    plan_ref,
                    f"plan reference does not resolve to a real plan file: {plan_ref}",
                )
            )
            paths = ()
        else:
            paths = (selected,)

    index = association_index
    if paths and index is None:
        try:
            from sase.sdd.associations import build_plan_association_index

            index = build_plan_association_index(
                store,
                primary_root=primary,
                project=project,
            )
        except Exception as exc:  # noqa: BLE001 - command-level diagnostic.
            issues.append(
                PlanLinksRefreshIssue(
                    "error",
                    "association-index",
                    str(root),
                    f"could not build plan association index: {exc}",
                )
            )
            paths = ()
    if index is not None:
        issues.extend(
            PlanLinksRefreshIssue("warning", "association-source", str(root), item)
            for item in index.diagnostics
        )

    known_bead_ids = None
    if paths:
        from sase.bead_pages.links import known_bead_ids_for_store

        known_bead_ids = known_bead_ids_for_store(store)

    actions: list[PlanLinksRefreshAction] = []
    changed_paths: list[Path] = []
    for path in paths:
        assert index is not None
        result = _refresh_one(
            path,
            root,
            store,
            primary,
            index,
            project=project,
            known_bead_ids=known_bead_ids,
        )
        if isinstance(result, PlanLinksRefreshIssue):
            issues.append(result)
            continue
        action, updated = result
        if action is None or updated is None:
            continue
        actions.append(action)
        if write:
            path.write_text(updated, encoding="utf-8")
            changed_paths.append(path)

    committed = False
    if write and changed_paths:
        try:
            from sase.file_references import format_markdown_files_with_prettier
            from sase.sdd.files import commit_sdd_store_files

            format_markdown_files_with_prettier(changed_paths)
            committed = bool(
                commit_sdd_store_files(
                    store,
                    "Refresh plan provenance links",
                    paths=changed_paths,
                    push_after_commit="async",
                    already_locked=True,
                )
            )
            if not committed:
                issues.append(
                    PlanLinksRefreshIssue(
                        "error",
                        "commit-failed",
                        str(root),
                        "plan headers changed but no plans-store commit was created",
                    )
                )
        except Exception as exc:  # noqa: BLE001 - preserve written repair.
            issues.append(
                PlanLinksRefreshIssue(
                    "error",
                    "commit-failed",
                    str(root),
                    f"could not commit refreshed plan headers: {exc}",
                )
            )

    return PlanLinksRefreshReport(
        root=root,
        write=write,
        plan=plan_ref,
        scanned=len(paths),
        actions=tuple(actions),
        issues=tuple(issues),
        changed_files=tuple(_relative(root, path) for path in changed_paths),
        committed=committed,
    )


def _refresh_one(
    path: Path,
    root: Path,
    store: SddStore,
    primary: Path,
    index: PlanAssociationIndex,
    *,
    project: str | None = None,
    known_bead_ids: frozenset[str] | None = None,
) -> tuple[PlanLinksRefreshAction | None, str | None] | PlanLinksRefreshIssue:
    from sase.sdd.plan_refs import canonicalize_plan_reference_from_roots

    plan_ref = canonicalize_plan_reference_from_roots(path, roots=(root,))
    if plan_ref is None:
        return PlanLinksRefreshIssue(
            "error",
            "plan-normalization",
            _relative(root, path),
            "plan path could not be normalized",
        )
    current = path.read_text(encoding="utf-8")
    parsed = parse_plan_header_block(current)
    if parsed.disposition is PlanHeaderDisposition.INVALID:
        return PlanLinksRefreshIssue(
            "error",
            "header-invalid",
            _relative(root, path),
            parsed.reason or "plan header block is malformed",
        )

    associations = index.for_plan(plan_ref)
    try:
        from sase.sdd.plan_header_writes import (
            refresh_bead_plan_section,
            refresh_prompt_plan_section,
        )

        updated = refresh_bead_plan_section(
            current,
            store=store,
            primary_root=primary,
            known_bead_ids=known_bead_ids,
        )
        updated = refresh_prompt_plan_section(
            updated,
            source_path=path,
            store=store,
            primary_root=primary,
            project=project,
        )
        updated, parent_migrated = _refresh_parent(
            updated,
            path=path,
            root=root,
            store=store,
            primary=primary,
            parsed=parsed,
        )
        from sase.sdd.plan_header_writes import refresh_association_sections

        updated = refresh_association_sections(updated, associations)
    except _UnresolvedParent as exc:
        return PlanLinksRefreshIssue(
            "error",
            "parent-unresolved",
            _relative(root, path),
            str(exc),
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        return PlanLinksRefreshIssue(
            "error",
            "header-refresh",
            _relative(root, path),
            str(exc),
        )
    if updated == current:
        return None, None
    return (
        PlanLinksRefreshAction(
            path=_relative(root, path),
            plan=plan_ref,
            parent_migrated=parent_migrated,
            agents=len(associations.agents),
            commits=len(associations.commits),
        ),
        updated,
    )


class _UnresolvedParent(ValueError):
    """A legacy or canonical parent label does not name a real plan."""


def _refresh_parent(
    document: str,
    *,
    path: Path,
    root: Path,
    store: SddStore,
    primary: Path,
    parsed: object,
) -> tuple[str, bool]:
    from sase.sdd.plan_tiers import parse_plan_frontmatter

    frontmatter, parse_error = parse_plan_frontmatter(document)
    if parse_error is not None:
        raise ValueError(parse_error)
    legacy_parent = frontmatter.get("parent")
    if legacy_parent is not None:
        if not isinstance(legacy_parent, str) or not legacy_parent.strip():
            raise _UnresolvedParent("legacy `parent` must be a non-empty string")
        if _resolve_real_plan(legacy_parent, root) is None:
            raise _UnresolvedParent(
                f"legacy `parent` does not resolve to a real plan: {legacy_parent}"
            )
        from sase.sdd.plan_header_writes import upsert_parent_plan_section

        return (
            upsert_parent_plan_section(
                document,
                legacy_parent,
                source_path=path,
                plans_root=root,
                store=store,
                primary_root=primary,
            ),
            True,
        )

    sections = getattr(parsed, "sections", ())
    parent = next(
        (
            section
            for section in sections
            if section.kind is PlanHeaderSectionKind.PARENT
        ),
        None,
    )
    if parent is None or parent.label is None:
        return document, False
    if _resolve_real_plan(parent.label, root) is None:
        raise _UnresolvedParent(
            f"PARENT section does not resolve to a real plan: {parent.label}"
        )
    from sase.sdd.plan_header_writes import refresh_existing_parent_section

    return (
        refresh_existing_parent_section(
            document,
            source_path=path,
            plans_root=root,
            store=store,
            primary_root=primary,
        ),
        False,
    )


def _resolve_real_plan(value: str, root: Path) -> Path | None:
    from sase.sdd.plan_refs import resolve_plan_reference_from_roots

    resolution = resolve_plan_reference_from_roots(value, roots=(root,))
    path = resolution.resolved_path
    if path is None or not path.is_file():
        return None
    return path.resolve(strict=False)


def _plan_paths(root: Path) -> tuple[Path, ...]:
    from sase.sdd._paths import is_month_dir_name
    from sase.sdd.plan_tiers import normalize_plan_tier, parse_plan_frontmatter

    result: list[Path] = []
    for month in sorted(path for path in root.iterdir() if path.is_dir()):
        if not is_month_dir_name(month.name):
            continue
        for path in sorted(month.glob("*.md")):
            frontmatter, error = parse_plan_frontmatter(
                path.read_text(encoding="utf-8")
            )
            if error is None and normalize_plan_tier(frontmatter.get("tier")):
                result.append(path.resolve(strict=False))
    return tuple(result)


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _report_with_root_error(
    root: Path,
    write: bool,
    plan_ref: str | None,
) -> PlanLinksRefreshReport:
    issue = PlanLinksRefreshIssue(
        "error",
        "invalid-root",
        str(root),
        f"plans root does not exist or is not a directory: {root}",
    )
    return PlanLinksRefreshReport(root, write, plan_ref, 0, (), (issue,), (), False)


def _report_with_lock_error(
    root: Path,
    write: bool,
    plan_ref: str | None,
) -> PlanLinksRefreshReport:
    issue = PlanLinksRefreshIssue(
        "error",
        "lock-busy",
        str(root),
        "plans store write lock is busy",
    )
    return PlanLinksRefreshReport(root, write, plan_ref, 0, (), (issue,), (), False)


__all__ = [
    "PlanLinksRefreshAction",
    "PlanLinksRefreshIssue",
    "PlanLinksRefreshReport",
    "plan_links_refresh_to_json",
    "refresh_plan_links",
]
