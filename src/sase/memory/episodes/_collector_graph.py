"""Graph/source mutation helpers for episode collection."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any

from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.core.episode_wire import (
    EpisodeEdgeWire,
    EpisodeEventWire,
    EpisodeNodeWire,
    EpisodeSourceRefWire,
)
from sase.memory.episodes._collector_utils import (
    compact_metadata,
    stable_id,
    timestamp_in_range,
)
from sase.memory.episodes._record_helpers import (
    record_display_name,
    record_family,
    record_role_suffix,
)
from sase.memory.episodes.source_refs import build_source_ref, normalize_source_path


class CollectorGraphMixin:
    def _ensure_agent_node(
        self: Any,
        record: AgentArtifactRecordWire,
        *,
        source_id: str | None = None,
    ) -> EpisodeNodeWire:
        return self._add_node(
            "agent_run",
            normalize_source_path(record.artifact_dir),
            label=record_display_name(record),
            source_id=source_id,
            metadata=compact_metadata(
                {
                    "project": record.project_name,
                    "workflow": record.workflow_dir_name,
                    "timestamp": record.timestamp,
                    "family": record_family(record),
                    "role_suffix": record_role_suffix(record),
                    "outcome": record.done.outcome if record.done else None,
                }
            ),
        )

    def _ensure_chat_node(self: Any, chat_path: str) -> EpisodeNodeWire:
        source = self._add_source(chat_path, "chat", label=Path(chat_path).name)
        return self._add_node(
            "chat",
            normalize_source_path(chat_path),
            label=Path(chat_path).name,
            source_id=source.id,
            metadata={"path": normalize_source_path(chat_path)},
        )

    def _ensure_changespec_node(self: Any, changespec_name: str) -> EpisodeNodeWire:
        return self._add_node(
            "changespec",
            changespec_name,
            label=changespec_name,
            metadata={"name": changespec_name},
        )

    def _ensure_bead_node(self: Any, bead_id: str) -> EpisodeNodeWire:
        return self._add_node("bead", bead_id, label=bead_id, metadata={"id": bead_id})

    def _add_bead_sources(self: Any, bead_id: str) -> list[EpisodeSourceRefWire]:
        paths: list[Path] = []
        issues = self.repo_root / "sdd" / "beads" / "issues.jsonl"
        if issues.exists():
            paths.append(issues)
        streams = self.repo_root / "sdd" / "beads" / "events" / "streams"
        bead_stream = streams / f"{bead_id}.jsonl"
        if bead_stream.exists():
            paths.append(bead_stream)
        root_id = bead_id.split(".", 1)[0]
        root_stream = streams / f"{root_id}.jsonl"
        if root_stream.exists() and root_stream not in paths:
            paths.append(root_stream)
        return [
            self._add_source(path, "bead", label=path.name)
            for path in sorted(paths, key=lambda item: str(item))
        ]

    def _add_marker_source(
        self: Any,
        record: AgentArtifactRecordWire,
        marker_name: str,
        *,
        kind: str = "artifact",
    ) -> EpisodeSourceRefWire | None:
        path = Path(record.artifact_dir) / marker_name
        if not path.exists():
            return None
        return self._add_source(path, kind, label=marker_name)

    def _add_source(
        self: Any,
        path: Path | str,
        kind: str,
        *,
        label: str | None = None,
    ) -> EpisodeSourceRefWire:
        ref_path = normalize_source_path(path)
        key = (kind, ref_path)
        existing = self.sources_by_key.get(key)
        if existing is not None:
            return existing
        source = build_source_ref(ref_path, kind, label=label)
        self.sources_by_key[key] = source
        return source

    def _add_file_node_for_source(
        self: Any,
        source: EpisodeSourceRefWire,
        parent_node: EpisodeNodeWire,
        kind: str,
    ) -> EpisodeNodeWire:
        node = self._add_node(
            kind,
            source.path,
            label=source.label or Path(source.path).name,
            source_id=source.id,
            metadata={"path": source.path, "exists": str(source.exists).lower()},
        )
        self._add_edge("source", parent_node.id, node.id, evidence_ids=[source.id])
        return node

    def _add_node(
        self: Any,
        kind: str,
        key: str,
        *,
        label: str | None = None,
        source_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> EpisodeNodeWire:
        node_id = stable_id("node", kind, key)
        new_metadata = metadata or {}
        existing = self.nodes_by_id.get(node_id)
        if existing is not None:
            merged = {**existing.metadata, **new_metadata}
            updated = replace(
                existing,
                label=existing.label or label,
                source_id=existing.source_id or source_id,
                metadata=dict(sorted(merged.items())),
            )
            self.nodes_by_id[node_id] = updated
            return updated
        node = EpisodeNodeWire(
            id=node_id,
            kind=kind,
            label=label,
            source_id=source_id,
            metadata=dict(sorted(new_metadata.items())),
        )
        self.nodes_by_id[node_id] = node
        return node

    def _add_edge(
        self: Any,
        kind: str,
        from_node_id: str,
        to_node_id: str,
        evidence_ids: Iterable[str],
        metadata: dict[str, str] | None = None,
    ) -> EpisodeEdgeWire:
        clean_metadata = tuple(sorted((metadata or {}).items()))
        key = (kind, from_node_id, to_node_id, clean_metadata)
        evidence = sorted({item for item in evidence_ids if item})
        existing = self.edges_by_key.get(key)
        if existing is not None:
            merged = sorted({*existing.evidence_ids, *evidence})
            updated = replace(existing, evidence_ids=merged)
            self.edges_by_key[key] = updated
            return updated
        edge_id = stable_id(
            "edge",
            kind,
            from_node_id,
            to_node_id,
            json.dumps(dict(clean_metadata), sort_keys=True),
        )
        edge = EpisodeEdgeWire(
            id=edge_id,
            from_node_id=from_node_id,
            to_node_id=to_node_id,
            kind=kind,
            evidence_ids=evidence,
            metadata=dict(clean_metadata),
        )
        self.edges_by_key[key] = edge
        return edge

    def _add_event(
        self: Any,
        kind: str,
        key: str,
        title: str,
        *,
        timestamp: str | None = None,
        description: str | None = None,
        evidence_ids: Iterable[str] = (),
    ) -> EpisodeEventWire:
        event_id = stable_id("event", kind, key)
        evidence = sorted({item for item in evidence_ids if item})
        existing = self.events_by_id.get(event_id)
        if existing is not None:
            updated = replace(
                existing,
                evidence_ids=sorted({*existing.evidence_ids, *evidence}),
            )
            self.events_by_id[event_id] = updated
            return updated
        event = EpisodeEventWire(
            id=event_id,
            kind=kind,
            title=title,
            timestamp=timestamp,
            description=description,
            evidence_ids=evidence,
        )
        self.events_by_id[event_id] = event
        return event

    def _source_for_node(self: Any, node: EpisodeNodeWire) -> str | None:
        return node.source_id

    def _record_matches_transitive_bounds(
        self: Any,
        record: AgentArtifactRecordWire,
    ) -> bool:
        if self.component_scope:
            return True
        if self.selector.explicit_selector_count() > 0:
            return True
        if (
            self.selector.project is not None
            and record.project_name != self.selector.project
        ):
            return False
        return timestamp_in_range(
            record.timestamp,
            since=self.selector.since,
            until=self.selector.until,
        )

    def _queue_record(self: Any, record: AgentArtifactRecordWire) -> bool:
        component_keys = self.component_artifact_keys
        record_key = normalize_source_path(record.artifact_dir)
        if component_keys is not None and record_key not in component_keys:
            return False
        if not self._record_matches_transitive_bounds(record):
            return False
        if record_key not in self.included_record_keys:
            self.record_queue.append(record)
        return True

    def _queue_chat(self: Any, chat_path: str) -> None:
        normalized = normalize_source_path(chat_path)
        component_paths = self.component_chat_paths
        if component_paths is not None and normalized not in component_paths:
            return
        if normalized not in self.included_chat_paths:
            self.chat_queue.append(normalized)

    def _queue_changespec(self: Any, changespec_name: str) -> None:
        if changespec_name not in self.included_changespec_names:
            self.changespec_queue.append(changespec_name)
