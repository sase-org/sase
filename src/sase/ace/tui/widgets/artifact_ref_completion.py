"""Pure artifact-reference completion plus off-thread catalog discovery."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Literal, cast

from sase.artifact_refs import (
    BUILTIN_ARTIFACT_REF_KINDS,
    ArtifactRefContext,
    at_reference_context,
    at_reference_inventory,
    at_reference_menu,
)
from sase.ace.tui.widgets import _artifact_ref_entity_catalogs as entity_catalogs
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
    "bead",
    "agent",
]

_MAX_DOCUMENT_ROWS_PER_KIND = 5000
_MAX_ARTIFACT_FILE_ROWS = 5000
_MAX_CHAT_SCAN_ROWS = 5000
_MAX_CHAT_ROWS = 5000


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
    detail: str = ""
    label_match: tuple[tuple[int, int], ...] = ()
    match_tier: int = 0

    @property
    def source_label(self) -> str:
        return self.detail or ("builtin" if self.builtin else "document")


@dataclass(frozen=True, slots=True)
class ArtifactRefPayloadCompletionMetadata:
    """Metadata rendered beside one artifact payload candidate."""

    kind: str
    payload: str
    source: ArtifactRefPayloadSource
    label: str = ""
    detail: str = ""
    age: str = ""
    label_match: tuple[tuple[int, int], ...] = ()
    title_match: tuple[tuple[int, int], ...] = ()
    match_tier: int = 0


@dataclass(frozen=True, slots=True)
class AtReferenceFileCompletionMetadata:
    """Metadata for one local path row in the shared ``@`` menu."""

    is_dir: bool
    directory: str
    label_match: tuple[tuple[int, int], ...] = ()
    match_tier: int = 0


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
    beads: tuple[entity_catalogs.ArtifactRefBeadCandidate, ...] = ()
    agents: tuple[entity_catalogs.ArtifactRefAgentCandidate, ...] = ()
    kind_details: tuple[tuple[str, str], ...] = ()
    truncated_payloads_by_kind: tuple[tuple[str, int], ...] = ()
    payload_indexes: Mapping[str, object] = field(
        init=False,
        repr=False,
        compare=False,
    )
    payload_metadata: Mapping[
        str,
        Mapping[str, ArtifactRefPayloadCompletionMetadata],
    ] = field(
        init=False,
        repr=False,
        compare=False,
    )
    payload_truncation: Mapping[str, int] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        """Build native indexes and row metadata once with the warm snapshot."""
        indexes, metadata = _build_catalog_payload_memos(self)
        object.__setattr__(self, "payload_indexes", MappingProxyType(indexes))
        object.__setattr__(self, "payload_metadata", MappingProxyType(metadata))
        object.__setattr__(
            self,
            "payload_truncation",
            MappingProxyType(
                {
                    kind.casefold(): count
                    for kind, count in self.truncated_payloads_by_kind
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ArtifactRefCompletionResult:
    """Candidates and shared extension for one detected context."""

    context: ArtifactRefCompletionContext
    candidates: list[CompletionCandidate]
    shared_extension: str
    payload_count: int = 0
    payload_total: int = 0
    truncated_payloads: int = 0
    files_suppressed: bool = False


@dataclass(frozen=True, slots=True)
class _ArtifactIndexCacheEntry:
    token: tuple[int, int] | None
    rows: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class _LoadedCandidates[CandidateT]:
    rows: tuple[CandidateT, ...]
    truncated_by_kind: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class _SnapshotPayloadMemo:
    snapshot: object
    index: object
    metadata_by_payload: Mapping[str, ArtifactRefPayloadCompletionMetadata]


_ARTIFACT_INDEX_CACHE: dict[Path, _ArtifactIndexCacheEntry] = {}
_SNAPSHOT_PAYLOAD_MEMOS: dict[str, _SnapshotPayloadMemo] = {}


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
    if folded == "bead":
        return "bead: beads"
    if folded == "agent":
        return "agent: agents"
    return f"{kind}: documents"


def build_artifact_ref_completion_result(
    context: ArtifactRefCompletionContext,
    catalog: ArtifactRefCompletionCatalog,
    *,
    include_files: bool = False,
    commits: Sequence[ArtifactRefCommitCandidate] = (),
    bugs: Sequence[ArtifactRefBugCandidate] = (),
    paths: Sequence[PromptPathRow] = (),
    paths_loading: bool = False,
) -> ArtifactRefCompletionResult:
    """Map shared Rust menu rows onto prompt completion candidates."""
    wire = context.wire
    if wire is None:
        return ArtifactRefCompletionResult(context, [], "")
    kinds = _kind_inventory(catalog)
    payloads, payload_index, payload_metadata, truncated_payloads = _payload_inventory(
        context,
        catalog,
        commits=commits,
        bugs=bugs,
    )
    inventory = {
        "kinds": kinds,
        "paths": [{"name": row.name, "is_dir": row.is_dir} for row in paths],
        "payloads": payloads,
        "truncated_payloads": truncated_payloads,
    }
    menu = at_reference_menu(
        wire,
        inventory,
        payload_index=payload_index,
        options={"include_files": include_files},
    )
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
                detail=str(raw_row.get("detail", "")),
                label_match=_wire_match_runs(raw_row.get("label_match")),
                match_tier=int(raw_row.get("match_tier", 0)),
            )
        elif group == "file":
            metadata = AtReferenceFileCompletionMetadata(
                is_dir=bool(raw_row.get("is_dir", False)),
                directory=context.path_directory or "",
                label_match=_wire_match_runs(raw_row.get("label_match")),
                match_tier=int(raw_row.get("match_tier", 0)),
            )
        else:
            payload = insertion.removeprefix(f"@{context.kind or ''}:")
            metadata = payload_metadata.get(payload)
            if metadata is None:
                continue
            metadata = replace(
                metadata,
                label=str(raw_row.get("title", metadata.label)),
                label_match=_wire_match_runs(raw_row.get("label_match")),
                title_match=_wire_match_runs(raw_row.get("title_match")),
                match_tier=int(raw_row.get("match_tier", 0)),
            )
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
        int(menu.get("payload_count", 0)),
        len(payload_metadata) + truncated_payloads,
        int(menu.get("truncated_payloads", 0)),
        bool(menu.get("files_suppressed", False)),
    )


def _wire_match_runs(value: object) -> tuple[tuple[int, int], ...]:
    """Return validated half-open character ranges from one wire value."""
    if not isinstance(value, (list, tuple)):
        return ()
    runs: list[tuple[int, int]] = []
    for raw_run in value:
        if not isinstance(raw_run, (list, tuple)) or len(raw_run) != 2:
            continue
        start, end = raw_run
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        if 0 <= start < end:
            runs.append((start, end))
    return tuple(runs)


def load_artifact_ref_completion_catalog(
    project: str | None,
    context: ArtifactRefContext,
) -> ArtifactRefCompletionCatalog:
    """Discover bounded payload rows; callers must run this off the UI thread."""
    documents = _load_document_candidate_catalog(context)
    artifact_files = _load_artifact_file_candidate_catalog(project, context)
    chats = _load_chat_candidate_catalog(context)
    beads = entity_catalogs.load_bead_candidate_catalog(context)
    agents = entity_catalogs.load_agent_candidate_catalog(context)
    return ArtifactRefCompletionCatalog(
        project=project,
        kinds=tuple(context.known_kinds),
        documents=tuple(documents.rows),
        artifact_files=tuple(artifact_files.rows),
        chats=tuple(chats.rows),
        beads=beads.rows,
        agents=agents.rows,
        kind_details=_document_kind_details(context),
        truncated_payloads_by_kind=(
            *documents.truncated_by_kind,
            *artifact_files.truncated_by_kind,
            *chats.truncated_by_kind,
            ("bead", beads.truncated),
            ("agent", agents.truncated),
        ),
    )


def _kind_inventory(
    catalog: ArtifactRefCompletionCatalog,
) -> list[dict[str, object]]:
    """Project the warm kind catalog into shared-core inventory rows."""
    builtin = {kind.casefold() for kind in BUILTIN_ARTIFACT_REF_KINDS}
    detail_by_kind = {kind.casefold(): detail for kind, detail in catalog.kind_details}
    return [
        {
            "kind": kind,
            "builtin": kind.casefold() in builtin,
            "detail": detail_by_kind.get(
                kind.casefold(),
                "builtin" if kind.casefold() in builtin else "document",
            ),
        }
        for kind in dict.fromkeys((*BUILTIN_ARTIFACT_REF_KINDS, *catalog.kinds))
    ]


def _document_kind_details(
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


def _payload_inventory(
    context: ArtifactRefCompletionContext,
    catalog: ArtifactRefCompletionCatalog,
    *,
    commits: Sequence[ArtifactRefCommitCandidate],
    bugs: Sequence[ArtifactRefBugCandidate],
) -> tuple[
    list[dict[str, object]],
    object | None,
    Mapping[str, ArtifactRefPayloadCompletionMetadata],
    int,
]:
    """Return a warm native index and O(1) metadata lookup for this kind."""
    if context.stage != "payload":
        return [], None, MappingProxyType({}), 0
    kind = context.kind or context.partial_kind
    folded = kind.casefold()
    if folded == "commit":
        memo = _snapshot_payload_memo(kind, commits)
    elif folded == "bug":
        memo = _snapshot_payload_memo(kind, bugs)
    else:
        index = catalog.payload_indexes.get(folded)
        metadata = catalog.payload_metadata.get(folded)
        if index is None or metadata is None:
            return [], None, MappingProxyType({}), 0
        truncated = catalog.payload_truncation.get(folded, 0)
        return [], index, metadata, truncated
    return [], memo.index, memo.metadata_by_payload, 0


def _build_catalog_payload_memos(
    catalog: ArtifactRefCompletionCatalog,
) -> tuple[
    dict[str, object],
    dict[str, Mapping[str, ArtifactRefPayloadCompletionMetadata]],
]:
    """Build every static provider's native index with the warm catalog."""
    if not any(
        (
            catalog.documents,
            catalog.artifact_files,
            catalog.chats,
            catalog.beads,
            catalog.agents,
        )
    ):
        return {}, {}
    kinds = [
        *catalog.kinds,
        *(row.kind for row in catalog.documents),
        "file",
        "chat",
        "bead",
        "agent",
    ]
    indexes: dict[str, object] = {}
    metadata: dict[
        str,
        Mapping[str, ArtifactRefPayloadCompletionMetadata],
    ] = {}
    for kind in dict.fromkeys(value.casefold() for value in kinds):
        if kind in {"commit", "bug"}:
            continue
        rows = _payload_rows(kind, catalog, commits=(), bugs=())
        index, metadata_by_payload = _index_payload_rows(rows)
        indexes[kind] = index
        metadata[kind] = metadata_by_payload
    return indexes, metadata


