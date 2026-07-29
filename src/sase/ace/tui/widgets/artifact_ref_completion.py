"""Pure artifact-reference completion plus off-thread catalog discovery."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from typing import Literal

from sase.artifact_refs import (
    BUILTIN_ARTIFACT_REF_KINDS,
    ArtifactRefContext,
    at_reference_context,
    at_reference_menu,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_path_inventory import PromptPathRow


ARTIFACT_REF_COMPLETION_KIND = "artifact_ref"
ArtifactRefCompletionStage = Literal["kind", "payload"]
ArtifactRefPayloadSource = Literal[
    "document",
    "file",
    "chat",
    "commit",
    "bug",
]

_MAX_DOCUMENT_ROWS = 500
_MAX_ARTIFACT_FILE_ROWS = 500
_MAX_CHAT_SCAN_ROWS = 1000
_MAX_CHAT_ROWS = 500


@dataclass(frozen=True, slots=True)
class ArtifactRefCompletionContext:
    """Artifact-reference token and replacement span at one cursor."""

    replacement_start: int
    replacement_end: int
    stage: ArtifactRefCompletionStage
    partial_kind: str
    partial_payload: str
    kind: str | None
    panel_title: str
    path_directory: str | None = None
    path_partial: str = ""
    query_start: int = 0
    query_end: int = 0
    wire: dict[str, object] | None = None

    @property
    def prefix(self) -> str:
        """Return the stage-local text used to filter candidates."""
        return self.partial_kind if self.stage == "kind" else self.partial_payload


@dataclass(frozen=True, slots=True)
class ArtifactRefKindCompletionMetadata:
    """Metadata for one builtin or project-defined artifact kind."""

    kind: str
    builtin: bool

    @property
    def source_label(self) -> str:
        return "builtin" if self.builtin else "document"


@dataclass(frozen=True, slots=True)
class ArtifactRefPayloadCompletionMetadata:
    """Metadata rendered beside one artifact payload candidate."""

    kind: str
    payload: str
    source: ArtifactRefPayloadSource
    label: str = ""
    detail: str = ""
    age: str = ""


@dataclass(frozen=True, slots=True)
class AtReferenceFileCompletionMetadata:
    """Metadata for one local path row in the shared ``@`` menu."""

    is_dir: bool
    directory: str


@dataclass(frozen=True, slots=True)
class AtReferenceLoadingCompletionMetadata:
    """Non-selectable row shown while a local path snapshot is cold."""


@dataclass(frozen=True, slots=True)
class _ArtifactRefDocumentCandidate:
    kind: str
    payload: str
    title: str = ""
    created_at: str = ""


@dataclass(frozen=True, slots=True)
class _ArtifactRefFileCandidate:
    payload: str
    label: str
    file_kind: str
    created_at: str = ""


@dataclass(frozen=True, slots=True)
class _ArtifactRefChatCandidate:
    payload: str
    modified_at: float


@dataclass(frozen=True, slots=True)
class ArtifactRefCommitCandidate:
    repo: str
    sha: str
    subject: str = ""
    timestamp: int = 0

    @property
    def payload(self) -> str:
        return f"{self.repo}@{self.sha}"


@dataclass(frozen=True, slots=True)
class ArtifactRefBugCandidate:
    project: str
    number: int
    title: str = ""
    updated_at: str = ""

    @property
    def payload(self) -> str:
        return f"{self.project}#{self.number}"


@dataclass(frozen=True, slots=True)
class ArtifactRefCompletionCatalog:
    """Bounded immutable payload snapshot for one target project."""

    project: str | None
    kinds: tuple[str, ...]
    documents: tuple[_ArtifactRefDocumentCandidate, ...] = ()
    artifact_files: tuple[_ArtifactRefFileCandidate, ...] = ()
    chats: tuple[_ArtifactRefChatCandidate, ...] = ()


@dataclass(frozen=True, slots=True)
class ArtifactRefCompletionResult:
    """Candidates and shared extension for one detected context."""

    context: ArtifactRefCompletionContext
    candidates: list[CompletionCandidate]
    shared_extension: str


@dataclass(frozen=True, slots=True)
class _ArtifactIndexCacheEntry:
    token: tuple[int, int] | None
    rows: tuple[object, ...]


_ARTIFACT_INDEX_CACHE: dict[Path, _ArtifactIndexCacheEntry] = {}


def at_reference_leading_match_count(
    candidates: Sequence[CompletionCandidate],
) -> int:
    """Count selectable rows in the menu's leading shared-core group."""
    if not candidates:
        return 0
    first_metadata = candidates[0].metadata
    if isinstance(first_metadata, AtReferenceLoadingCompletionMetadata):
        return 0
    first_group = type(first_metadata)
    count = 0
    for candidate in candidates:
        if type(candidate.metadata) is not first_group:
            break
        count += 1
    return count


