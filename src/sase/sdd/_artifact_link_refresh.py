"""Refresh v2 artifact-link truth and Markdown projections."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from sase.agents_sync.referenced_by_outbox_models import ReferencedByOutboxItem
from sase.sdd._artifact_link_projection import (
    artifact_link_row,
    artifact_projection_document,
    companion_seed,
    link_rows_changed,
    preview_link_rows,
    render_artifact_link_projection,
    safety_body,
)
from sase.sdd._referenced_by_refresh_models import (
    ReferencedByRefreshAction,
    ReferencedByRefreshIssue,
    ReferencedByRefreshReport,
)
from sase.sdd._referenced_by_refresh_utils import relative_path
from sase.sdd.artifact_link_store import ArtifactLinkStore
from sase.sdd.hosted_links import hosted_link_resolver
from sase.sdd.referenced_by_index import referenced_by_index_path

if TYPE_CHECKING:
    from sase.sdd.store import SddStore


def refresh_artifact_links_locked(
    store: SddStore,
    *,
    role: str,
    requests: tuple[ReferencedByOutboxItem, ...],
    write: bool,
) -> ReferencedByRefreshReport:
    """Refresh artifact links while the caller holds the repository lock."""

    repo_root = store.repo_root_for_kind(role).resolve(strict=False)
    issues: list[ReferencedByRefreshIssue] = []
    actions: list[ReferencedByRefreshAction] = []
    changed_paths: list[Path] = []
    grouped: dict[str, list[ReferencedByOutboxItem]] = defaultdict(list)
    for item in requests:
        grouped[item.artifact_id].append(item)
    project_key = requests[0].project_key if requests else "default"
    link_store = ArtifactLinkStore.from_sdd_store(store, project_key)
    resolver = hosted_link_resolver(
        store,
        project=requests[0].project if requests else None,
    )
    for artifact_id, group in sorted(grouped.items()):
        asset = (repo_root / group[0].repo_relpath).resolve(strict=False)
        if not asset.is_relative_to(repo_root) or not asset.is_file():
            issues.append(
                ReferencedByRefreshIssue(
                    "error",
                    "artifact-missing",
                    group[0].repo_relpath,
                    f"artifact document is missing: {group[0].repo_relpath}",
                )
            )
            continue
        try:
            document = artifact_projection_document(asset)
            is_companion = document != asset
            current = (
                document.read_text(encoding="utf-8")
                if document.exists()
                else companion_seed(asset, document)
            )
            existing_rows = link_store.load_artifact_rows(artifact_id)
            incoming_rows = tuple(artifact_link_row(item) for item in group)
            preview_rows = preview_link_rows(existing_rows, incoming_rows)
            updated = render_artifact_link_projection(
                current,
                artifact_id=artifact_id,
                rows=preview_rows,
                store=store,
                resolver=resolver,
                companion=is_companion,
            )
            if updated != current and safety_body(updated) != safety_body(current):
                issues.append(
                    ReferencedByRefreshIssue(
                        "error",
                        "managed-block-safety",
                        group[0].repo_relpath,
                        "artifact-link refresh would change text outside managed blocks",
                    )
                )
                continue
        except Exception as exc:
            issues.append(
                ReferencedByRefreshIssue(
                    "error",
                    "refresh-failed",
                    group[0].repo_relpath,
                    str(exc),
                )
            )
            continue

        index_changed = link_rows_changed(existing_rows, preview_rows)
        document_changed = updated != current
        if not index_changed and not document_changed:
            continue
        actions.append(
            ReferencedByRefreshAction(
                path=relative_path(repo_root, document),
                artifact_id=artifact_id,
                rows=len(preview_rows),
            )
        )
        if write:
            written_rows = preview_rows
            if index_changed:
                for row in incoming_rows:
                    link_store.upsert_row(row)
                written_rows = link_store.load_artifact_rows(artifact_id)
                index_path = referenced_by_index_path(repo_root, artifact_id)
                changed_paths.append(index_path)
            if document_changed:
                updated = render_artifact_link_projection(
                    current,
                    artifact_id=artifact_id,
                    rows=written_rows,
                    store=store,
                    resolver=resolver,
                    companion=is_companion,
                )
                if not document.exists():
                    document.parent.mkdir(parents=True, exist_ok=True)
                document.write_text(updated, encoding="utf-8")
                changed_paths.append(document)

    committed = (
        _commit_changes(store, repo_root, changed_paths, issues) if write else False
    )
    return ReferencedByRefreshReport(
        root=repo_root,
        role=role,
        write=write,
        scanned=len(grouped),
        actions=tuple(actions),
        issues=tuple(issues),
        changed_files=tuple(relative_path(repo_root, path) for path in changed_paths),
        committed=committed,
    )


def _commit_changes(
    store: SddStore,
    repo_root: Path,
    changed_paths: list[Path],
    issues: list[ReferencedByRefreshIssue],
) -> bool:
    if not changed_paths:
        return False
    try:
        from sase.file_references import format_markdown_files_with_prettier
        from sase.sdd.files import commit_sdd_store_files

        markdown_paths = [path for path in changed_paths if path.suffix == ".md"]
        if markdown_paths:
            format_markdown_files_with_prettier(markdown_paths)
        committed = bool(
            commit_sdd_store_files(
                store,
                "Update artifact link projections",
                paths=changed_paths,
                push_after_commit="async",
                already_locked=True,
                cause="artifact_links",
            )
        )
        if not committed:
            issues.append(
                ReferencedByRefreshIssue(
                    "error",
                    "commit-failed",
                    str(repo_root),
                    "artifact-link projections changed but no store commit was created",
                )
            )
        return committed
    except Exception as exc:
        issues.append(
            ReferencedByRefreshIssue(
                "error",
                "commit-failed",
                str(repo_root),
                f"could not commit artifact-link projections: {exc}",
            )
        )
        return False