def _snapshot_payload_memo(
    kind: str,
    snapshot: Sequence[ArtifactRefCommitCandidate] | Sequence[ArtifactRefBugCandidate],
) -> _SnapshotPayloadMemo:
    """Memoize dynamic mounted-pane snapshots by object identity."""
    folded = kind.casefold()
    cached = _SNAPSHOT_PAYLOAD_MEMOS.get(folded)
    if cached is not None and cached.snapshot is snapshot:
        return cached
    commits: Sequence[ArtifactRefCommitCandidate] = ()
    bugs: Sequence[ArtifactRefBugCandidate] = ()
    if folded == "commit":
        commits = cast(Sequence[ArtifactRefCommitCandidate], snapshot)
    else:
        bugs = cast(Sequence[ArtifactRefBugCandidate], snapshot)
    index, metadata = _index_payload_rows(
        _payload_rows(kind, None, commits=commits, bugs=bugs)
    )
    memo = _SnapshotPayloadMemo(snapshot, index, metadata)
    _SNAPSHOT_PAYLOAD_MEMOS[folded] = memo
    return memo


def _index_payload_rows(
    rows: Sequence[tuple[str, ArtifactRefPayloadCompletionMetadata]],
) -> tuple[
    object,
    Mapping[str, ArtifactRefPayloadCompletionMetadata],
]:
    inventory = [
        {
            "payload": payload,
            "label": metadata.label,
            "detail": metadata.detail,
            "age": metadata.age,
        }
        for payload, metadata in rows
    ]
    metadata_by_payload = MappingProxyType(dict(rows))
    return at_reference_inventory(inventory), metadata_by_payload


