"""Bounded exact-node ancestry hydration from immutable continuation refs."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from sase.core.continuation_wire import ContinuationNodeWire

from ..common import json_string
from ._load import (
    delayed_starter_parent_ids,
    iter_captured_nodes,
    load_agent_meta,
    load_captured_node_content,
)
from ._util import (
    BlockContent,
    ContinuationSourceError,
    MAX_HYDRATION_NODES,
    unique_strings,
)


@dataclass(frozen=True)
class _HydratedNode:
    node: ContinuationNodeWire
    content: BlockContent
    artifact_dir: Path


class ContinuationNodeIndex:
    """Resolve exact continuation nodes without rediscovering family aliases."""

    def __init__(self) -> None:
        self._by_id: dict[str, _HydratedNode] = {}
        self._observed: set[Path] = set()
        self.omissions: list[dict[str, str | None]] = []

    def observe_dir(self, artifact_dir: Path | None) -> None:
        if artifact_dir is None:
            return
        resolved = artifact_dir.expanduser().resolve(strict=False)
        if resolved in self._observed or not resolved.is_dir():
            return
        self._observed.add(resolved)
        meta = load_agent_meta(resolved)
        self._index_dir(resolved, meta)
        starter = json_string(meta, "monitor_starter_artifacts_dir")
        if starter:
            self.observe_dir(Path(starter))

    def observe_siblings(self, artifact_dir: Path | None) -> None:
        if artifact_dir is None:
            return
        parent = artifact_dir.expanduser().resolve(strict=False).parent
        if not parent.is_dir():
            return
        try:
            entries = list(parent.iterdir())
        except OSError:
            return
        for index, sibling in enumerate(entries):
            if index >= MAX_HYDRATION_NODES:
                break
            if sibling.is_dir() and (sibling / "continuation").is_dir():
                self.observe_dir(sibling)

    def resolve(self, node_id: str) -> _HydratedNode | None:
        return self._by_id.get(node_id)

    def _index_dir(self, artifact_dir: Path, meta: Mapping[str, object]) -> None:
        for raw_node in iter_captured_nodes(artifact_dir):
            node_id = raw_node.get("node_id")
            if not isinstance(node_id, str) or not node_id:
                continue
            hydrated_node = dict(raw_node)
            delayed = delayed_starter_parent_ids(artifact_dir, hydrated_node, meta=meta)
            if delayed:
                hydrated_node["parent_ids"] = delayed
            try:
                loaded = load_captured_node_content(
                    artifact_dir,
                    hydrated_node,
                    label=f"hydrated `{node_id}`",
                    meta=meta,
                )
            except ContinuationSourceError as exc:
                self.omissions.append(
                    {
                        "kind": exc.kind,
                        "node_id": node_id,
                        "parent_id": None,
                        "reason": str(exc),
                    }
                )
                continue
            if loaded is None:
                continue
            node, content = loaded
            existing = self._by_id.get(node_id)
            if existing is not None and existing.node != node:
                raise ContinuationSourceError(
                    "conflict",
                    f"conflicting continuation node {node_id}",
                )
            self._by_id[node_id] = _HydratedNode(
                node=node,
                content=content,
                artifact_dir=artifact_dir,
            )


def hydrate_missing_parents(
    records: Mapping[str, ContinuationNodeWire],
    index: ContinuationNodeIndex,
    *,
    max_depth: int = MAX_HYDRATION_NODES,
) -> tuple[list[_HydratedNode], list[dict[str, str | None]]]:
    """Walk persisted parent IDs and return nodes not already in *records*."""

    pending: deque[str] = deque()
    seen = set(records)
    for node in records.values():
        for parent_id in unique_strings(node.get("parent_ids") or []):
            if parent_id not in seen:
                pending.append(parent_id)
    hydrated: list[_HydratedNode] = []
    visited = 0
    while pending and visited < max_depth:
        parent_id = pending.popleft()
        if parent_id in seen:
            continue
        visited += 1
        loaded = index.resolve(parent_id)
        if loaded is None:
            continue
        seen.add(parent_id)
        hydrated.append(loaded)
        for grandparent_id in unique_strings(loaded.node.get("parent_ids") or []):
            if grandparent_id not in seen:
                pending.append(grandparent_id)
    return hydrated, list(index.omissions)
