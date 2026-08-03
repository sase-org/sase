"""Tree-wide reconciliation for generated bead pages."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING

from sase.bead.model import Issue
from sase.bead_pages.paths import (
    BEAD_PAGES_DIRNAME,
    bead_lineage_root,
    bead_page_path,
)
from sase.bead_pages.refresh_models import (
    BeadPagesRefreshAction,
    BeadPagesRefreshIssue,
    BeadPagesRefreshReport,
    bead_pages_refresh_to_json,
)

if TYPE_CHECKING:
    from sase.bead_pages.associations import BeadAssociationIndex
    from sase.sdd.hosted_links import HostedLinkResolver
    from sase.sdd.store import SddStore


def refresh_bead_pages(
    store: SddStore,
    *,
    primary_root: Path | str,
    bead_id: str | None = None,
    write: bool = False,
    project: str | None = None,
    association_index: BeadAssociationIndex | None = None,
    link_resolver: HostedLinkResolver | None = None,
) -> BeadPagesRefreshReport:
    """Rebuild generated bead pages, optionally writing one batched commit."""

    from sase.sdd.checkout_anchor import resolve_checkout_anchor

    anchor = resolve_checkout_anchor(primary_root)
    resolved_project = project or anchor.project_name
    pages_root = store.repo_root_for_kind("beads") / BEAD_PAGES_DIRNAME
    if not store.is_sidecar_storage or store.beads_dir is None:
        return _error_report(
            pages_root,
            write,
            bead_id,
            "missing-sidecar",
            "project has no recorded beads sidecar",
        )

    from sase.sdd._git_contention import store_git_write_lock

    lock = (
        store_git_write_lock(
            store.repo_root_for_kind("beads"),
            op="sdd.bead_pages.refresh",
            mutates_worktree=True,
        )
        if write
        else nullcontext(True)
    )
    with lock as acquired:
        if not acquired:
            return _error_report(
                pages_root,
                write,
                bead_id,
                "lock-busy",
                "beads store write lock is busy",
            )
        return _refresh_locked(
            store,
            pages_root=pages_root,
            primary_root=anchor.primary_root,
            bead_id=bead_id,
            write=write,
            project=resolved_project,
            association_index=association_index,
            link_resolver=link_resolver,
        )


def _refresh_locked(
    store: SddStore,
    *,
    pages_root: Path,
    primary_root: Path,
    bead_id: str | None,
    write: bool,
    project: str | None,
    association_index: BeadAssociationIndex | None,
    link_resolver: HostedLinkResolver | None,
) -> BeadPagesRefreshReport:
    issues: list[BeadPagesRefreshIssue] = []
    try:
        from sase.bead.store_locator import open_bead_project_for_beads_dir

        view_context = open_bead_project_for_beads_dir(store.kind_root("beads"))
        with view_context as view:
            bead_issues = tuple(view.list_issues())
            from sase.bead_pages.links import bead_id_aliases_for_store

            aliases = bead_id_aliases_for_store(store)
            canonical_bead_id = (
                None if bead_id is None else aliases.get(bead_id, bead_id)
            )
            selected = _select_issues(bead_issues, canonical_bead_id)
            if selected is None:
                return _error_report(
                    pages_root,
                    write,
                    bead_id,
                    "bead-unresolved",
                    f"bead does not exist in store: {bead_id}",
                )
            valid_aliases, alias_issues = _validated_aliases(
                aliases,
                bead_issues,
                pages_root,
            )
            issues.extend(alias_issues)

            resolver = link_resolver
            if resolver is None:
                from sase.sdd.hosted_links import hosted_link_resolver

                resolver = hosted_link_resolver(
                    store,
                    project=project,
                    primary_root=primary_root,
                )
            index = association_index
            if index is None:
                from sase.bead_pages.associations import (
                    build_bead_association_index,
                )

                index = build_bead_association_index(
                    store,
                    primary_root=primary_root,
                    project=project,
                    link_resolver=resolver,
                    bead_issues=bead_issues,
                )
            issues.extend(
                BeadPagesRefreshIssue(
                    "warning",
                    "association-source",
                    str(pages_root),
                    diagnostic,
                )
                for diagnostic in index.diagnostics
            )
            payloads = _render_payloads(
                pages_root,
                bead_issues,
                selected,
                index,
                resolver,
                valid_aliases,
                include_roster=bead_id is None,
            )
    except Exception as exc:  # noqa: BLE001 - command-level diagnostic.
        return _error_report(
            pages_root,
            write,
            bead_id,
            "refresh-failed",
            f"could not build bead-page projection: {exc}",
        )

    desired_paths = frozenset(path for path, _payload, _bead in payloads)
    orphan_paths = _orphan_paths(
        pages_root,
        desired_paths,
        lineage=bead_lineage_root(bead_id) if bead_id is not None else None,
    )
    actions = _actions(pages_root, payloads, orphan_paths)
    changed_files: tuple[str, ...] = ()
    removed_files: tuple[str, ...] = ()
    committed = False
    if write and actions:
        changed, removed = _apply_actions(
            pages_root,
            payloads,
            orphan_paths,
        )
        changed_files = tuple(_relative(pages_root, path) for path in changed)
        removed_files = tuple(_relative(pages_root, path) for path in removed)
        try:
            from sase.sdd.files import commit_sdd_store_files

            committed = commit_sdd_store_files(
                store,
                "Refresh bead pages",
                paths=(*changed, *removed),
                auto_commit_type="beads",
                push_after_commit="async",
                already_locked=True,
            )
            if not committed:
                issues.append(
                    BeadPagesRefreshIssue(
                        "error",
                        "commit-failed",
                        str(pages_root),
                        "bead pages changed but no beads-store commit was created",
                    )
                )
        except Exception as exc:  # noqa: BLE001 - preserve written repair.
            issues.append(
                BeadPagesRefreshIssue(
                    "error",
                    "commit-failed",
                    str(pages_root),
                    f"could not commit refreshed bead pages: {exc}",
                )
            )

    return BeadPagesRefreshReport(
        root=pages_root,
        write=write,
        bead=bead_id,
        scanned=len(selected),
        lineages=len({bead_lineage_root(issue.id) for issue in selected}),
        actions=actions,
        issues=tuple(issues),
        changed_files=changed_files,
        removed_files=removed_files,
        committed=committed,
    )


def _select_issues(
    issues: tuple[Issue, ...],
    bead_id: str | None,
) -> tuple[Issue, ...] | None:
    if bead_id is None:
        return tuple(sorted(issues, key=lambda issue: issue.id))
    known = frozenset(issue.id for issue in issues)
    if bead_id not in known:
        return None
    root_id = bead_lineage_root(bead_id)
    return tuple(
        sorted(
            (issue for issue in issues if bead_lineage_root(issue.id) == root_id),
            key=lambda issue: issue.id,
        )
    )


def _render_payloads(
    pages_root: Path,
    all_issues: tuple[Issue, ...],
    selected: tuple[Issue, ...],
    association_index: BeadAssociationIndex,
    link_resolver: HostedLinkResolver,
    aliases: Mapping[str, str],
    *,
    include_roster: bool,
) -> tuple[tuple[Path, bytes, str | None], ...]:
    from sase.bead.cli_detail import IssueDetailIndex
    from sase.bead_pages.rendering import render_bead_page_detail_bytes
    from sase.bead_pages.rendering import render_bead_alias_page_bytes
    from sase.bead_pages.roster import render_bead_pages_roster_bytes

    detail_index = IssueDetailIndex.from_issues(all_issues)
    payloads: list[tuple[Path, bytes, str | None]] = [
        (
            pages_root.parent / bead_page_path(issue.id),
            render_bead_page_detail_bytes(
                detail_index.resolve(issue),
                all_issues,
                association_index,
                link_resolver=link_resolver,
            ),
            issue.id,
        )
        for issue in selected
    ]
    selected_ids = frozenset(issue.id for issue in selected)
    payloads.extend(
        (
            pages_root.parent / bead_page_path(old_id),
            render_bead_alias_page_bytes(old_id, canonical_id),
            canonical_id,
        )
        for old_id, canonical_id in aliases.items()
        if canonical_id in selected_ids
    )
    if include_roster:
        payloads.append(
            (
                pages_root / "README.md",
                render_bead_pages_roster_bytes(all_issues, association_index),
                None,
            )
        )
    return tuple(sorted(payloads, key=lambda item: item[0].as_posix()))


def _validated_aliases(
    aliases: Mapping[str, str],
    issues: tuple[Issue, ...],
    pages_root: Path,
) -> tuple[dict[str, str], tuple[BeadPagesRefreshIssue, ...]]:
    canonical_ids = frozenset(issue.id for issue in issues)
    valid: dict[str, str] = {}
    diagnostics: list[BeadPagesRefreshIssue] = []
    for old_id, canonical_id in sorted(aliases.items()):
        if old_id in canonical_ids:
            diagnostics.append(
                BeadPagesRefreshIssue(
                    "error",
                    "alias-shadows-canonical",
                    str(pages_root),
                    f"bead ID alias shadows canonical ID: {old_id}",
                )
            )
            continue
        if canonical_id not in canonical_ids:
            diagnostics.append(
                BeadPagesRefreshIssue(
                    "error",
                    "alias-target-missing",
                    str(pages_root),
                    f"bead ID alias target does not exist: {old_id} -> {canonical_id}",
                )
            )
            continue
        try:
            bead_page_path(old_id)
            bead_page_path(canonical_id)
        except ValueError as exc:
            diagnostics.append(
                BeadPagesRefreshIssue(
                    "error",
                    "alias-page-invalid",
                    str(pages_root),
                    str(exc),
                )
            )
            continue
        valid[old_id] = canonical_id
    return valid, tuple(diagnostics)


def _orphan_paths(
    pages_root: Path,
    desired_paths: frozenset[Path],
    *,
    lineage: str | None,
) -> tuple[Path, ...]:
    scan_root = pages_root / lineage if lineage is not None else pages_root
    if not scan_root.is_dir():
        return ()
    current = {
        path
        for path in scan_root.rglob("*.md")
        if path.is_file() and (lineage is not None or path != pages_root / "README.md")
    }
    return tuple(sorted(current - desired_paths))


def _actions(
    pages_root: Path,
    payloads: tuple[tuple[Path, bytes, str | None], ...],
    orphan_paths: tuple[Path, ...],
) -> tuple[BeadPagesRefreshAction, ...]:
    actions = [
        BeadPagesRefreshAction(
            _relative(pages_root, path),
            "create" if not path.is_file() else "update",
            bead_id,
        )
        for path, payload, bead_id in payloads
        if not path.is_file() or path.read_bytes() != payload
    ]
    actions.extend(
        BeadPagesRefreshAction(_relative(pages_root, path), "remove")
        for path in orphan_paths
    )
    return tuple(sorted(actions, key=lambda action: action.path))


def _apply_actions(
    pages_root: Path,
    payloads: tuple[tuple[Path, bytes, str | None], ...],
    orphan_paths: tuple[Path, ...],
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    changed: list[Path] = []
    for path, payload, _bead_id in payloads:
        if path.is_file() and path.read_bytes() == payload:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        changed.append(path)
    for path in orphan_paths:
        path.unlink()
        _remove_empty_parent(path.parent, stop=pages_root)
    return tuple(changed), orphan_paths


def _remove_empty_parent(path: Path, *, stop: Path) -> None:
    current = path
    while current != stop and current.is_dir() and not any(current.iterdir()):
        current.rmdir()
        current = current.parent


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _error_report(
    root: Path,
    write: bool,
    bead_id: str | None,
    code: str,
    message: str,
) -> BeadPagesRefreshReport:
    issue = BeadPagesRefreshIssue("error", code, str(root), message)
    return BeadPagesRefreshReport(
        root,
        write,
        bead_id,
        0,
        0,
        (),
        (issue,),
        (),
        (),
        False,
    )


__all__ = [
    "BeadPagesRefreshAction",
    "BeadPagesRefreshIssue",
    "BeadPagesRefreshReport",
    "bead_pages_refresh_to_json",
    "refresh_bead_pages",
]