def _payload_rows(
    kind: str,
    catalog: ArtifactRefCompletionCatalog | None,
    *,
    commits: Sequence[ArtifactRefCommitCandidate],
    bugs: Sequence[ArtifactRefBugCandidate],
) -> list[tuple[str, ArtifactRefPayloadCompletionMetadata]]:
    """Project one provider snapshot into native rows and render metadata."""
    folded = kind.casefold()
    rows: list[tuple[str, ArtifactRefPayloadCompletionMetadata]] = []
    if folded == "file" and catalog is not None:
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
    elif folded == "chat" and catalog is not None:
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
    elif folded in {"bead", "agent"} and catalog is not None:
        entities = catalog.beads if folded == "bead" else catalog.agents
        source: ArtifactRefPayloadSource = "bead" if folded == "bead" else "agent"
        rows.extend(
            (
                row.payload,
                ArtifactRefPayloadCompletionMetadata(
                    kind=kind,
                    payload=row.payload,
                    source=source,
                    label=row.label,
                    detail=row.detail,
                    age=_age_label(row.updated_at),
                ),
            )
            for row in entities
        )
    elif catalog is not None:
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

    return rows


def _load_document_candidate_catalog(
    context: ArtifactRefContext,
) -> _LoadedCandidates[_ArtifactRefDocumentCandidate]:
    """Load each document role independently so large roles cannot starve peers."""
    corpora_by_role: dict[str, list[tuple[Path, str]]] = {}
    role_names: dict[str, str] = {}
    for root in context.document_roots:
        folded = root.kind.casefold()
        role_names.setdefault(folded, root.kind)
        corpora_by_role.setdefault(folded, []).append((root.root, root.kind))
    if not corpora_by_role:
        return _LoadedCandidates(())

    from sase.plan_search.facade import SOURCE_REPO, search

    rows: list[_ArtifactRefDocumentCandidate] = []
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
        role_rows: list[_ArtifactRefDocumentCandidate] = []
        seen: set[str] = set()
        for match in matches:
            plan = match.plan
            key = plan.relpath.casefold()
            if key in seen:
                continue
            seen.add(key)
            if len(role_rows) < _MAX_DOCUMENT_ROWS_PER_KIND:
                role_rows.append(
                    _ArtifactRefDocumentCandidate(
                        kind=role,
                        payload=plan.relpath,
                        title=plan.title,
                        created_at=plan.created_at,
                    )
                )
        rows.extend(role_rows)
        truncated.append(
            (
                folded,
                max(0, len(seen) - _MAX_DOCUMENT_ROWS_PER_KIND),
            )
        )
    return _LoadedCandidates(tuple(rows), tuple(truncated))