def detect_artifact_ref_completion_context(
    text: str,
    cursor_offset: int,
    known_kinds: Iterable[str] = (),
) -> ArtifactRefCompletionContext | None:
    """Map the shared Rust cursor policy into prompt-local context."""
    raw = at_reference_context(text, cursor_offset, known_kinds)
    if raw is None:
        return None
    stage = str(raw["stage"])
    candidate_start, candidate_end = (int(value) for value in raw["candidate_span"])
    query_start, query_end = (int(value) for value in raw["query_span"])
    query = str(raw["query"])
    kind_value = raw.get("kind")
    kind = None if kind_value is None else str(kind_value)
    path_query = raw.get("path_query")
    path_directory: str | None = None
    path_partial = ""
    if isinstance(path_query, dict):
        path_directory = str(path_query.get("directory", ""))
        path_partial = str(path_query.get("partial", ""))
    return ArtifactRefCompletionContext(
        replacement_start=candidate_start,
        replacement_end=candidate_end,
        stage="kind" if stage == "kind" else "payload",
        partial_kind=query if stage == "kind" else (kind or ""),
        partial_payload=query if stage == "payload" else "",
        kind=kind,
        panel_title=(
            "artifact kinds"
            if stage == "kind"
            else _artifact_ref_payload_panel_title(kind or "")
        ),
        path_directory=path_directory,
        path_partial=path_partial,
        query_start=query_start,
        query_end=query_end,
        wire=raw,
    )


def _artifact_ref_payload_panel_title(kind: str) -> str:
    """Return the shared panel title for one resolved payload provider."""
    folded = kind.casefold()
    if folded == "file":
        return "file: artifacts"
    if folded == "chat":
        return "chat: chats"
    if folded == "commit":
        return "commit: commits"
    if folded == "bug":
        return "bug: bugs"
    return f"{kind}: documents"


def build_artifact_ref_completion_result(
    context: ArtifactRefCompletionContext,
    catalog: ArtifactRefCompletionCatalog,
    *,
    commits: Sequence[ArtifactRefCommitCandidate] = (),
    bugs: Sequence[ArtifactRefBugCandidate] = (),
    paths: Sequence[PromptPathRow] = (),
    paths_loading: bool = False,
) -> ArtifactRefCompletionResult:
    """Map shared Rust menu rows onto prompt completion candidates."""
    wire = context.wire
    if wire is None:
        return ArtifactRefCompletionResult(context, [], "")
    kinds = _kind_inventory(catalog.kinds)
    payloads, payload_metadata = _payload_inventory(
        context,
        catalog,
        commits=commits,
        bugs=bugs,
    )
    inventory = {
        "kinds": kinds,
        "paths": [{"name": row.name, "is_dir": row.is_dir} for row in paths],
        "payloads": payloads,
    }
    menu = at_reference_menu(wire, inventory)
    candidates: list[CompletionCandidate] = []
    for raw_row in menu.get("rows", []):
        if not isinstance(raw_row, dict):
            continue
        group = str(raw_row.get("group", ""))
        insertion = str(raw_row.get("insertion", ""))
        label = str(raw_row.get("label", ""))
        if group == "artifact":
            metadata: object = ArtifactRefKindCompletionMetadata(
                kind=label,
                builtin=bool(raw_row.get("builtin", False)),
            )
        elif group == "file":
            metadata = AtReferenceFileCompletionMetadata(
                is_dir=bool(raw_row.get("is_dir", False)),
                directory=context.path_directory or "",
            )
        else:
            metadata = payload_metadata.get(insertion)
            if metadata is None:
                continue
        candidates.append(
            CompletionCandidate(
                display=label,
                insertion=insertion,
                is_dir=bool(raw_row.get("is_dir", False)),
                name=label.removesuffix("/"),
                metadata=metadata,
            )
        )
    if context.stage == "kind" and paths_loading and not candidates:
        candidates.append(
            CompletionCandidate(
                display="loading files…",
                insertion="",
                is_dir=False,
                name="",
                metadata=AtReferenceLoadingCompletionMetadata(),
            )
        )
    return ArtifactRefCompletionResult(
        context,
        candidates,
        str(menu.get("shared_extension", "")),
    )


