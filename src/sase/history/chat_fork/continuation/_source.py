"""Bounded exact-node ancestry hydration from immutable continuation refs."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from sase.core.continuation_wire import ContinuationNodeWire

from ..common import json_string, load_json_object
from ._load import (
    delayed_starter_parent_ids,
    iter_captured_nodes,
    load_agent_meta,
    load_captured_node_content,
)
from ._refs import read_json_ref
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
    """Resolve exact continuation nodes without rediscovering agent-session aliases."""

    def __init__(self) -> None:
        self._by_id: dict[str, _HydratedNode] = {}
        self._observed: set[Path] = set()
        self.omissions: list[dict[str, str | None]] = []
        self._superseded_by_id: dict[str, Mapping[str, object]] = {}

    def observe_dir(self, artifact_dir: Path | None) -> None:
        if artifact_dir is None:
            return
        resolved = artifact_dir.expanduser().resolve(strict=False)
        if resolved in self._observed or not resolved.is_dir():
            return
        self._observed.add(resolved)
        meta = load_agent_meta(resolved)
        self._index_dir(resolved, meta)
        self._index_superseded_attempts(resolved)
        starter = json_string(meta, "monitor_starter_artifacts_dir")
        if starter:
            self.observe_dir(Path(starter))
        self._index_portable_parents(resolved, meta)

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

    def canonical_parent_ids(self, node: Mapping[str, object]) -> list[str]:
        """Splice same-run archived attempt edges out of *node*'s parents.

        A parent id proven to be an archived superseded attempt of the same
        run is replaced with that archived node's own canonical parents,
        recursively. Anything else is kept unchanged so unknown parents
        still reach the planner as ``missing_parent``.
        """

        child_run = _owner_run_id(node)
        initial = _node_parent_ids(node)
        if not child_run:
            return initial
        result: list[str] = []
        seen: set[str] = set()

        def _visit(parent_id: str, chain: frozenset[str]) -> None:
            if parent_id in chain:
                return
            archived = self._superseded_by_id.get(parent_id)
            if archived is not None and _owner_run_id(archived) == child_run:
                for sub_id in _node_parent_ids(archived):
                    _visit(sub_id, chain | {parent_id})
                return
            if parent_id not in seen:
                seen.add(parent_id)
                result.append(parent_id)

        for parent_id in initial:
            _visit(parent_id, frozenset())
        return result

    def _index_superseded_attempts(self, artifact_dir: Path) -> None:
        try:
            paths = sorted(
                (artifact_dir / "attempts").glob("*/continuation/nodes/*.json")
            )
        except OSError:
            return
        for path in paths[:MAX_HYDRATION_NODES]:
            payload = load_json_object(path)
            if not payload:
                continue
            node_id = payload.get("node_id")
            if not isinstance(node_id, str) or not node_id:
                continue
            self._superseded_by_id.setdefault(node_id, payload)

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

    def _index_portable_parents(
        self,
        artifact_dir: Path,
        meta: Mapping[str, object],
    ) -> None:
        refs: dict[str, str] = {}
        parent_map = meta.get("continuation_parent_portable_refs")
        if isinstance(parent_map, Mapping):
            for key, value in parent_map.items():
                if isinstance(key, str) and isinstance(value, str) and value:
                    refs[key] = value
        locators = load_json_object(
            artifact_dir / "continuation" / "portable_locators.json"
        )
        locator_map = locators.get("locators")
        if isinstance(locator_map, Mapping):
            for key, value in locator_map.items():
                if (
                    isinstance(key, str)
                    and isinstance(value, str)
                    and value.startswith("file:")
                    and not key.startswith("local:")
                ):
                    refs.setdefault(key, value)
        for node_id, ref in refs.items():
            if node_id in self._by_id:
                continue
            try:
                payload = read_json_ref(artifact_dir, ref)
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
            if payload.get("node_id") != node_id and payload.get("kind") is None:
                continue
            hydrated_node = dict(payload)
            if "node_id" not in hydrated_node:
                hydrated_node["node_id"] = node_id
            try:
                loaded = load_captured_node_content(
                    artifact_dir,
                    hydrated_node,
                    label=f"portable `{node_id}`",
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
            self._by_id[node_id] = _HydratedNode(
                node=node,
                content=content,
                artifact_dir=artifact_dir,
            )


def _node_parent_ids(node: Mapping[str, object]) -> list[str]:
    raw = node.get("parent_ids")
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        return unique_strings(raw)
    return []


def _owner_run_id(node: Mapping[str, object]) -> str:
    owner = node.get("owner")
    if not isinstance(owner, Mapping):
        return ""
    run_id = owner.get("run_id")
    return run_id if isinstance(run_id, str) else ""


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
        canonical = index.canonical_parent_ids(loaded.node)
        if list(loaded.node.get("parent_ids") or []) != canonical:
            loaded = _HydratedNode(
                node={**loaded.node, "parent_ids": canonical},  # type: ignore[typeddict-item]
                content=loaded.content,
                artifact_dir=loaded.artifact_dir,
            )
        seen.add(parent_id)
        hydrated.append(loaded)
        for grandparent_id in unique_strings(loaded.node.get("parent_ids") or []):
            if grandparent_id not in seen:
                pending.append(grandparent_id)
    return hydrated, list(index.omissions)
