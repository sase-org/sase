"""Reconcile Referenced By projections in artifact repositories."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from sase.agents_sync.io import atomic_write_json
from sase.agents_sync.referenced_by_outbox_models import ReferencedByOutboxItem
from sase.core.rust import require_rust_binding
from sase.sdd.artifact_link_store import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    ArtifactLinkStore,
    artifact_links_enabled,
)
from sase.sdd.hosted_links import hosted_link_resolver, resolve_hosted_branch
from sase.sdd.referenced_by_index import (
    merge_referenced_by_rows,
    read_referenced_by_index,
    referenced_by_index_path,
    referenced_by_index_schema_version,
)

if TYPE_CHECKING:
    from sase.sdd.store import SddStore

_RefreshSeverity = Literal["error", "warning"]
_CURATED_ORIGINS = frozenset({"manual", "migrated"})
_AUTOMATIC_ORIGINS = frozenset({"prompt_ref", "read"})
_MAX_RENDERED_ROWS = 50


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

    if artifact_links_enabled():
        return _refresh_artifact_links(store, role=role, requests=requests, write=write)

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


def _refresh_artifact_links(
    store: SddStore,
    *,
    role: str,
    requests: tuple[ReferencedByOutboxItem, ...],
    write: bool,
) -> _ReferencedByRefreshReport:
    """Refresh v2 artifact-link truth and Markdown projections."""

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
            op="sdd.artifact_links.refresh",
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
        return _refresh_artifact_links_locked(
            store,
            role=role,
            requests=requests,
            write=write,
        )


def _refresh_artifact_links_locked(
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
                _ReferencedByRefreshIssue(
                    "error",
                    "artifact-missing",
                    group[0].repo_relpath,
                    f"artifact document is missing: {group[0].repo_relpath}",
                )
            )
            continue
        try:
            document = _artifact_projection_document(asset)
            is_companion = document != asset
            current = (
                document.read_text(encoding="utf-8")
                if document.exists()
                else _companion_seed(asset, document)
            )
            existing_rows = link_store.load_artifact_rows(artifact_id)
            incoming_rows = tuple(_artifact_link_row(item) for item in group)
            preview_rows = _preview_link_rows(existing_rows, incoming_rows)
            updated = _render_artifact_link_projection(
                current,
                artifact_id=artifact_id,
                rows=preview_rows,
                store=store,
                resolver=resolver,
                companion=is_companion,
            )
            if updated != current and _safety_body(updated) != _safety_body(current):
                issues.append(
                    _ReferencedByRefreshIssue(
                        "error",
                        "managed-block-safety",
                        group[0].repo_relpath,
                        "artifact-link refresh would change text outside managed blocks",
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

        index_changed = _link_rows_changed(existing_rows, preview_rows)
        document_changed = updated != current
        if not index_changed and not document_changed:
            continue
        actions.append(
            _ReferencedByRefreshAction(
                path=_relative(repo_root, document),
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
                updated = _render_artifact_link_projection(
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
                    "Update artifact link projections",
                    paths=changed_paths,
                    push_after_commit="async",
                    already_locked=True,
                    cause="artifact_links",
                )
            )
            if not committed:
                issues.append(
                    _ReferencedByRefreshIssue(
                        "error",
                        "commit-failed",
                        str(repo_root),
                        "artifact-link projections changed but no store commit was created",
                    )
                )
        except Exception as exc:
            issues.append(
                _ReferencedByRefreshIssue(
                    "error",
                    "commit-failed",
                    str(repo_root),
                    f"could not commit artifact-link projections: {exc}",
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


def _artifact_projection_document(asset: Path) -> Path:
    suffix = asset.suffix.casefold()
    if suffix in {".md", ".markdown"}:
        return asset
    companion = require_rust_binding("companion_md_path")(str(asset))
    return Path(str(companion["path"])).expanduser().resolve(strict=False)


def _companion_seed(asset: Path, document: Path) -> str:
    if document == asset:
        return ""
    rel_asset = _relative(document.parent, asset)
    title = asset.name.replace("\n", " ")
    suffix = asset.suffix.casefold()
    if suffix in {".apng", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}:
        preview = f"![{title}](./{rel_asset})"
        kind = "image"
    else:
        preview = f"[{title}](./{rel_asset})"
        kind = "artifact"
    return (
        f"# {title}\n\n"
        f"{preview}\n\n"
        f"_Typed links for this {kind}. This file is generated; do not hand-edit._\n"
    )


def _artifact_link_row(item: ReferencedByOutboxItem) -> dict[str, object]:
    target_ref = item.canonical_ref or item.artifact_id
    description = item.description.strip() or f"{item.origin} reference to {target_ref}"
    return {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "source_ref": f"agent:{item.global_agent}",
        "relation": item.relation,
        "target_ref": target_ref,
        "description": description[:240],
        "origin": item.origin,
        "created_by": item.global_agent,
        "created_at": _item_created_at(item),
        "uses": item.uses,
    }


def _item_created_at(item: ReferencedByOutboxItem) -> str:
    timestamp = item.created_at or item.updated_at
    if timestamp > 0:
        return (
            datetime.fromtimestamp(timestamp, tz=UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
    return f"{item.published_date}T00:00:00Z"


def _preview_link_rows(
    existing_rows: Sequence[Mapping[str, Any]],
    incoming_rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    rows = [dict(row) for row in existing_rows]
    upsert = require_rust_binding("artifact_link_upsert_row")
    for incoming in incoming_rows:
        outcome = upsert(rows, dict(incoming))
        rows = [dict(row) for row in outcome["rows"]]
    return tuple(rows)


def _link_rows_changed(
    existing_rows: Sequence[Mapping[str, Any]],
    preview_rows: Sequence[Mapping[str, Any]],
) -> bool:
    return [dict(row) for row in existing_rows] != [dict(row) for row in preview_rows]


def _render_artifact_link_projection(
    current: str,
    *,
    artifact_id: str,
    rows: Sequence[Mapping[str, Any]],
    store: SddStore,
    resolver: Any,
    companion: bool = False,
) -> str:
    links_rows = _table_rows_for_origins(
        artifact_id,
        rows,
        origins=_CURATED_ORIGINS,
        store=store,
        resolver=resolver,
        include_uses=False,
    )
    automatic_rows = _table_rows_for_origins(
        artifact_id,
        rows,
        origins=_AUTOMATIC_ORIGINS,
        store=store,
        resolver=resolver,
        include_uses=True,
    )
    links_table = _links_table(links_rows, automatic_count=len(automatic_rows))
    if companion:
        return _render_companion_projection(
            current,
            links_table=links_table,
            referenced_by_table=_referenced_by_table(automatic_rows),
        )
    updated = str(require_rust_binding("links_block_upsert")(current, links_table))
    referenced_by_table = _referenced_by_table(automatic_rows)
    return str(
        require_rust_binding("referenced_by_block_upsert")(
            updated,
            referenced_by_table,
        )
    )


def _render_companion_projection(
    current: str,
    *,
    links_table: Mapping[str, object],
    referenced_by_table: Mapping[str, object],
) -> str:
    body = _strip_managed_link_blocks(current).rstrip()
    blocks: list[str] = []
    if links_table.get("rows"):
        blocks.append(
            _managed_block(
                "links", str(require_rust_binding("links_block_render")(links_table))
            )
        )
    if referenced_by_table.get("rows"):
        blocks.append(
            _managed_block(
                "referenced-by",
                str(
                    require_rust_binding("referenced_by_block_render")(
                        referenced_by_table
                    )
                ),
            )
        )
    if not blocks:
        return f"{body}\n" if body else ""
    return f"{body}\n\n" + "\n\n".join(blocks) + "\n"


def _managed_block(name: str, body: str) -> str:
    return f"<!-- sase:{name}:start -->\n\n{body}\n\n<!-- sase:{name}:end -->"


def _table_rows_for_origins(
    artifact_id: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    origins: frozenset[str],
    store: SddStore,
    resolver: Any,
    include_uses: bool,
) -> tuple[dict[str, object], ...]:
    rendered: list[dict[str, object]] = []
    for row in rows:
        if str(row.get("origin") or "") not in origins:
            continue
        projected = _project_row(
            artifact_id,
            row,
            store=store,
            resolver=resolver,
            include_uses=include_uses,
        )
        if projected is not None:
            rendered.append(projected)
    rendered.sort(
        key=lambda item: (
            str(cast(Mapping[str, object], item["values"]).get("relation") or ""),
            str(cast(Mapping[str, object], item["values"]).get("artifact") or ""),
        )
    )
    return tuple(rendered)


def _project_row(
    artifact_id: str,
    row: Mapping[str, Any],
    *,
    store: SddStore,
    resolver: Any,
    include_uses: bool,
) -> dict[str, object] | None:
    source = str(row.get("source_ref") or "")
    target = str(row.get("target_ref") or "")
    if artifact_id == source:
        other = target
        this_is_source = True
    elif artifact_id == target:
        other = source
        this_is_source = False
    else:
        return None
    relation = str(
        require_rust_binding("artifact_relation_label")(
            str(row.get("relation") or ""),
            this_is_source,
        )
    )
    values = {
        "relation": relation,
        "artifact": other,
        "why": str(row.get("description") or ""),
    }
    if include_uses:
        values["uses"] = str(row.get("uses") or "0")
    link_targets: dict[str, str] = {}
    url = _artifact_url(other, store=store, resolver=resolver)
    if url:
        link_targets["artifact"] = url
    return {"values": values, "link_targets": link_targets}


def _links_table(
    rows: Sequence[Mapping[str, object]],
    *,
    automatic_count: int,
) -> dict[str, object]:
    table_rows, omitted = _cap_rows(rows)
    table: dict[str, object] = {
        "schema_version": int(
            require_rust_binding("referenced_by_wire_schema_version")()
        ),
        "columns": [
            {"key": "relation", "label": "Relation", "numeric": False},
            {"key": "artifact", "label": "Artifact", "numeric": False},
            {"key": "why", "label": "Why", "numeric": False},
        ],
        "rows": table_rows,
        "omitted": omitted,
    }
    if table_rows and automatic_count > 0:
        table["pointer"] = (
            f"Plus {automatic_count} automatic references — see "
            "[Referenced By](#referenced-by)."
        )
    return table


def _referenced_by_table(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    table_rows, omitted = _cap_rows(rows)
    return {
        "schema_version": int(
            require_rust_binding("referenced_by_wire_schema_version")()
        ),
        "columns": [
            {"key": "relation", "label": "Relation", "numeric": False},
            {"key": "artifact", "label": "Artifact", "numeric": False},
            {"key": "why", "label": "Why", "numeric": False},
            {"key": "uses", "label": "Uses", "numeric": True},
        ],
        "rows": table_rows,
        "omitted": omitted,
    }


def _cap_rows(
    rows: Sequence[Mapping[str, object]],
) -> tuple[tuple[Mapping[str, object], ...], int]:
    kept = tuple(rows[:_MAX_RENDERED_ROWS])
    return kept, max(0, len(rows) - len(kept))


def _artifact_url(artifact_ref: str, *, store: SddStore, resolver: Any) -> str | None:
    kind, separator, value = artifact_ref.partition(":")
    if not separator:
        return None
    if kind == "agent":
        return resolver.agent_url(value)
    if kind == "bead":
        return resolver.bead_url(value)
    if kind == "commit":
        return resolver.commit_url(value)
    if kind == "plan":
        return resolver.plan_url(artifact_ref)
    if kind == "stitch":
        return resolver.commit_url(value)
    return _document_url(kind, value, store=store, resolver=resolver)


def _document_url(
    kind: str,
    repo_relpath: str,
    *,
    store: SddStore,
    resolver: Any,
) -> str | None:
    try:
        repo_root = store.repo_root_for_kind(kind).expanduser().resolve(strict=False)
    except Exception:
        return None
    branch = resolve_hosted_branch(repo_root)
    if branch is None:
        return None
    try:
        return resolver.blob_url_for_repository(repo_root, branch, repo_relpath)
    except Exception:
        return None


def _strip_managed_link_blocks(text: str) -> str:
    without_links = str(require_rust_binding("links_block_remove")(text))
    return str(require_rust_binding("referenced_by_block_remove")(without_links))


def _safety_body(text: str) -> str:
    stripped = _strip_managed_link_blocks(text)
    while "\n\n\n" in stripped:
        stripped = stripped.replace("\n\n\n", "\n\n")
    return stripped


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