def load_artifact_ref_completion_catalog(
    project: str | None,
    context: ArtifactRefContext,
) -> ArtifactRefCompletionCatalog:
    """Discover bounded payload rows; callers must run this off the UI thread."""
    return ArtifactRefCompletionCatalog(
        project=project,
        kinds=tuple(context.known_kinds),
        documents=_load_document_candidates(context),
        artifact_files=_load_artifact_file_candidates(project, context),
        chats=_load_chat_candidates(context),
    )


def _kind_inventory(kinds: Sequence[str]) -> list[dict[str, object]]:
    """Project the warm kind catalog into shared-core inventory rows."""
    builtin = {kind.casefold() for kind in BUILTIN_ARTIFACT_REF_KINDS}
    return [
        {
            "kind": kind,
            "builtin": kind.casefold() in builtin,
            "detail": (
                "builtin artifact kind"
                if kind.casefold() in builtin
                else "document artifact"
            ),
        }
        for kind in dict.fromkeys((*BUILTIN_ARTIFACT_REF_KINDS, *kinds))
    ]


def _payload_inventory(
    context: ArtifactRefCompletionContext,
    catalog: ArtifactRefCompletionCatalog,
    *,
    commits: Sequence[ArtifactRefCommitCandidate],
    bugs: Sequence[ArtifactRefBugCandidate],
) -> tuple[
    list[dict[str, object]],
    dict[str, ArtifactRefPayloadCompletionMetadata],
]:
    """Project existing warm payload providers into shared-core inventory."""
    kind = context.kind or context.partial_kind
    folded = kind.casefold()
    rows: list[tuple[str, ArtifactRefPayloadCompletionMetadata]] = []
    if folded == "file":
        rows.extend(
            (
                row.payload,
                ArtifactRefPayloadCompletionMetadata(
                    kind=kind,
                    payload=row.payload,
                    source="file",
                    label=row.label,
                    detail=row.file_kind,
                    age=_age_label(row.created_at),
                ),
            )
            for row in catalog.artifact_files
        )
    elif folded == "chat":
        rows.extend(
            (
                row.payload,
                ArtifactRefPayloadCompletionMetadata(
                    kind=kind,
                    payload=row.payload,
                    source="chat",
                    label=Path(row.payload).name,
                    age=_age_label(row.modified_at),
                ),
            )
            for row in catalog.chats
        )
    elif folded == "commit":
        rows.extend(
            (
                row.payload,
                ArtifactRefPayloadCompletionMetadata(
                    kind=kind,
                    payload=row.payload,
                    source="commit",
                    label=row.subject,
                    detail=row.repo,
                    age=_age_label(row.timestamp),
                ),
            )
            for row in commits
        )
    elif folded == "bug":
        rows.extend(
            (
                row.payload,
                ArtifactRefPayloadCompletionMetadata(
                    kind=kind,
                    payload=row.payload,
                    source="bug",
                    label=row.title,
                    detail=row.project,
                    age=_age_label(row.updated_at),
                ),
            )
            for row in bugs
        )
    else:
        rows.extend(
            (
                row.payload,
                ArtifactRefPayloadCompletionMetadata(
                    kind=kind,
                    payload=row.payload,
                    source="document",
                    label=row.title,
                    detail=row.kind,
                    age=_age_label(row.created_at),
                ),
            )
            for row in catalog.documents
            if row.kind.casefold() == folded
        )

    inventory: list[dict[str, object]] = [
        {
            "payload": payload,
            "label": metadata.label,
            "detail": metadata.detail,
            "age": metadata.age,
        }
        for payload, metadata in rows
    ]
    metadata_by_insertion = {
        f"@{kind}:{payload}": metadata for payload, metadata in rows
    }
    return inventory, metadata_by_insertion