def _load_artifact_file_candidate_catalog(
    project: str | None,
    context: ArtifactRefContext,
) -> _LoadedCandidates[_ArtifactRefFileCandidate]:
    """Load bounded artifact-file rows and retain the exact eligible count."""
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
    return _LoadedCandidates(
        tuple(
            _ArtifactRefFileCandidate(
                payload=str(getattr(row, "id", "")),
                label=str(getattr(row, "label", getattr(row, "id", ""))),
                file_kind=str(getattr(row, "kind", "file")),
                created_at=str(getattr(row, "created_at", "") or ""),
            )
            for row in filtered[:_MAX_ARTIFACT_FILE_ROWS]
        ),
        (
            (
                "file",
                max(0, len(filtered) - _MAX_ARTIFACT_FILE_ROWS),
            ),
        )
        if filtered
        else (),
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
            from sase.core.artifact_file_query_facade import query_artifact_files

            rows = tuple(query_artifact_files(resolved))
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


def _load_chat_candidate_catalog(
    context: ArtifactRefContext,
) -> _LoadedCandidates[_ArtifactRefChatCandidate]:
    """Load bounded chat rows and count paths deliberately left unscanned."""
    try:
        from sase.history.chat_storage import iter_chat_files

        paths = iter_chat_files()
    except Exception:
        return _LoadedCandidates(())
    rows: list[_ArtifactRefChatCandidate] = []
    truncated = 0
    root = context.chats_root.expanduser().resolve(strict=False)
    for index, path in enumerate(paths):
        if index >= _MAX_CHAT_SCAN_ROWS:
            truncated += 1
            continue
        resolved = path.expanduser().resolve(strict=False)
        try:
            payload = resolved.relative_to(root).as_posix()
            modified_at = resolved.stat().st_mtime
        except (OSError, ValueError):
            continue
        rows.append(_ArtifactRefChatCandidate(payload, modified_at))
    rows.sort(key=lambda row: (-row.modified_at, row.payload.casefold(), row.payload))
    truncated += max(0, len(rows) - _MAX_CHAT_ROWS)
    return _LoadedCandidates(
        tuple(rows[:_MAX_CHAT_ROWS]),
        (("chat", truncated),),
    )


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
