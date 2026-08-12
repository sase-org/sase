"""Off-thread catalog discovery for artifact-reference completion."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sase.artifact_refs import ArtifactRefContext, filter_artifact_ref_paths
from sase.ace.tui.widgets import _artifact_ref_entity_catalogs as entity_catalogs
from sase.ace.tui.widgets._artifact_ref_completion_menu import (
    ArtifactRefCompletionCatalog,
)
from sase.ace.tui.widgets._artifact_ref_completion_models import (
    ArtifactRefDocumentCandidate,
    ArtifactRefFileCandidate,
    ArtifactRefLoadedCandidates,
)


@dataclass(frozen=True, slots=True)
class ArtifactIndexCacheEntry:
    token: tuple[int, int] | None
    rows: tuple[object, ...]


_ARTIFACT_INDEX_CACHE: dict[Path, ArtifactIndexCacheEntry] = {}
_ArtifactIndexReader = Callable[[Path], tuple[object, ...]]
_DocumentCatalogLoader = Callable[
    [ArtifactRefContext],
    ArtifactRefLoadedCandidates[ArtifactRefDocumentCandidate],
]
_ArtifactFileCatalogLoader = Callable[
    [str | None, ArtifactRefContext],
    ArtifactRefLoadedCandidates[ArtifactRefFileCandidate],
]


def load_artifact_ref_completion_catalog(
    project: str | None,
    context: ArtifactRefContext,
    *,
    max_document_rows_per_kind: int,
    max_artifact_file_rows: int,
    read_artifact_index: _ArtifactIndexReader,
    load_document_candidates: _DocumentCatalogLoader | None = None,
    load_artifact_file_candidates: _ArtifactFileCatalogLoader | None = None,
) -> ArtifactRefCompletionCatalog:
    """Discover bounded payload rows; callers must run this off the UI thread."""
    documents = (
        load_document_candidate_catalog(
            context,
            max_rows_per_kind=max_document_rows_per_kind,
        )
        if load_document_candidates is None
        else load_document_candidates(context)
    )
    artifact_files = (
        load_artifact_file_candidate_catalog(
            project,
            context,
            max_rows=max_artifact_file_rows,
            read_artifact_index=read_artifact_index,
        )
        if load_artifact_file_candidates is None
        else load_artifact_file_candidates(project, context)
    )
    beads = entity_catalogs.load_bead_candidate_catalog(context)
    agents = entity_catalogs.load_agent_candidate_catalog(context)
    return ArtifactRefCompletionCatalog(
        project=project,
        kinds=tuple(context.known_kinds),
        documents=tuple(documents.rows),
        artifact_files=tuple(artifact_files.rows),
        beads=beads.rows,
        agents=agents.rows,
        kind_details=document_kind_details(context),
        truncated_payloads_by_kind=(
            *documents.truncated_by_kind,
            *artifact_files.truncated_by_kind,
            ("bead", beads.truncated),
            ("agent", agents.truncated),
        ),
    )


def document_kind_details(
    context: ArtifactRefContext,
) -> tuple[tuple[str, str], ...]:
    """Return one display detail per project-defined document kind."""
    details: list[tuple[str, str]] = []
    seen: set[str] = set()
    home = Path.home()
    for root in context.document_roots:
        folded = root.kind.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        path = Path(root.root)
        try:
            relative = path.relative_to(home)
        except ValueError:
            display = str(path)
        else:
            display = "~" if relative == Path(".") else f"~/{relative.as_posix()}"
        details.append((root.kind, f"document · {display}"))
    return tuple(details)


def load_document_candidate_catalog(
    context: ArtifactRefContext,
    *,
    max_rows_per_kind: int,
) -> ArtifactRefLoadedCandidates[ArtifactRefDocumentCandidate]:
    """Load each document role independently so large roles cannot starve peers."""
    corpora_by_role: dict[str, list[tuple[Path, str]]] = {}
    role_names: dict[str, str] = {}
    path_globs_by_role: dict[str, tuple[str, ...] | None] = {}
    for root in context.document_roots:
        folded = root.kind.casefold()
        role_names.setdefault(folded, root.kind)
        corpora_by_role.setdefault(folded, []).append((root.root, root.kind))
        path_globs_by_role.setdefault(folded, root.path_globs)
    if not corpora_by_role:
        return ArtifactRefLoadedCandidates(())

    from sase.plan_search.facade import SOURCE_REPO, search

    rows: list[ArtifactRefDocumentCandidate] = []
    truncated: list[tuple[str, int]] = []
    search_kinds = tuple(
        dict.fromkeys(
            kind
            for kind in (*context.known_kinds, "tale", "epic")
            if kind.casefold() != "prompt"
        )
    )
    for folded, role_corpora in corpora_by_role.items():
        role = role_names[folded]
        try:
            matches = search(
                source=SOURCE_REPO,
                sort="recent",
                limit=None,
                kinds=search_kinds,
                repo_root=role_corpora[0][0],
                document_corpora=role_corpora,
            )
        except Exception:
            continue
        role_rows: list[ArtifactRefDocumentCandidate] = []
        seen: set[str] = set()
        for match in matches:
            plan = match.plan
            key = plan.relpath.casefold()
            if key in seen:
                continue
            seen.add(key)
            role_rows.append(
                ArtifactRefDocumentCandidate(
                    kind=role,
                    payload=plan.relpath,
                    title=plan.title,
                    created_at=plan.created_at,
                )
            )
        filtered_rows = _filter_document_rows(
            role,
            role_rows,
            path_globs=path_globs_by_role.get(folded),
        )
        rows.extend(filtered_rows[:max_rows_per_kind])
        truncated.append(
            (
                folded,
                max(0, len(filtered_rows) - max_rows_per_kind),
            )
        )
    return ArtifactRefLoadedCandidates(tuple(rows), tuple(truncated))


def _filter_document_rows(
    role: str,
    rows: list[ArtifactRefDocumentCandidate],
    *,
    path_globs: tuple[str, ...] | None,
) -> tuple[ArtifactRefDocumentCandidate, ...]:
    if not rows:
        return ()
    try:
        filter_result = filter_artifact_ref_paths(
            role,
            tuple(row.payload for row in rows),
            path_globs=path_globs,
        )
    except Exception:
        return ()
    allowed_payloads = set(filter_result.allowed)
    return tuple(row for row in rows if row.payload in allowed_payloads)


def load_artifact_file_candidate_catalog(
    project: str | None,
    context: ArtifactRefContext,
    *,
    max_rows: int,
    read_artifact_index: _ArtifactIndexReader,
) -> ArtifactRefLoadedCandidates[ArtifactRefFileCandidate]:
    """Load bounded artifact-file rows and retain the exact eligible count."""
    rows = read_artifact_index(context.artifact_index_path)
    accepted_projects = accepted_project_names(project, context)
    filtered = [
        row
        for row in rows
        if getattr(row, "id", "")
        and (
            not accepted_projects
            or getattr(row, "project", None) is None
            or str(getattr(row, "project", "")).casefold() in accepted_projects
        )
    ]
    return ArtifactRefLoadedCandidates(
        tuple(
            ArtifactRefFileCandidate(
                payload=str(getattr(row, "id", "")),
                label=str(getattr(row, "label", getattr(row, "id", ""))),
                file_kind=str(getattr(row, "kind", "file")),
                created_at=str(getattr(row, "created_at", "") or ""),
            )
            for row in filtered[:max_rows]
        ),
        (("file", max(0, len(filtered) - max_rows)),) if filtered else (),
    )


def read_cached_artifact_index(index_path: Path) -> tuple[object, ...]:
    resolved = index_path.expanduser().resolve(strict=False)
    try:
        stat = resolved.stat()
        token: tuple[int, int] | None = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        token = None
    cached = _ARTIFACT_INDEX_CACHE.get(resolved)
    if cached is not None and cached.token == token:
        return cached.rows
    if token is None:
        rows: tuple[object, ...] = ()
    else:
        try:
            from sase.core.artifact_file_query_facade import query_artifact_files

            rows = tuple(query_artifact_files(resolved))
        except Exception:
            rows = ()
    _ARTIFACT_INDEX_CACHE[resolved] = ArtifactIndexCacheEntry(token, rows)
    return rows


def accepted_project_names(
    project: str | None,
    context: ArtifactRefContext,
) -> frozenset[str]:
    if project is None:
        return frozenset()
    folded = project.casefold()
    names = {folded}
    for candidate in context.projects:
        candidate_names = {
            candidate.name.casefold(),
            candidate.key.casefold(),
            *(alias.casefold() for alias in candidate.aliases),
        }
        if folded in candidate_names:
            names.update(candidate_names)
    return frozenset(names)
