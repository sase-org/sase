"""I/O-free artifact-reference menu construction and native index memoization."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, cast

from sase.artifact_refs import (
    BUILTIN_ARTIFACT_REF_KINDS,
    at_reference_inventory,
    at_reference_menu,
)
from sase.ace.tui.widgets import _artifact_ref_entity_catalogs as entity_catalogs
from sase.ace.tui.widgets._artifact_ref_completion_models import (
    ArtifactRefBugCandidate,
    ArtifactRefChatCandidate,
    ArtifactRefCommitCandidate,
    ArtifactRefCompletionContext,
    ArtifactRefCompletionResult,
    ArtifactRefDocumentCandidate,
    ArtifactRefFileCandidate,
    ArtifactRefKindCompletionMetadata,
    ArtifactRefPayloadCompletionMetadata,
    ArtifactRefPayloadSource,
    AtReferenceFileCompletionMetadata,
    AtReferenceLoadingCompletionMetadata,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_path_inventory import PromptPathRow


class _AtReferenceMenuBuilder(Protocol):
    def __call__(
        self,
        context: Mapping[str, Any],
        inventory: Mapping[str, Any],
        *,
        payload_index: object | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]: ...


class _AtReferenceInventoryBuilder(Protocol):
    def __call__(self, payloads: Iterable[Mapping[str, Any]]) -> object: ...


@dataclass(frozen=True, slots=True)
class ArtifactRefCompletionCatalog:
    """Bounded immutable payload snapshot for one target project."""

    project: str | None
    kinds: tuple[str, ...]
    documents: tuple[ArtifactRefDocumentCandidate, ...] = ()
    artifact_files: tuple[ArtifactRefFileCandidate, ...] = ()
    chats: tuple[ArtifactRefChatCandidate, ...] = ()
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
        indexes, metadata = build_catalog_payload_memos(self)
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
class SnapshotPayloadMemo:
    snapshot: object
    index: object
    metadata_by_payload: Mapping[str, ArtifactRefPayloadCompletionMetadata]


_SNAPSHOT_PAYLOAD_MEMOS: dict[str, SnapshotPayloadMemo] = {}


def build_artifact_ref_completion_result(
    context: ArtifactRefCompletionContext,
    catalog: ArtifactRefCompletionCatalog,
    *,
    include_files: bool = False,
    commits: Sequence[ArtifactRefCommitCandidate] = (),
    commits_loading: bool = False,
    commits_truncated_payloads: int = 0,
    bugs: Sequence[ArtifactRefBugCandidate] = (),
    paths: Sequence[PromptPathRow] = (),
    paths_loading: bool = False,
    _menu_builder: _AtReferenceMenuBuilder = at_reference_menu,
    _inventory_builder: _AtReferenceInventoryBuilder = at_reference_inventory,
    _payload_inventory_builder: Callable[..., Any] | None = None,
) -> ArtifactRefCompletionResult:
    """Map shared Rust menu rows onto prompt completion candidates."""
    wire = context.wire
    if wire is None:
        return ArtifactRefCompletionResult(context, [], "")
    kinds = kind_inventory(catalog)
    if _payload_inventory_builder is None:
        inventory_result = payload_inventory(
            context,
            catalog,
            commits=commits,
            commits_truncated_payloads=commits_truncated_payloads,
            bugs=bugs,
            inventory_builder=_inventory_builder,
        )
    else:
        inventory_result = _payload_inventory_builder(
            context,
            catalog,
            commits=commits,
            commits_truncated_payloads=commits_truncated_payloads,
            bugs=bugs,
        )
    payloads, payload_index, payload_metadata, truncated_payloads = inventory_result
    inventory = {
        "kinds": kinds,
        "paths": [{"name": row.name, "is_dir": row.is_dir} for row in paths],
        "payloads": payloads,
        "truncated_payloads": truncated_payloads,
    }
    menu = _menu_builder(
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
                label_match=wire_match_runs(raw_row.get("label_match")),
                match_tier=int(raw_row.get("match_tier", 0)),
            )
        elif group == "file":
            metadata = AtReferenceFileCompletionMetadata(
                is_dir=bool(raw_row.get("is_dir", False)),
                directory=context.path_directory or "",
                label_match=wire_match_runs(raw_row.get("label_match")),
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
                label_match=wire_match_runs(raw_row.get("label_match")),
                title_match=wire_match_runs(raw_row.get("title_match")),
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
    loading_text = ""
    if context.stage == "kind" and paths_loading and not candidates:
        loading_text = "loading files…"
    elif (
        context.stage == "payload"
        and (context.kind or "").casefold() == "commit"
        and commits_loading
        and not candidates
    ):
        loading_text = "loading commits…"
    if loading_text:
        candidates.append(
            CompletionCandidate(
                display=loading_text,
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


def wire_match_runs(value: object) -> tuple[tuple[int, int], ...]:
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


def kind_inventory(
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


def payload_inventory(
    context: ArtifactRefCompletionContext,
    catalog: ArtifactRefCompletionCatalog,
    *,
    commits: Sequence[ArtifactRefCommitCandidate],
    commits_truncated_payloads: int = 0,
    bugs: Sequence[ArtifactRefBugCandidate],
    inventory_builder: _AtReferenceInventoryBuilder = at_reference_inventory,
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
        memo = snapshot_payload_memo(kind, commits, inventory_builder)
    elif folded == "bug":
        memo = snapshot_payload_memo(kind, bugs, inventory_builder)
    else:
        index = catalog.payload_indexes.get(folded)
        metadata = catalog.payload_metadata.get(folded)
        if index is None or metadata is None:
            return [], None, MappingProxyType({}), 0
        truncated = catalog.payload_truncation.get(folded, 0)
        return [], index, metadata, truncated
    truncated = commits_truncated_payloads if folded == "commit" else 0
    return [], memo.index, memo.metadata_by_payload, truncated


def build_catalog_payload_memos(
    catalog: ArtifactRefCompletionCatalog,
    inventory_builder: _AtReferenceInventoryBuilder = at_reference_inventory,
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
        rows = payload_rows(kind, catalog, commits=(), bugs=())
        index, metadata_by_payload = index_payload_rows(rows, inventory_builder)
        indexes[kind] = index
        metadata[kind] = metadata_by_payload
    return indexes, metadata


def snapshot_payload_memo(
    kind: str,
    snapshot: Sequence[ArtifactRefCommitCandidate] | Sequence[ArtifactRefBugCandidate],
    inventory_builder: _AtReferenceInventoryBuilder,
) -> SnapshotPayloadMemo:
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
    index, metadata = index_payload_rows(
        payload_rows(kind, None, commits=commits, bugs=bugs),
        inventory_builder,
    )
    memo = SnapshotPayloadMemo(snapshot, index, metadata)
    _SNAPSHOT_PAYLOAD_MEMOS[folded] = memo
    return memo


def index_payload_rows(
    rows: Sequence[tuple[str, ArtifactRefPayloadCompletionMetadata]],
    inventory_builder: _AtReferenceInventoryBuilder = at_reference_inventory,
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
            "scope": metadata.scope,
            "rank": metadata.rank,
            "body": metadata.body,
        }
        for payload, metadata in rows
    ]
    metadata_by_payload = MappingProxyType(dict(rows))
    return inventory_builder(inventory), metadata_by_payload


def payload_rows(
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
                    age=age_label(row.created_at),
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
                    age=age_label(row.modified_at),
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
                    label=row.label,
                    detail=row.detail,
                    age=row.age,
                    scope=row.scope,
                    rank=row.rank,
                    body=row.body,
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
                    age=age_label(row.updated_at),
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
                    age=age_label(row.updated_at),
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
                    age=age_label(row.created_at),
                ),
            )
            for row in catalog.documents
            if row.kind.casefold() == folded
        )
    return rows


def age_label(value: str | int | float) -> str:
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
