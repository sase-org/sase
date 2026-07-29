"""Pure artifact-reference completion plus off-thread catalog discovery."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import islice
import os
from pathlib import Path
import re
from typing import Literal

from sase.artifact_refs import (
    BUILTIN_ARTIFACT_REF_KINDS,
    ArtifactRefContext,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate


ARTIFACT_REF_COMPLETION_KIND = "artifact_ref"
ArtifactRefCompletionStage = Literal["kind", "payload"]
ArtifactRefPayloadSource = Literal[
    "document",
    "file",
    "chat",
    "commit",
    "bug",
]

_KIND_RE = re.compile(r"[a-z][a-z0-9_-]*\Z")
_PARTIAL_KIND_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")
_LEFT_CONTEXT = frozenset("'\"")
_TOKEN_TERMINATORS = frozenset("'\"`?!;,()[]{}<>|&=+*^%$\\")
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


def detect_artifact_ref_completion_context(
    text: str,
    cursor_offset: int,
    known_kinds: Iterable[str] = (),
) -> ArtifactRefCompletionContext | None:
    """Detect an incomplete ``@kind:payload`` context without filesystem work."""
    if not 0 <= cursor_offset <= len(text) or "@" not in text:
        return None
    if _cursor_is_literal(text, cursor_offset):
        return None

    line_start = text.rfind("\n", 0, cursor_offset) + 1
    marker = text.rfind("@", line_start, cursor_offset + 1)
    while marker >= line_start and not _valid_left_context(text, marker):
        marker = text.rfind("@", line_start, marker)
    if marker < line_start:
        return None

    token_end = _candidate_end(text, cursor_offset)
    token = text[marker:token_end]
    cursor_in_token = cursor_offset - marker
    if cursor_in_token < 1:
        return None
    prefix = token[:cursor_in_token]
    if any(char.isspace() or char in _TOKEN_TERMINATORS for char in prefix[1:]):
        return None

    separator = token.find(":")
    if separator == -1:
        raw_kind = token[1:]
        if raw_kind and _PARTIAL_KIND_RE.fullmatch(raw_kind) is None:
            return None
        # Anything path-shaped belongs to the existing @file provider.
        if "/" in raw_kind or raw_kind.startswith((".", "~")):
            return None
        partial_kind = token[1:cursor_in_token]
        if partial_kind and _PARTIAL_KIND_RE.fullmatch(partial_kind) is None:
            return None
        return ArtifactRefCompletionContext(
            replacement_start=marker,
            replacement_end=token_end,
            stage="kind",
            partial_kind=partial_kind,
            partial_payload="",
            kind=None,
            panel_title="artifact kinds",
        )

    raw_kind = token[1:separator]
    if cursor_in_token <= separator:
        partial_kind = token[1:cursor_in_token]
        if _PARTIAL_KIND_RE.fullmatch(raw_kind) is None or (
            partial_kind and _PARTIAL_KIND_RE.fullmatch(partial_kind) is None
        ):
            return None
        canonical_kind = _canonical_kind(raw_kind, known_kinds)
        return ArtifactRefCompletionContext(
            replacement_start=marker,
            replacement_end=marker + separator + 1,
            stage="kind",
            partial_kind=partial_kind,
            partial_payload="",
            kind=canonical_kind,
            panel_title="artifact kinds",
        )

    if _KIND_RE.fullmatch(raw_kind) is None:
        return None
    canonical_kind = _canonical_kind(raw_kind, known_kinds)
    payload_end = token_end
    fragment = token.find("#", separator + 1)
    if canonical_kind.casefold() != "bug" and fragment != -1:
        fragment_offset = marker + fragment
        if cursor_offset > fragment_offset:
            return None
        payload_end = fragment_offset
    if cursor_offset > payload_end:
        return None
    partial_payload = text[marker + separator + 1 : cursor_offset]
    return ArtifactRefCompletionContext(
        replacement_start=marker,
        replacement_end=payload_end,
        stage="payload",
        partial_kind=raw_kind,
        partial_payload=partial_payload,
        kind=canonical_kind,
        panel_title=_artifact_ref_payload_panel_title(canonical_kind),
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
) -> ArtifactRefCompletionResult:
    """Build memory-only candidates for one artifact completion stage."""
    if context.stage == "kind":
        candidates, shared = _build_kind_candidates(context.partial_kind, catalog.kinds)
    else:
        candidates, shared = _build_payload_candidates(
            context,
            catalog,
            commits=commits,
            bugs=bugs,
        )
    return ArtifactRefCompletionResult(context, candidates, shared)


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


def _build_kind_candidates(
    partial: str,
    kinds: Sequence[str],
) -> tuple[list[CompletionCandidate], str]:
    builtin = {kind.casefold() for kind in BUILTIN_ARTIFACT_REF_KINDS}
    ordered = tuple(
        dict.fromkeys(
            (
                *BUILTIN_ARTIFACT_REF_KINDS,
                *sorted(
                    (kind for kind in kinds if kind.casefold() not in builtin),
                    key=lambda value: (value.casefold(), value),
                ),
            )
        )
    )
    matches = [
        kind for kind in ordered if kind.casefold().startswith(partial.casefold())
    ]
    candidates = [
        CompletionCandidate(
            display=kind,
            insertion=f"@{kind}:",
            is_dir=False,
            name=kind,
            metadata=ArtifactRefKindCompletionMetadata(
                kind,
                kind.casefold() in builtin,
            ),
        )
        for kind in matches
    ]
    return candidates, _shared_extension(matches, partial)


def _build_payload_candidates(
    context: ArtifactRefCompletionContext,
    catalog: ArtifactRefCompletionCatalog,
    *,
    commits: Sequence[ArtifactRefCommitCandidate],
    bugs: Sequence[ArtifactRefBugCandidate],
) -> tuple[list[CompletionCandidate], str]:
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

    partial = context.partial_payload
    filtered = [
        (payload, metadata)
        for payload, metadata in rows
        if _payload_matches(partial, payload, metadata)
    ]
    candidates = [
        CompletionCandidate(
            display=payload,
            insertion=f"@{kind}:{payload}",
            is_dir=False,
            name=payload,
            metadata=metadata,
        )
        for payload, metadata in filtered
    ]
    return candidates, _shared_extension([payload for payload, _ in filtered], partial)


def _payload_matches(
    partial: str,
    payload: str,
    metadata: ArtifactRefPayloadCompletionMetadata,
) -> bool:
    folded = partial.casefold()
    if not folded:
        return True
    return payload.casefold().startswith(
        folded
    ) or metadata.label.casefold().startswith(folded)


def _shared_extension(values: Sequence[str], partial: str) -> str:
    if len(values) < 2:
        return ""
    folded = os.path.commonprefix([value.casefold() for value in values])
    if len(folded) <= len(partial):
        return ""
    return values[0][len(partial) : len(folded)]


def _valid_left_context(text: str, marker: int) -> bool:
    return (
        marker == 0 or text[marker - 1].isspace() or text[marker - 1] in _LEFT_CONTEXT
    )


def _candidate_end(text: str, cursor_offset: int) -> int:
    end = cursor_offset
    while end < len(text):
        char = text[end]
        if char.isspace() or char in _TOKEN_TERMINATORS:
            break
        end += 1
    return end


def _canonical_kind(kind: str, known_kinds: Iterable[str]) -> str:
    folded = kind.casefold()
    return next(
        (known for known in known_kinds if known.casefold() == folded),
        kind.lower(),
    )


def _cursor_is_literal(text: str, cursor_offset: int) -> bool:
    try:
        from sase.xprompt._literal_zones import literal_zone_ranges

        probe = max(0, cursor_offset - 1)
        return any(start <= probe < end for start, end in literal_zone_ranges(text))
    except Exception:
        return False


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
    "ArtifactRefBugCandidate",
    "ArtifactRefCommitCandidate",
    "ArtifactRefCompletionCatalog",
    "ArtifactRefCompletionContext",
    "ArtifactRefCompletionResult",
    "ArtifactRefKindCompletionMetadata",
    "ArtifactRefPayloadCompletionMetadata",
    "build_artifact_ref_completion_result",
    "detect_artifact_ref_completion_context",
    "load_artifact_ref_completion_catalog",
]
