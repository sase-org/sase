"""Reconcile Referenced By projections in artifact repositories."""

from __future__ import annotations

from collections import defaultdict
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sase.agents_sync.io import atomic_write_json
from sase.agents_sync.referenced_by_outbox_models import ReferencedByOutboxItem
from sase.core.rust import require_rust_binding
from sase.sdd.referenced_by_index import (
    merge_referenced_by_rows,
    read_referenced_by_index,
    referenced_by_index_path,
)

if TYPE_CHECKING:
    from sase.sdd.store import SddStore

_RefreshSeverity = Literal["error", "warning"]


@dataclass(frozen=True, slots=True)
class _ReferencedByRefreshIssue:
    """One actionable Referenced By refresh diagnostic."""

    severity: _RefreshSeverity
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class _ReferencedByRefreshAction:
    """One artifact document whose managed projection differs."""

    path: str
    artifact_id: str
    rows: int


@dataclass(frozen=True, slots=True)
class _ReferencedByRefreshReport:
    """Complete dry-run or write result for one refresh invocation."""

    root: Path
    role: str
    write: bool
    scanned: int
    actions: tuple[_ReferencedByRefreshAction, ...]
    issues: tuple[_ReferencedByRefreshIssue, ...]
    changed_files: tuple[str, ...]
    committed: bool

    @property
    def errors(self) -> tuple[_ReferencedByRefreshIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[_ReferencedByRefreshIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    @property
    def ok(self) -> bool:
        return not self.errors


def refresh_referenced_by(
    store: SddStore,
    *,
    role: str,
    requests: tuple[ReferencedByOutboxItem, ...],
    write: bool = False,
) -> _ReferencedByRefreshReport:
    """Refresh managed Referenced By blocks for one sidecar role."""

    repo_root = store.repo_root_for_kind(role).resolve(strict=False)
    if not repo_root.is_dir():
        return _report_with_error(
            repo_root,
            role,
            write,
            "root-missing",
            str(repo_root),
            f"artifact repository root does not exist: {repo_root}",
        )
    from sase.sdd._git_contention import store_git_write_lock

    lock = (
        store_git_write_lock(
            repo_root,
            op="sdd.referenced_by.refresh",
            mutates_worktree=True,
        )
        if write
        else nullcontext(True)
    )
    with lock as acquired:
        if not acquired:
            return _report_with_error(
                repo_root,
                role,
                write,
                "lock-busy",
                str(repo_root),
                "artifact repository write lock is busy",
            )
        return _refresh_locked(store, role=role, requests=requests, write=write)


def _refresh_locked(
    store: SddStore,
    *,
    role: str,
    requests: tuple[ReferencedByOutboxItem, ...],
    write: bool,
) -> _ReferencedByRefreshReport:
    repo_root = store.repo_root_for_kind(role).resolve(strict=False)
    issues: list[_ReferencedByRefreshIssue] = []
    if write:
        pull_issue = _pull_rebase_if_remote(repo_root)
        if pull_issue is not None:
            return _ReferencedByRefreshReport(
                root=repo_root,
                role=role,
                write=write,
                scanned=0,
                actions=(),
                issues=(pull_issue,),
                changed_files=(),
                committed=False,
            )

    actions: list[_ReferencedByRefreshAction] = []
    changed_paths: list[Path] = []
    grouped: dict[str, list[ReferencedByOutboxItem]] = defaultdict(list)
    for item in requests:
        grouped[item.artifact_id].append(item)

    for artifact_id, group in sorted(grouped.items()):
        document = (repo_root / group[0].repo_relpath).resolve(strict=False)
        if not document.is_relative_to(repo_root) or not document.is_file():
            issues.append(
                _ReferencedByRefreshIssue(
                    "error",
                    "artifact-missing",
                    group[0].repo_relpath,
                    f"artifact document is missing: {group[0].repo_relpath}",
                )
            )
            continue
        index_path = referenced_by_index_path(repo_root, artifact_id)
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
                    _ReferencedByRefreshIssue(
                        "error",
                        "managed-block-safety",
                        group[0].repo_relpath,
                        "referenced-by refresh would change text outside the managed block",
                    )
                )
                continue
        except Exception as exc:
            issues.append(
                _ReferencedByRefreshIssue(
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
            _ReferencedByRefreshAction(
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

    committed = False
    if write and changed_paths:
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
                    _ReferencedByRefreshIssue(
                        "error",
                        "commit-failed",
                        str(repo_root),
                        "referenced-by projections changed but no store commit was created",
                    )
                )
        except Exception as exc:
            issues.append(
                _ReferencedByRefreshIssue(
                    "error",
                    "commit-failed",
                    str(repo_root),
                    f"could not commit referenced-by projections: {exc}",
                )
            )

    return _ReferencedByRefreshReport(
        root=repo_root,
        role=role,
        write=write,
        scanned=len(grouped),
        actions=tuple(actions),
        issues=tuple(issues),
        changed_files=tuple(_relative(repo_root, path) for path in changed_paths),
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


def _pull_rebase_if_remote(repo_root: Path) -> _ReferencedByRefreshIssue | None:
    from sase.sdd._git import run_sdd_git
    from sase.sdd._git_contention import run_sdd_git_write

    remote = run_sdd_git(
        ["remote", "get-url", "origin"],
        cwd=repo_root,
        capture_output=True,
        check=False,
        op="sdd.referenced_by.remote",
    )
    if remote.returncode != 0 or not remote.stdout.strip():
        return None
    result = run_sdd_git_write(
        ["pull", "--rebase"],
        cwd=repo_root,
        capture_output=True,
        check=False,
        op="sdd.referenced_by.pull",
    )
    if result.returncode == 0:
        return None
    detail = result.stderr.strip() or result.stdout.strip() or "git pull failed"
    return _ReferencedByRefreshIssue(
        "error",
        "pull-failed",
        str(repo_root),
        detail,
    )


def _report_with_error(
    root: Path,
    role: str,
    write: bool,
    code: str,
    path: str,
    message: str,
) -> _ReferencedByRefreshReport:
    return _ReferencedByRefreshReport(
        root=root,
        role=role,
        write=write,
        scanned=0,
        actions=(),
        issues=(_ReferencedByRefreshIssue("error", code, path, message),),
        changed_files=(),
        committed=False,
    )


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


__all__ = ["refresh_referenced_by"]
