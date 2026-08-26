"""Consume artifact path renames into durable artifact-link indexes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agents_sync.io import atomic_write_json
from sase.sdd._artifact_link_store_support import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    canonicalize_artifact_link_ref,
    is_projected_row,
    kind_of_ref,
    read_artifact_link_index,
    row_touches,
    sidecar_index_path,
    unique_rows,
    validate_artifact_link_row,
)
from sase.sdd._git import run_sdd_git
from sase.sdd.referenced_by_index import REFERENCED_BY_LINKS_DIR


@dataclass(frozen=True)
class _ArtifactLinkRename:
    """One sidecar artifact rename expressed in canonical artifact refs."""

    old_ref: str
    new_ref: str


@dataclass(frozen=True)
class _ArtifactLinkRenameReport:
    """Outcome of applying artifact-link rename rewrites."""

    renames: tuple[_ArtifactLinkRename, ...] = ()
    changed_indexes: tuple[Path, ...] = ()
    removed_indexes: tuple[Path, ...] = ()
    rewritten_rows: int = 0
    aggregate_changed: bool = False

    @property
    def changed_paths(self) -> tuple[Path, ...]:
        return tuple(dict.fromkeys((*self.changed_indexes, *self.removed_indexes)))

    @property
    def changed(self) -> bool:
        return bool(
            self.changed_indexes
            or self.removed_indexes
            or self.rewritten_rows
            or self.aggregate_changed
        )


def consume_recent_artifact_renames(
    store: Any,
    *,
    repo_root: Path,
    kind: str,
) -> _ArtifactLinkRenameReport:
    """Rewrite link indexes for renames introduced by the current HEAD commit."""

    renames = tuple(_current_head_renames(repo_root, kind=kind))
    return _apply_artifact_renames(store, renames, sidecar_roots=(repo_root,))


def repair_historical_artifact_renames(
    store: Any,
    refs: Iterable[str],
) -> _ArtifactLinkRenameReport:
    """Repair stale refs when a sidecar git rename explains the drift."""

    by_kind: dict[str, dict[str, str]] = {}
    resolved: list[_ArtifactLinkRename] = []
    for raw_ref in refs:
        try:
            old_ref = canonicalize_artifact_link_ref(raw_ref)
        except (TypeError, ValueError, RuntimeError):
            continue
        kind = kind_of_ref(old_ref)
        if kind not in {"plan", "research"}:
            continue
        root = store.sidecar_roots.get(kind)
        if root is None or not root.is_dir():
            continue
        history = by_kind.setdefault(
            kind,
            _historical_rename_map(root, kind=kind),
        )
        new_ref = _follow_rename_chain(old_ref, history, root)
        if new_ref is None:
            continue
        resolved.append(_ArtifactLinkRename(old_ref=old_ref, new_ref=new_ref))
    return _apply_artifact_renames(store, tuple(dict.fromkeys(resolved)))


def _apply_artifact_renames(
    store: Any,
    renames: Iterable[_ArtifactLinkRename],
    *,
    sidecar_roots: Iterable[Path] | None = None,
) -> _ArtifactLinkRenameReport:
    """Apply artifact ref rewrites across sidecar indexes and the aggregate."""

    ordered = tuple(
        _ArtifactLinkRename(
            old_ref=canonicalize_artifact_link_ref(rename.old_ref),
            new_ref=canonicalize_artifact_link_ref(rename.new_ref),
        )
        for rename in renames
        if rename.old_ref != rename.new_ref
    )
    if not ordered:
        return _ArtifactLinkRenameReport()
    mapping = {rename.old_ref: rename.new_ref for rename in ordered}
    allowed_roots = (
        None
        if sidecar_roots is None
        else {root.expanduser().resolve(strict=False) for root in sidecar_roots}
    )
    changed_indexes: list[Path] = []
    removed_indexes: list[Path] = []
    rewritten_rows = 0
    for kind, root in store.sidecar_roots.items():
        resolved_root = root.expanduser().resolve(strict=False)
        if allowed_roots is not None and resolved_root not in allowed_roots:
            continue
        changed = _rewrite_sidecar_indexes(root, mapping, kind=kind)
        changed_indexes.extend(changed.changed_indexes)
        removed_indexes.extend(changed.removed_indexes)
        rewritten_rows += changed.rewritten_rows

    aggregate_changed = _rewrite_aggregate(store, mapping)
    if changed_indexes or removed_indexes:
        # Sidecar rows are authoritative for document-shaped refs; rebuild before
        # the final aggregate rewrite so aggregate-only rows can still follow.
        store.rebuild_aggregate()
        aggregate_changed = _rewrite_aggregate(store, mapping) or aggregate_changed
    return _ArtifactLinkRenameReport(
        renames=ordered,
        changed_indexes=tuple(dict.fromkeys(changed_indexes)),
        removed_indexes=tuple(dict.fromkeys(removed_indexes)),
        rewritten_rows=rewritten_rows,
        aggregate_changed=aggregate_changed,
    )


@dataclass(frozen=True)
class _SidecarRewriteReport:
    changed_indexes: tuple[Path, ...] = ()
    removed_indexes: tuple[Path, ...] = ()
    rewritten_rows: int = 0


def _rewrite_sidecar_indexes(
    repo_root: Path,
    mapping: Mapping[str, str],
    *,
    kind: str,
) -> _SidecarRewriteReport:
    root = repo_root.expanduser().resolve(strict=False)
    links_root = root / REFERENCED_BY_LINKS_DIR
    if not links_root.is_dir():
        return _SidecarRewriteReport()
    pending: dict[Path, list[dict[str, Any]]] = {}
    pending_refs: dict[Path, str] = {}
    changed_sources: set[Path] = set()
    moved_sources: set[Path] = set()
    rewritten_rows = 0
    for path in sorted(links_root.rglob("*.json")):
        relative = path.relative_to(links_root).as_posix()
        if not relative.endswith(".json"):
            continue
        fallback_ref = f"{kind}:{relative[: -len('.json')]}"
        try:
            index = read_artifact_link_index(path, artifact_ref=fallback_ref)
        except Exception:  # noqa: BLE001 - health checks report malformed indexes.
            continue
        old_artifact_ref = str(index["artifact_ref"])
        new_artifact_ref = _rewrite_ref(old_artifact_ref, mapping)
        rows: list[dict[str, Any]] = []
        changed = new_artifact_ref != old_artifact_ref
        for raw in index.get("rows", []):
            row = dict(raw)
            rewritten = _rewrite_row(row, mapping)
            if rewritten is None:
                if row != rewritten:
                    changed = True
                continue
            if rewritten != row:
                changed = True
                rewritten_rows += 1
            rows.append(rewritten)
        if not changed:
            continue
        target_path = sidecar_index_path(root, new_artifact_ref)
        pending.setdefault(target_path, []).extend(rows)
        pending_refs[target_path] = new_artifact_ref
        changed_sources.add(path)
        if target_path != path:
            moved_sources.add(path)

    changed_indexes: list[Path] = []
    removed_indexes: list[Path] = []
    for target_path, rows in sorted(
        pending.items(), key=lambda item: item[0].as_posix()
    ):
        artifact_ref = pending_refs[target_path]
        base_rows: list[dict[str, Any]] = []
        if target_path.is_file() and target_path not in changed_sources:
            try:
                base = read_artifact_link_index(target_path, artifact_ref=artifact_ref)
                base_rows = [dict(row) for row in base.get("rows", [])]
            except Exception:  # noqa: BLE001 - prefer writing the validated repair.
                base_rows = []
        desired = {
            "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
            "artifact_ref": artifact_ref,
            "rows": unique_rows((*base_rows, *rows)),
        }
        current = None
        if target_path.is_file():
            try:
                current = read_artifact_link_index(
                    target_path, artifact_ref=artifact_ref
                )
            except Exception:  # noqa: BLE001 - write a repaired index below.
                current = None
        if current != desired:
            atomic_write_json(target_path, desired)
            changed_indexes.append(target_path)

    for path in sorted(moved_sources):
        if path in pending:
            continue
        if path.exists():
            path.unlink()
            removed_indexes.append(path)

    return _SidecarRewriteReport(
        changed_indexes=tuple(dict.fromkeys(changed_indexes)),
        removed_indexes=tuple(dict.fromkeys(removed_indexes)),
        rewritten_rows=rewritten_rows,
    )


def _rewrite_aggregate(store: Any, mapping: Mapping[str, str]) -> bool:
    current = store.load_aggregate()
    rows = current.get("rows")
    if not isinstance(rows, list):
        return False
    rewritten_rows: list[dict[str, Any]] = []
    changed = False
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        if is_projected_row(raw):
            # Recomputed on the next rebuild, never rewritten: a rewrite here
            # would persist a repair the source fact does not support.
            rewritten_rows.append(dict(raw))
            continue
        rewritten = _rewrite_row(raw, mapping)
        if rewritten is None:
            changed = True
            continue
        if rewritten != raw:
            changed = True
        rewritten_rows.append(rewritten)
    if not changed:
        return False
    store._write_aggregate(  # noqa: SLF001 - package-private repair primitive.
        {
            "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
            "rows": unique_rows(rewritten_rows),
        }
    )
    return True


def _rewrite_row(
    row: Mapping[str, Any],
    mapping: Mapping[str, str],
) -> dict[str, Any] | None:
    rewritten = dict(row)
    for key in ("source_ref", "target_ref"):
        value = str(rewritten.get(key) or "")
        if value in mapping:
            rewritten[key] = mapping[value]
    if rewritten.get("source_ref") == rewritten.get("target_ref"):
        return None
    try:
        return validate_artifact_link_row(rewritten)
    except (TypeError, ValueError, RuntimeError):
        return None


def _rewrite_ref(ref: str, mapping: Mapping[str, str]) -> str:
    return mapping.get(ref, ref)


def _current_head_renames(
    repo_root: Path, *, kind: str
) -> tuple[_ArtifactLinkRename, ...]:
    result = run_sdd_git(
        [
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-status",
            "-r",
            "-M",
            "HEAD",
            "--",
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        op="sdd.artifact_links.renames",
    )
    if result.returncode != 0:
        return ()
    return _parse_name_status_renames(str(result.stdout or ""), kind=kind)


def _historical_rename_map(repo_root: Path, *, kind: str) -> dict[str, str]:
    result = run_sdd_git(
        [
            "log",
            "--all",
            "--format=",
            "--name-status",
            "--find-renames",
            "-M",
            "--diff-filter=R",
            "--",
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        op="sdd.artifact_links.rename_history",
    )
    if result.returncode != 0:
        return {}
    mapping: dict[str, str] = {}
    for rename in _parse_name_status_renames(str(result.stdout or ""), kind=kind):
        mapping.setdefault(rename.old_ref, rename.new_ref)
    return mapping


def _parse_name_status_renames(
    output: str,
    *,
    kind: str,
) -> tuple[_ArtifactLinkRename, ...]:
    renames: list[_ArtifactLinkRename] = []
    for raw_line in output.splitlines():
        if not raw_line.startswith("R"):
            continue
        parts = raw_line.split("\t")
        if len(parts) != 3:
            continue
        old_ref = _artifact_ref_for_sidecar_path(kind, parts[1])
        new_ref = _artifact_ref_for_sidecar_path(kind, parts[2])
        if old_ref is None or new_ref is None or old_ref == new_ref:
            continue
        renames.append(_ArtifactLinkRename(old_ref=old_ref, new_ref=new_ref))
    return tuple(renames)


def _artifact_ref_for_sidecar_path(kind: str, relpath: str) -> str | None:
    path = Path(relpath)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    if path.parts[:1] == (REFERENCED_BY_LINKS_DIR,):
        return None
    return canonicalize_artifact_link_ref(f"{kind}:{path.as_posix()}")


def _follow_rename_chain(
    old_ref: str,
    history: Mapping[str, str],
    repo_root: Path,
) -> str | None:
    seen = {old_ref}
    current = old_ref
    for _ in range(20):
        candidate = history.get(current)
        if candidate is None or candidate in seen:
            return None
        seen.add(candidate)
        root = repo_root.expanduser().resolve(strict=False)
        _kind, _sep, relpath = candidate.partition(":")
        if relpath and (root / relpath).is_file():
            return candidate
        current = candidate
    return None


__all__ = [
    "consume_recent_artifact_renames",
    "repair_historical_artifact_renames",
]
