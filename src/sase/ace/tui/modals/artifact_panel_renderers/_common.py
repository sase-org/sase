"""Shared helpers for artifact panel renderers."""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from rich.text import Text

from sase.core.artifact_wire import (
    ARTIFACT_KIND_FILE,
    ArtifactDetailWire,
    ArtifactNodeWire,
    ArtifactPayloadWire,
)

FILE_PREVIEW_LINE_LIMIT = 120
FILE_PREVIEW_MAX_BYTES = 256_000


def render_header(detail: ArtifactDetailWire) -> Text:
    node = detail.node
    assert node is not None
    text = Text()
    text.append("Artifact\n", style="bold")
    append_kv(text, "ID", node.id)
    append_kv(text, "Kind", node.kind)
    append_kv(text, "Title", node.display_title)
    append_kv(text, "Subtitle", node.subtitle)
    append_kv(text, "Provenance", node.provenance)
    append_kv(text, "Source", _join_compact([node.source_kind, node.source_id]))
    append_kv(text, "Created", node.created_at)
    append_kv(text, "Updated", node.updated_at)
    text.append("\n")
    return text


def append_child_summary(text: Text, children: list[ArtifactNodeWire]) -> None:
    append_kv(
        text,
        "Child artifacts",
        format_kind_counts(node.kind for node in children),
    )


def append_linked_kinds(
    text: Text, detail: ArtifactDetailWire, kinds: tuple[str, ...]
) -> None:
    ids_by_kind: dict[str, list[str]] = defaultdict(list)
    for node in detail.children:
        if node.kind in kinds:
            ids_by_kind[node.kind].append(node.id)
    for kind in kinds:
        ids = ids_by_kind.get(kind)
        if ids:
            append_kv(text, f"Linked {kind}s", ", ".join(ids[:8]))


def append_artifact_groups(
    text: Text,
    detail: ArtifactDetailWire,
    groups: tuple[tuple[str, tuple[str, ...]], ...],
) -> None:
    grouped = _semantic_artifact_ids(detail)
    for label, aliases in groups:
        ids: list[str] = []
        seen: set[str] = set()
        for alias in aliases:
            for artifact_id in grouped.get(alias, []):
                if artifact_id in seen:
                    continue
                seen.add(artifact_id)
                ids.append(artifact_id)
        if ids:
            append_kv(text, f"Linked {label}", ", ".join(ids[:8]))


def append_created_artifacts(text: Text, detail: ArtifactDetailWire) -> None:
    created_ids: list[str] = []
    node_id = detail.node.id if detail.node is not None else None
    for link in detail.outbound_links:
        if link.link_type == "created" and link.source_id == node_id:
            created_ids.append(link.target_id)
    if created_ids:
        append_kv(text, "Created artifacts", ", ".join(created_ids[:8]))


def _semantic_artifact_ids(detail: ArtifactDetailWire) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for child in detail.children:
        for key in _semantic_keys_for_node(child):
            grouped[key].append(child.id)
    return grouped


def _semantic_keys_for_node(node: ArtifactNodeWire) -> set[str]:
    keys = {_normalize_semantic_key(node.kind)}
    for metadata_key in (
        "artifact_type",
        "payload_type",
        "role",
        "type",
        "kind",
        "source_kind",
    ):
        value = node.metadata.get(metadata_key)
        if isinstance(value, str):
            keys.add(_normalize_semantic_key(value))

    searchable = " ".join(
        part
        for part in (node.id, node.display_title, node.subtitle, node.search_text)
        if part
    ).casefold()
    for marker, key in (
        ("plan", "plan"),
        ("question", "question"),
        ("hitl", "question"),
        ("transcript", "transcript"),
        ("conversation", "conversation"),
        ("chat", "chat"),
        ("diff", "diff"),
        ("patch", "patch"),
        ("delta", "delta"),
    ):
        if marker in searchable:
            keys.add(key)
    return keys


def _normalize_semantic_key(value: str) -> str:
    return value.casefold().replace("-", "_").replace(" ", "_")


def append_payload_types(text: Text, payloads: list[ArtifactPayloadWire]) -> None:
    if payloads:
        append_kv(
            text,
            "Artifact payloads",
            ", ".join(sorted({payload.payload_type for payload in payloads})),
        )


def append_selected_metadata(
    text: Text, metadata: Mapping[str, Any], keys: Iterable[str]
) -> None:
    ordered_keys = tuple(keys)
    key_set = set(ordered_keys)
    for key in ordered_keys:
        append_kv(text, _label_from_key(key), metadata.get(key))
    remaining = {key: value for key, value in metadata.items() if key not in key_set}
    if remaining:
        text.append("\nOther metadata\n", style="bold")
        append_metadata_mapping(text, remaining)


def append_metadata_mapping(text: Text, metadata: Mapping[str, Any]) -> None:
    for key in sorted(metadata):
        append_kv(text, _label_from_key(key), metadata[key])


def append_kv(text: Text, label: str, value: Any) -> None:
    if value is None or value == "" or value == [] or value == {}:
        return
    text.append(f"{label}: ", style="bold")
    text.append(f"{_format_value(value)}\n")


def with_empty_notice(text: Text) -> Text:
    if len(text.plain.splitlines()) <= 1:
        text.append("No kind-specific metadata available.\n", style="dim italic")
    return text


def metadata_value(metadata: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = metadata.get(key)
        if value is not None and value != "":
            return value
    return None


def path_from_node(node: ArtifactNodeWire) -> str | None:
    value = metadata_value(node.metadata, "path", "file_path", "abs_path")
    if value is None and node.kind == ARTIFACT_KIND_FILE and os.path.isabs(node.id):
        value = node.id
    if value is None:
        return None
    return str(value)


def peer_ids_for_link_type(detail: ArtifactDetailWire, link_type: str) -> list[str]:
    node = detail.node
    if node is None:
        return []
    peers: list[str] = []
    for link in [*detail.outbound_links, *detail.inbound_links]:
        if link.link_type != link_type:
            continue
        if link.source_id == node.id:
            peers.append(link.target_id)
        elif link.target_id == node.id:
            peers.append(link.source_id)
    return peers


def first_payload_value(
    payloads: list[ArtifactPayloadWire], preferred_keys: tuple[str, ...]
) -> Any:
    for payload in payloads:
        value = payload.payload
        if isinstance(value, Mapping):
            for key in preferred_keys:
                candidate = value.get(key)
                if candidate:
                    return candidate
        elif value:
            return value
    return None


def payload_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return _format_value(value)


def format_kind_counts(kinds: Iterable[str]) -> str:
    counts = Counter(kinds)
    if not counts:
        return "0"
    return ", ".join(f"{kind}={count}" for kind, count in sorted(counts.items()))


def _format_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool | int | float):
        return str(value)
    try:
        return json.dumps(value, sort_keys=True)
    except TypeError:
        return str(value)


def _label_from_key(key: str) -> str:
    return key.replace("_", " ").title()


def _join_compact(parts: Iterable[str | None]) -> str | None:
    values = [part for part in parts if part]
    return " / ".join(values) if values else None


def require_node(detail: ArtifactDetailWire) -> ArtifactNodeWire:
    node = detail.node
    assert node is not None
    return node