def _load_document_candidates(
    context: ArtifactRefContext,
) -> tuple[_ArtifactRefDocumentCandidate, ...]:
    corpora = tuple((root.root, root.kind) for root in context.document_roots)
    if not corpora:
        return ()
    try:
        from sase.plan_search.facade import SOURCE_REPO, search

        matches = search(
            source=SOURCE_REPO,
            sort="recent",
            limit=_MAX_DOCUMENT_ROWS,
            repo_root=corpora[0][0],
            document_corpora=corpora,
        )
    except Exception:
        return ()

    rows: list[_ArtifactRefDocumentCandidate] = []
    seen: set[tuple[str, str]] = set()
    for match in matches:
        plan = match.plan
        role = _document_role_for_path(plan.path, corpora, fallback=plan.kind)
        key = (role.casefold(), plan.relpath.casefold())
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            _ArtifactRefDocumentCandidate(
                kind=role,
                payload=plan.relpath,
                title=plan.title,
                created_at=plan.created_at,
            )
        )
    return tuple(rows)


def _document_role_for_path(
    path: str,
    corpora: Sequence[tuple[Path, str]],
    *,
    fallback: str,
) -> str:
    candidate = Path(path).expanduser().resolve(strict=False)
    for root, role in corpora:
        try:
            candidate.relative_to(Path(root).expanduser().resolve(strict=False))
        except ValueError:
            continue
        return role
    return fallback


def _load_artifact_file_candidates(
    project: str | None,
    context: ArtifactRefContext,
) -> tuple[_ArtifactRefFileCandidate, ...]:
    rows = _read_cached_artifact_index(context.artifact_index_path)
    accepted_projects = _accepted_project_names(project, context)
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
    filtered.sort(
        key=lambda row: (
            str(getattr(row, "created_at", "")),
            str(getattr(row, "id", "")).casefold(),
        ),
        reverse=True,
    )
    return tuple(
        _ArtifactRefFileCandidate(
            payload=str(getattr(row, "id", "")),
            label=str(getattr(row, "label", getattr(row, "id", ""))),
            file_kind=str(getattr(row, "kind", "file")),
            created_at=str(getattr(row, "created_at", "") or ""),
        )
        for row in filtered[:_MAX_ARTIFACT_FILE_ROWS]
    )


def _read_cached_artifact_index(index_path: Path) -> tuple[object, ...]:
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
            from sase.core.artifact_file_facade import read_artifact_file_index

            rows = tuple(read_artifact_file_index(resolved))
        except Exception:
            rows = ()
    _ARTIFACT_INDEX_CACHE[resolved] = _ArtifactIndexCacheEntry(token, rows)
    return rows


def _accepted_project_names(
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


def _load_chat_candidates(
    context: ArtifactRefContext,
) -> tuple[_ArtifactRefChatCandidate, ...]:
    try:
        from sase.history.chat_storage import iter_chat_files

        paths = tuple(islice(iter_chat_files(), _MAX_CHAT_SCAN_ROWS))
    except Exception:
        return ()
    rows: list[_ArtifactRefChatCandidate] = []
    root = context.chats_root.expanduser().resolve(strict=False)
    for path in paths:
        resolved = path.expanduser().resolve(strict=False)
        try:
            payload = resolved.relative_to(root).as_posix()
            modified_at = resolved.stat().st_mtime
        except (OSError, ValueError):
            continue
        rows.append(_ArtifactRefChatCandidate(payload, modified_at))
    rows.sort(key=lambda row: (-row.modified_at, row.payload.casefold(), row.payload))
    return tuple(rows[:_MAX_CHAT_ROWS])


def _age_label(value: str | int | float) -> str:
    if not value:
        return ""
    timestamp: float
    if isinstance(value, (int, float)):
        timestamp = float(value)
    else:
        raw = value.strip()
        try:
            timestamp = datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return raw[:10]
    seconds = max(0, datetime.now(UTC).timestamp() - timestamp)
    if seconds < 60:
        return "now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    if seconds < 7 * 86400:
        return f"{int(seconds // 86400)}d"
    return datetime.fromtimestamp(timestamp, UTC).date().isoformat()


__all__ = [
    "ARTIFACT_REF_COMPLETION_KIND",
    "AtReferenceFileCompletionMetadata",
    "AtReferenceLoadingCompletionMetadata",
    "ArtifactRefBugCandidate",
    "ArtifactRefCommitCandidate",
    "ArtifactRefCompletionCatalog",
    "ArtifactRefCompletionContext",
    "ArtifactRefCompletionResult",
    "ArtifactRefKindCompletionMetadata",
    "ArtifactRefPayloadCompletionMetadata",
    "at_reference_leading_match_count",
    "build_artifact_ref_completion_result",
    "detect_artifact_ref_completion_context",
    "load_artifact_ref_completion_catalog",
]
