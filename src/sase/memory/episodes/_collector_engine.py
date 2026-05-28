"""Collector engine state and orchestration."""

from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path

from sase.ace.changespec.models import ChangeSpec
from sase.core.agent_scan_wire import AgentArtifactRecordWire, AgentArtifactScanWire
from sase.core.episode_wire import (
    EPISODE_WIRE_SCHEMA_VERSION,
    EpisodeEdgeWire,
    EpisodeEventWire,
    EpisodeNodeWire,
    EpisodeSourceRefWire,
)
from sase.memory.episodes._collector_changeschat import CollectorChatChangespecMixin
from sase.memory.episodes._collector_graph import CollectorGraphMixin
from sase.memory.episodes._collector_record import CollectorRecordMixin
from sase.memory.episodes._collector_seed import CollectorSeedMixin
from sase.memory.episodes._collector_utils import first_project_name
from sase.memory.episodes._models import (
    EpisodeDraft,
    EpisodeSelector,
    EpisodeChatTurnRef,
)
from sase.memory.episodes.source_refs import normalize_source_path, sort_source_refs


class EpisodeCollectorEngine(
    CollectorSeedMixin,
    CollectorRecordMixin,
    CollectorChatChangespecMixin,
    CollectorGraphMixin,
):
    def __init__(
        self,
        selector: EpisodeSelector,
        *,
        projects_root: Path,
        scan: AgentArtifactScanWire,
        repo_root: Path,
        component_artifact_keys: set[str] | None = None,
        component_chat_paths: set[str] | None = None,
        component_metadata: dict[str, str] | None = None,
    ) -> None:
        self.selector = selector
        self.projects_root = projects_root
        self.scan = scan
        self.repo_root = repo_root
        self.component_artifact_keys = component_artifact_keys
        self.component_chat_paths = component_chat_paths
        self.component_metadata = component_metadata or {}
        self.component_scope = (
            component_artifact_keys is not None or component_chat_paths is not None
        )

        self.records = sorted(
            scan.records,
            key=lambda record: (
                record.project_name,
                record.workflow_dir_name,
                record.timestamp,
                record.artifact_dir,
            ),
        )
        self.records_by_artifact = {
            normalize_source_path(record.artifact_dir): record
            for record in self.records
        }
        self.records_by_timestamp: dict[str, list[AgentArtifactRecordWire]] = (
            defaultdict(list)
        )
        self.records_by_agent: dict[str, list[AgentArtifactRecordWire]] = defaultdict(
            list
        )
        self.records_by_family: dict[str, list[AgentArtifactRecordWire]] = defaultdict(
            list
        )
        self.records_by_changespec: dict[str, list[AgentArtifactRecordWire]] = (
            defaultdict(list)
        )
        self.records_by_bead: dict[str, list[AgentArtifactRecordWire]] = defaultdict(
            list
        )
        self._index_records()

        self.sources_by_key: dict[tuple[str, str], EpisodeSourceRefWire] = {}
        self.nodes_by_id: dict[str, EpisodeNodeWire] = {}
        self.edges_by_key: dict[
            tuple[str, str, str, tuple[tuple[str, str], ...]], EpisodeEdgeWire
        ] = {}
        self.events_by_id: dict[str, EpisodeEventWire] = {}
        self.chat_turns_by_id: dict[str, EpisodeChatTurnRef] = {}
        self.warnings: set[str] = set()

        self.record_queue: deque[AgentArtifactRecordWire] = deque()
        self.chat_queue: deque[str] = deque()
        self.changespec_queue: deque[str] = deque()
        self.included_record_keys: set[str] = set()
        self.included_chat_paths: set[str] = set()
        self.included_changespec_names: set[str] = set()
        self.changespecs_by_name: dict[str, list[ChangeSpec]] | None = None

        self.root_source_id = ""
        self.root_node_id = ""
        self.project = selector.project or first_project_name(self.records) or "home"

    def collect(self) -> EpisodeDraft:
        self._seed()
        self._drain_queues()
        if not self.sources_by_key:
            raise ValueError("episode selector did not resolve to any sources")
        if not self.root_source_id:
            self.root_source_id = sort_source_refs(list(self.sources_by_key.values()))[
                0
            ].id
        if not self.root_node_id:
            self.root_node_id = sorted(self.nodes_by_id)[0]
        return self._build_draft()

    def collect_component(
        self,
        *,
        artifact_dirs: list[str],
        chat_paths: list[str],
    ) -> EpisodeDraft:
        self._seed_component(artifact_dirs=artifact_dirs, chat_paths=chat_paths)
        self._drain_queues()
        if not self.sources_by_key:
            raise ValueError("episode component plan did not resolve to any sources")
        if not self.root_source_id:
            self.root_source_id = sort_source_refs(list(self.sources_by_key.values()))[
                0
            ].id
        if not self.root_node_id:
            self.root_node_id = sorted(self.nodes_by_id)[0]
        return self._build_draft()

    def _build_draft(self) -> EpisodeDraft:
        sources = sort_source_refs(list(self.sources_by_key.values()))
        return EpisodeDraft(
            schema_version=EPISODE_WIRE_SCHEMA_VERSION,
            project=self.project,
            selector_kind=self.selector.selector_kind(),
            selector_value=self.selector.selector_value(),
            root_source_id=self.root_source_id,
            root_node_id=self.root_node_id,
            sources=sources,
            nodes=sorted(self.nodes_by_id.values(), key=lambda node: node.id),
            edges=sorted(self.edges_by_key.values(), key=lambda edge: edge.id),
            events=sorted(
                self.events_by_id.values(),
                key=lambda event: (event.timestamp or "", event.id),
            ),
            chat_turns=sorted(
                self.chat_turns_by_id.values(),
                key=lambda turn: turn.id,
            ),
            metadata={
                "agent_record_count": str(len(self.included_record_keys)),
                "chat_count": str(len(self.included_chat_paths)),
                "changespec_count": str(len(self.included_changespec_names)),
                **self.component_metadata,
            },
            warnings=sorted(self.warnings),
        )
