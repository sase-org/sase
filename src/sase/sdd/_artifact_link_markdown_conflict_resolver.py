"""Resolve managed artifact-link Markdown block conflicts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sase.bead.conflict_resolver_git import (
    git_add,
    read_git_show,
    unmerged_stages,
    upstream_and_local_stages,
)
from sase.sdd._artifact_link_projection import (
    render_artifact_link_projection,
    safety_body,
)
from sase.sdd._artifact_link_store_support import canonicalize_artifact_link_ref
from sase.sdd.artifact_link_store import resolve_artifact_link_store
from sase.sdd.hosted_links import hosted_link_resolver

_LINKS_START = "<!-- sase:links:start -->"
_REFERENCED_BY_START = "<!-- sase:referenced-by:start -->"


@dataclass(frozen=True)
class _ArtifactLinkMarkdownConflictResolution:
    ok: bool
    message: str
    resolved_files: tuple[str, ...] = ()


def is_artifact_link_markdown_conflict_path(repo_root: Path, path: str) -> bool:
    """Return whether *path* has a managed artifact-link Markdown conflict."""

    if Path(path).suffix.casefold() not in {".md", ".markdown"}:
        return False
    try:
        stages = unmerged_stages(repo_root, path)
        return any(
            _has_managed_block(read_git_show(repo_root, stage, path))
            for stage in stages
        )
    except Exception:  # noqa: BLE001 - leave ambiguous paths to the generic conflict gate.
        return False


def resolve_artifact_link_markdown_conflicts(
    repo_root: Path,
    paths: tuple[str, ...],
) -> _ArtifactLinkMarkdownConflictResolution:
    """Resolve preclaimed Markdown conflicts by regenerating managed blocks."""

    if not paths:
        return _ArtifactLinkMarkdownConflictResolution(
            True,
            "no artifact-link Markdown conflicts",
        )

    prepared: list[tuple[str, str]] = []
    for path in sorted(paths):
        if not is_artifact_link_markdown_conflict_path(repo_root, path):
            return _ArtifactLinkMarkdownConflictResolution(
                False,
                "unsupported artifact-link Markdown conflicts: " + path,
            )
        result = _prepare_markdown_merge(repo_root, path)
        if not result.ok:
            return _ArtifactLinkMarkdownConflictResolution(False, result.message)
        assert result.content is not None
        prepared.append((path, result.content))

    for path, content in prepared:
        target = repo_root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    git_add(repo_root, [path for path, _content in prepared])
    resolved = tuple(path for path, _content in prepared)
    return _ArtifactLinkMarkdownConflictResolution(
        True,
        "resolved artifact-link Markdown conflicts: " + ", ".join(resolved),
        resolved,
    )


@dataclass(frozen=True)
class _PreparedMarkdownMerge:
    ok: bool
    message: str
    content: str | None = None


def _prepare_markdown_merge(repo_root: Path, path: str) -> _PreparedMarkdownMerge:
    stages = unmerged_stages(repo_root, path)
    if stages == frozenset({1, 2, 3}):
        base = read_git_show(repo_root, 1, path)
        upstream_stage, local_stage = upstream_and_local_stages(repo_root)
        current = read_git_show(repo_root, local_stage, path)
        theirs = read_git_show(repo_root, upstream_stage, path)
        if len({safety_body(base), safety_body(current), safety_body(theirs)}) != 1:
            return _PreparedMarkdownMerge(
                False,
                f"authored Markdown conflict remains in {path}",
            )
    elif stages == frozenset({2, 3}):
        upstream_stage, local_stage = upstream_and_local_stages(repo_root)
        current = read_git_show(repo_root, local_stage, path)
        theirs = read_git_show(repo_root, upstream_stage, path)
        if safety_body(current) != safety_body(theirs):
            return _PreparedMarkdownMerge(
                False,
                f"authored Markdown conflict remains in {path}",
            )
    else:
        return _PreparedMarkdownMerge(
            False,
            f"unsupported artifact-link Markdown conflict {path}: unexpected stages "
            + ",".join(str(stage) for stage in sorted(stages)),
        )

    artifact_ref = _artifact_ref_for_markdown(repo_root, path)
    if artifact_ref is None:
        return _PreparedMarkdownMerge(
            False,
            f"could not map artifact-link Markdown conflict to an artifact ref: {path}",
        )

    try:
        store = resolve_artifact_link_store(cwd=repo_root)
        rows = store.load_artifact_rows(artifact_ref)
        resolver = (
            hosted_link_resolver(store.sdd_store)
            if store.sdd_store is not None
            else _NullHostedLinkResolver()
        )
        rendered = render_artifact_link_projection(
            current,
            artifact_id=artifact_ref,
            rows=rows,
            store=cast(Any, store.sdd_store or _ProjectionStoreAdapter(store)),
            resolver=resolver,
        )
    except Exception as exc:  # noqa: BLE001 - fail closed and leave stages intact.
        return _PreparedMarkdownMerge(
            False,
            f"artifact-link Markdown conflict resolution failed for {path}: {exc}",
        )
    if safety_body(rendered) != safety_body(current):
        return _PreparedMarkdownMerge(
            False,
            f"artifact-link Markdown conflict resolver changed authored text: {path}",
        )
    return _PreparedMarkdownMerge(True, "resolved", rendered)


def _artifact_ref_for_markdown(repo_root: Path, path: str) -> str | None:
    try:
        store = resolve_artifact_link_store(cwd=repo_root)
    except Exception:
        return None
    absolute = (repo_root / path).expanduser().resolve(strict=False)
    for kind, root in store.sidecar_roots.items():
        resolved_root = root.expanduser().resolve(strict=False)
        try:
            relpath = absolute.relative_to(resolved_root).as_posix()
        except ValueError:
            continue
        if not relpath:
            continue
        return canonicalize_artifact_link_ref(f"{kind}:{relpath}")
    return None


def _has_managed_block(text: str) -> bool:
    return _LINKS_START in text or _REFERENCED_BY_START in text


class _NullHostedLinkResolver:
    def agent_url(self, _agent_name: str) -> None:
        return None

    def bead_url(self, _bead_id: str) -> None:
        return None

    def commit_url(self, _sha: str) -> None:
        return None

    def plan_url(self, _plan_ref: str) -> None:
        return None

    def blob_url_for_repository(
        self,
        _repo_root: Path,
        _branch: str,
        _repo_relpath: str,
    ) -> None:
        return None


class _ProjectionStoreAdapter:
    def __init__(self, store: Any) -> None:
        self._store = store

    def repo_root_for_kind(self, kind: str) -> Path:
        root = self._store.sidecar_roots.get(kind)
        if root is None:
            raise KeyError(kind)
        return Path(root)


__all__ = [
    "is_artifact_link_markdown_conflict_path",
    "resolve_artifact_link_markdown_conflicts",
]
