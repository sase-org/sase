"""Refresh legacy Referenced By indexes and Markdown projections."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.agents_sync.io import atomic_write_json
from sase.agents_sync.referenced_by_outbox_models import ReferencedByOutboxItem
from sase.core.rust import require_rust_binding
from sase.sdd._referenced_by_refresh_models import (
    ReferencedByRefreshAction,
    ReferencedByRefreshIssue,
    ReferencedByRefreshReport,
)
from sase.sdd._referenced_by_refresh_utils import relative_path
from sase.sdd.referenced_by_index import (
    merge_referenced_by_rows,
    read_referenced_by_index,
    referenced_by_index_path,
    referenced_by_index_schema_version,
)

if TYPE_CHECKING:
    from sase.sdd.store import SddStore


def refresh_legacy_locked(
    store: SddStore,
    *,
    role: str,
    requests: tuple[ReferencedByOutboxItem, ...],
    write: bool,
) -> ReferencedByRefreshReport:
    """Refresh legacy projections while the caller holds the repository lock."""

    repo_root = store.repo_root_for_kind(role).resolve(strict=False)
    issues: list[ReferencedByRefreshIssue] = []
    actions: list[ReferencedByRefreshAction] = []
    changed_paths: list[Path] = []
    grouped: dict[str, list[ReferencedByOutboxItem]] = defaultdict(list)
    for item in requests:
        grouped[item.artifact_id].append(item)

    for artifact_id, group in sorted(grouped.items()):
        document = (repo_root / group[0].repo_relpath).resolve(strict=False)
        if not document.is_relative_to(repo_root) or not document.is_file():
            issues.append(
                ReferencedByRefreshIssue(
                    "error",
                    "artifact-missing",
                    group[0].repo_relpath,
                    f"artifact document is missing: {group[0].repo_relpath}",
                )
            )
            continue
        index_path = referenced_by_index_path(repo_root, artifact_id)
        if referenced_by_index_schema_version(index_path) == 2:
            # v2 truth is owned by the artifact-link adapter; do not clobber it.
            continue
        try:
            existing_index = read_referenced_by_index(index_path)
            merged_index = merge_referenced_by_rows(existing_index, group)
            current = document.read_text(encoding="utf-8")
            table = _table_from_index(merged_index)
            updated = str(
                require_rust_binding("referenced_by_block_upsert")(current, table)
            )
            remove_block = require_rust_binding("referenced_by_block_remove")
            if updated != current and str(remove_block(updated)) != str(
                remove_block(current)
            ):
                issues.append(
                    ReferencedByRefreshIssue(
                        "error",
                        "managed-block-safety",
                        group[0].repo_relpath,
                        "referenced-by refresh would change text outside the managed block",
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
        index_changed = _index_changed(index_path, merged_index)
        document_changed = updated != current
        if not index_changed and not document_changed:
            continue
        actions.append(
            ReferencedByRefreshAction(
                path=group[0].repo_relpath,
                artifact_id=artifact_id,
                rows=len(merged_index.get("rows", [])),
            )
        )
        if write:
            if document_changed:
                document.write_text(updated, encoding="utf-8")
                changed_paths.append(document)
            if index_changed:
                index_path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_json(index_path, merged_index)
                changed_paths.append(index_path)

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


def _table_from_index(index: dict[str, Any]) -> dict[str, object]:
    rows = []
    for row in index.get("rows", []):
        if not isinstance(row, dict):
            continue
        values = {
            "agent": str(row.get("agent") or ""),
            "project": str(row.get("project") or ""),
            "reference": str(row.get("canonical_ref") or ""),
            "published": str(row.get("published") or ""),
            "uses": str(row.get("uses") or "0"),
        }
        link_targets = {}
        agent_url = row.get("agent_url")
        if isinstance(agent_url, str) and agent_url:
            link_targets["agent"] = agent_url
        rows.append({"values": values, "link_targets": link_targets})
    return {
        "schema_version": int(
            require_rust_binding("referenced_by_wire_schema_version")()
        ),
        "columns": [
            {"key": "agent", "label": "Agent", "numeric": False},
            {"key": "project", "label": "Project", "numeric": False},
            {"key": "reference", "label": "Reference", "numeric": False},
            {"key": "published", "label": "Published", "numeric": False},
            {"key": "uses", "label": "Uses", "numeric": True},
        ],
        "rows": rows,
        "omitted": 0,
    }


def _index_changed(path: Path, document: dict[str, Any]) -> bool:
    try:
        current = read_referenced_by_index(path)
    except FileNotFoundError:
        return True
    except Exception:
        return True
    return current != document


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
                "Update Referenced By projections",
                paths=changed_paths,
                push_after_commit="async",
                already_locked=True,
                cause="referenced_by",
            )
        )
        if not committed:
            issues.append(
                ReferencedByRefreshIssue(
                    "error",
                    "commit-failed",
                    str(repo_root),
                    "referenced-by projections changed but no store commit was created",
                )
            )
        return committed
    except Exception as exc:
        issues.append(
            ReferencedByRefreshIssue(
                "error",
                "commit-failed",
                str(repo_root),
                f"could not commit referenced-by projections: {exc}",
            )
        )
        return False
