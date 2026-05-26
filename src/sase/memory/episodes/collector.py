"""Deterministic source-graph collector for episodic-memory drafts."""

from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, fields, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
import hashlib

from sase.ace.changespec.models import ChangeSpec, CommitEntry
from sase.ace.changespec.parser import parse_project_file_python
from sase.core.agent_artifact_facade import list_agent_artifacts
from sase.core.agent_scan_facade import scan_agent_artifacts
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    DoneMarkerWire,
    PendingQuestionMarkerWire,
    PlanPathMarkerWire,
    PromptStepMarkerWire,
    RunningMarkerWire,
    WaitingMarkerWire,
    WorkflowStateWire,
)
from sase.core.episode_facade import generate_episode_id
from sase.core.episode_wire import (
    EPISODE_WIRE_SCHEMA_VERSION,
    EpisodeEdgeWire,
    EpisodeEventWire,
    EpisodeNodeWire,
    EpisodeSourceRefWire,
    EpisodeWire,
)
from sase.history.chat import resolve_chat_file_path
from sase.memory.episodes.chat_parse import ParsedChatTranscript, parse_chat_transcript
from sase.memory.episodes.source_refs import (
    build_source_ref,
    normalize_source_path,
    sort_source_refs,
)


@dataclass(frozen=True)
class EpisodeSelector:
    """Selector for one deterministic source graph collection."""

    project: str | None = None
    agent: str | None = None
    artifact_dir: str | Path | None = None
    changespec: str | None = None
    chat: str | Path | None = None
    since: str | None = None
    until: str | None = None
    limit: int | None = None

    def explicit_selector_count(self) -> int:
        return sum(
            value is not None
            for value in (self.agent, self.artifact_dir, self.changespec, self.chat)
        )

    def selector_kind(self) -> str:
        if self.agent is not None:
            return "agent"
        if self.artifact_dir is not None:
            return "artifact_dir"
        if self.changespec is not None:
            return "changespec"
        if self.chat is not None:
            return "chat"
        return "project_scan"

    def selector_value(self) -> str | None:
        value: str | Path | None
        if self.agent is not None:
            value = self.agent
        elif self.artifact_dir is not None:
            value = self.artifact_dir
        elif self.changespec is not None:
            value = self.changespec
        elif self.chat is not None:
            value = self.chat
        else:
            value = self.project
        return str(value) if value is not None else None


@dataclass(frozen=True)
class _EpisodeChatTurnRef:
    """A bounded chat turn reference attached to a source graph."""

    id: str
    chat_source_id: str
    chat_path: str
    turn_index: int
    prompt_excerpt: str | None = None
    response_excerpt: str | None = None


@dataclass(frozen=True)
class EpisodeDraft:
    """In-memory collector output; storage/rendering happen in later phases."""

    schema_version: int
    project: str
    selector_kind: str
    selector_value: str | None
    root_source_id: str
    root_node_id: str
    sources: list[EpisodeSourceRefWire]
    nodes: list[EpisodeNodeWire]
    edges: list[EpisodeEdgeWire]
    events: list[EpisodeEventWire]
    chat_turns: list[_EpisodeChatTurnRef]
    metadata: dict[str, str]
    warnings: list[str]

    def to_json_dict(self) -> dict[str, Any]:
        """Return a deterministic JSON-safe projection of this draft."""

        return asdict(self)

    def to_json(self) -> str:
        """Serialize this draft in stable key order for byte-stability tests."""

        return (
            json.dumps(
                self.to_json_dict(),
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )

    def to_episode_wire(
        self,
        *,
        title: str = "Episode Draft",
        summary: str = "Collected deterministic source graph.",
    ) -> EpisodeWire:
        """Project the draft graph to an ``EpisodeWire`` without lessons."""

        episode_id = generate_episode_id(
            self.project,
            self.root_source_id,
            self.sources,
        )
        return EpisodeWire(
            schema_version=EPISODE_WIRE_SCHEMA_VERSION,
            episode_id=episode_id,
            project=self.project,
            title=title,
            summary=summary,
            root_source_id=self.root_source_id,
            sources=self.sources,
            nodes=self.nodes,
            edges=self.edges,
            events=self.events,
            lessons=[],
            metadata={
                **self.metadata,
                "selector_kind": self.selector_kind,
                "selector_value": self.selector_value or "",
            },
        )


def collect_episode_draft(
    selector: EpisodeSelector | None = None,
    *,
    projects_root: Path | str | None = None,
    scan: AgentArtifactScanWire | None = None,
    repo_root: Path | str | None = None,
) -> EpisodeDraft:
    """Collect one deterministic source graph from agent/chat/ChangeSpec inputs."""

    selected = selector or EpisodeSelector()
    if selected.explicit_selector_count() > 1:
        raise ValueError("specify only one of agent, artifact_dir, changespec, or chat")
    root = (
        Path(projects_root).expanduser()
        if projects_root is not None
        else Path.home() / ".sase" / "projects"
    )
    snapshot = scan if scan is not None else _scan_projects(root)
    collector = _EpisodeCollector(
        selected,
        projects_root=root,
        scan=snapshot,
        repo_root=Path(repo_root).expanduser() if repo_root is not None else Path.cwd(),
    )
    return collector.collect()


def _scan_projects(projects_root: Path) -> AgentArtifactScanWire:
    return scan_agent_artifacts(
        projects_root,
        AgentArtifactScanOptionsWire(
            include_prompt_step_markers=True,
            include_raw_prompt_snippets=False,
            include_done_markers=True,
            include_workflow_state=True,
            include_waiting=True,
        ),
    )


class _EpisodeCollector:
    def __init__(
        self,
        selector: EpisodeSelector,
        *,
        projects_root: Path,
        scan: AgentArtifactScanWire,
        repo_root: Path,
    ) -> None:
        self.selector = selector
        self.projects_root = projects_root
        self.scan = scan
        self.repo_root = repo_root

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
        self.chat_turns_by_id: dict[str, _EpisodeChatTurnRef] = {}
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
        self.project = selector.project or _first_project_name(self.records) or "home"

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

    def _index_records(self) -> None:
        for record in self.records:
            self.records_by_timestamp[record.timestamp].append(record)
            for name in _record_agent_names(record):
                self.records_by_agent[name].append(record)
            family = _record_family(record)
            if family:
                self.records_by_family[family].append(record)
            for changespec in _record_changespec_names(record):
                self.records_by_changespec[changespec].append(record)
            for bead_id in _record_bead_ids(record):
                self.records_by_bead[bead_id].append(record)

    def _seed(self) -> None:
        if self.selector.agent is not None:
            self._seed_agent(self.selector.agent)
            return
        if self.selector.artifact_dir is not None:
            self._seed_artifact_dir(self.selector.artifact_dir)
            return
        if self.selector.changespec is not None:
            self._seed_changespec(self.selector.changespec)
            return
        if self.selector.chat is not None:
            self._seed_chat(self.selector.chat)
            return
        self._seed_project_scan()

    def _seed_agent(self, agent_name: str) -> None:
        matches = list(self.records_by_agent.get(agent_name, []))
        matches.extend(self.records_by_family.get(agent_name, []))
        matches = _dedupe_records(matches)
        if not matches:
            raise ValueError(f"agent not found in artifact scan: {agent_name}")
        for record in _limit_records(matches, self.selector.limit):
            self._queue_record(record)

    def _seed_artifact_dir(self, artifact_dir: str | Path) -> None:
        key = normalize_source_path(artifact_dir)
        record = self.records_by_artifact.get(key)
        if record is None:
            record = _record_from_artifact_dir(Path(key), self.projects_root)
            self.records_by_artifact[key] = record
            self.records_by_timestamp[record.timestamp].append(record)
        self._queue_record(record)

    def _seed_changespec(self, changespec_name: str) -> None:
        if not self._changespecs_named(changespec_name):
            raise ValueError(f"ChangeSpec not found: {changespec_name}")
        self._queue_changespec(changespec_name)
        for record in self.records_by_changespec.get(changespec_name, []):
            self._queue_record(record)

    def _seed_chat(self, chat: str | Path) -> None:
        chat_path = _resolve_chat_selector(chat)
        self._queue_chat(chat_path)
        for record in self._records_for_chat(chat_path):
            self._queue_record(record)

    def _seed_project_scan(self) -> None:
        records = [
            record
            for record in self.records
            if (
                self.selector.project is None
                or record.project_name == self.selector.project
            )
            and _timestamp_in_range(
                record.timestamp,
                since=self.selector.since,
                until=self.selector.until,
            )
        ]
        for record in _limit_records(records, self.selector.limit):
            self._queue_record(record)

    def _drain_queues(self) -> None:
        while self.record_queue or self.chat_queue or self.changespec_queue:
            while self.record_queue:
                self._include_record(self.record_queue.popleft())
            while self.chat_queue:
                self._include_chat(self.chat_queue.popleft())
            while self.changespec_queue:
                self._include_changespec(self.changespec_queue.popleft())

    def _include_record(self, record: AgentArtifactRecordWire) -> None:
        record_key = normalize_source_path(record.artifact_dir)
        if record_key in self.included_record_keys:
            return
        self.included_record_keys.add(record_key)
        self.project = self.selector.project or record.project_name

        agent_source = self._add_marker_source(record, "agent_meta.json")
        done_source = self._add_marker_source(record, "done.json")
        source_id = (
            agent_source.id
            if agent_source is not None
            else done_source.id
            if done_source is not None
            else None
        )
        agent_node = self._ensure_agent_node(record, source_id=source_id)
        if not self.root_node_id:
            self.root_node_id = agent_node.id
        if not self.root_source_id and source_id is not None:
            self.root_source_id = source_id

        self._add_agent_events(record, agent_node, source_id)
        self._add_artifact_dir_sources(record, agent_node)
        self._add_record_paths(record, agent_node)
        self._add_prompt_step_links(record, agent_node)
        self._add_record_changespec_links(record, agent_node)
        self._add_record_bead_links(record, agent_node)
        self._queue_related_records(record, agent_node)

    def _include_chat(self, chat_path: str) -> None:
        normalized = normalize_source_path(chat_path)
        if normalized in self.included_chat_paths:
            return
        self.included_chat_paths.add(normalized)

        chat_source = self._add_source(normalized, "chat", label=Path(normalized).name)
        chat_node = self._add_node(
            "chat",
            normalized,
            label=Path(normalized).name,
            source_id=chat_source.id,
            metadata={"path": normalized},
        )
        if not self.root_source_id:
            self.root_source_id = chat_source.id
        if not self.root_node_id:
            self.root_node_id = chat_node.id

        parsed = parse_chat_transcript(normalized)
        self._add_chat_turns(parsed, chat_node, chat_source)
        for linked_path in parsed.linked_chat_paths:
            linked_node = self._ensure_chat_node(linked_path)
            self._add_edge(
                "linked_chat",
                chat_node.id,
                linked_node.id,
                evidence_ids=[chat_source.id],
            )
            self._queue_chat(linked_path)
            for record in self._records_for_chat(linked_path):
                self._queue_record(record)
        for fork_ref in parsed.fork_refs:
            self._add_fork_ref(
                parsed,
                chat_node,
                chat_source,
                fork_ref_argument=fork_ref.argument,
                xprompt_name=fork_ref.xprompt_name,
                resolved_chat_path=fork_ref.resolved_chat_path,
            )

    def _include_changespec(self, changespec_name: str) -> None:
        if changespec_name in self.included_changespec_names:
            return
        changespecs = self._changespecs_named(changespec_name)
        if not changespecs:
            return
        self.included_changespec_names.add(changespec_name)
        for changespec in changespecs:
            source = self._add_source(
                changespec.file_path,
                "changespec",
                label=changespec.name,
            )
            node = self._add_node(
                "changespec",
                f"{changespec.file_path}:{changespec.name}",
                label=changespec.name,
                source_id=source.id,
                metadata={
                    "name": changespec.name,
                    "status": changespec.status,
                    "project": changespec.project_name,
                },
            )
            if not self.root_source_id:
                self.root_source_id = source.id
            if not self.root_node_id:
                self.root_node_id = node.id
            self._add_changespec_commit_links(changespec, node, source.id)
            self._add_changespec_events(changespec, node, source.id)

    def _add_agent_events(
        self,
        record: AgentArtifactRecordWire,
        agent_node: EpisodeNodeWire,
        source_id: str | None,
    ) -> None:
        evidence = [source_id] if source_id is not None else []
        started = _record_started_timestamp(record)
        if started is not None:
            self._add_event(
                "agent_start",
                f"{record.artifact_dir}:start",
                f"Agent {_record_display_name(record)} started",
                timestamp=started,
                evidence_ids=evidence,
            )
        done = record.done
        if done is not None and done.finished_at is not None:
            self._add_event(
                "agent_finish",
                f"{record.artifact_dir}:finish",
                f"Agent {_record_display_name(record)} finished",
                timestamp=_epoch_to_iso(done.finished_at),
                description=done.outcome,
                evidence_ids=evidence,
            )
        meta = record.agent_meta
        if meta is not None:
            for index, timestamp in enumerate(meta.feedback_submitted_at, 1):
                self._add_event(
                    "feedback",
                    f"{record.artifact_dir}:feedback:{index}",
                    f"Feedback round {index}",
                    timestamp=timestamp,
                    evidence_ids=evidence,
                )
            for index, timestamp in enumerate(meta.questions_submitted_at, 1):
                self._add_event(
                    "question_answer",
                    f"{record.artifact_dir}:question:{index}",
                    f"Question round {index}",
                    timestamp=timestamp,
                    evidence_ids=evidence,
                )
            for index, timestamp in enumerate(meta.retry_started_at, 1):
                self._add_event(
                    "retry",
                    f"{record.artifact_dir}:retry:{index}",
                    f"Retry started {index}",
                    timestamp=timestamp,
                    evidence_ids=evidence,
                )

    def _add_artifact_dir_sources(
        self,
        record: AgentArtifactRecordWire,
        agent_node: EpisodeNodeWire,
    ) -> None:
        for marker_name in (
            "running.json",
            "waiting.json",
            "pending_question.json",
            "workflow_state.json",
            "plan_path.json",
            "raw_xprompt.md",
            "submitted_xprompt.md",
            "dynamic_memory.json",
            "memory_reads.jsonl",
            "episode_trace.json",
        ):
            source = self._add_marker_source(record, marker_name)
            if source is not None:
                self._add_file_node_for_source(source, agent_node, "artifact")
        for source_path, kind in (
            ("plan_feedback.jsonl", "feedback"),
            ("qa_log.jsonl", "question"),
        ):
            source = self._add_marker_source(record, source_path, kind=kind)
            if source is not None:
                node = self._add_file_node_for_source(source, agent_node, kind)
                self._add_edge(kind, agent_node.id, node.id, evidence_ids=[source.id])
        artifact_dir = Path(record.artifact_dir)
        for path in sorted(artifact_dir.glob("followup_prompt*.md")):
            source = self._add_source(path, "artifact", label=path.name)
            self._add_file_node_for_source(source, agent_node, "artifact")
        for path in sorted(artifact_dir.glob("prompt_step_*.json")):
            source = self._add_source(path, "workflow_step", label=path.name)
            self._add_file_node_for_source(source, agent_node, "workflow_step")

    def _add_record_paths(
        self,
        record: AgentArtifactRecordWire,
        agent_node: EpisodeNodeWire,
    ) -> None:
        raw_meta = _read_json_object(Path(record.artifact_dir) / "agent_meta.json")
        raw_done = _read_json_object(Path(record.artifact_dir) / "done.json")

        for chat_path in _record_chat_paths(record, raw_meta):
            chat_node = self._ensure_chat_node(chat_path)
            chat_source = self._source_for_node(chat_node)
            self._add_edge(
                "response_chat",
                agent_node.id,
                chat_node.id,
                evidence_ids=[chat_source] if chat_source else [],
            )
            self._queue_chat(chat_path)

        for path, kind, edge_kind in _record_referenced_paths(
            record, raw_meta, raw_done
        ):
            source = self._add_source(path, kind, label=Path(path).name)
            node = self._add_file_node_for_source(source, agent_node, kind)
            self._add_edge(edge_kind, agent_node.id, node.id, evidence_ids=[source.id])

        try:
            artifacts = list_agent_artifacts(record.artifact_dir)
        except (OSError, ValueError, json.JSONDecodeError):
            artifacts = []
        for artifact in artifacts:
            source = self._add_source(
                artifact.path,
                artifact.kind,
                label=artifact.label,
            )
            node = self._add_file_node_for_source(source, agent_node, artifact.kind)
            self._add_edge("artifact", agent_node.id, node.id, evidence_ids=[source.id])

    def _add_prompt_step_links(
        self,
        record: AgentArtifactRecordWire,
        agent_node: EpisodeNodeWire,
    ) -> None:
        for step in sorted(record.prompt_steps, key=lambda item: item.file_name):
            step_source = self._add_marker_source(
                record,
                step.file_name,
                kind="workflow_step",
            )
            step_node = self._add_node(
                "workflow_step",
                f"{record.artifact_dir}:{step.file_name}",
                label=step.step_name,
                source_id=step_source.id if step_source is not None else None,
                metadata={
                    "workflow": step.workflow_name,
                    "step_type": step.step_type,
                    "status": step.status,
                },
            )
            self._add_edge(
                "workflow_step",
                agent_node.id,
                step_node.id,
                evidence_ids=[step_source.id] if step_source is not None else [],
            )
            if step.response_path:
                chat_node = self._ensure_chat_node(step.response_path)
                self._add_edge(
                    "workflow_step_chat",
                    step_node.id,
                    chat_node.id,
                    evidence_ids=[step_source.id] if step_source is not None else [],
                )
                self._queue_chat(step.response_path)
            if step.diff_path:
                source = self._add_source(step.diff_path, "artifact", label="diff")
                file_node = self._add_file_node_for_source(
                    source, step_node, "artifact"
                )
                self._add_edge("diff", step_node.id, file_node.id, [source.id])
            if step.artifacts_dir:
                target = self.records_by_artifact.get(
                    normalize_source_path(step.artifacts_dir)
                )
                if target is not None:
                    target_node = self._ensure_agent_node(target)
                    self._add_edge(
                        "workflow_step_agent",
                        step_node.id,
                        target_node.id,
                        evidence_ids=[step_source.id]
                        if step_source is not None
                        else [],
                    )
                    self._queue_record(target)

    def _add_record_changespec_links(
        self,
        record: AgentArtifactRecordWire,
        agent_node: EpisodeNodeWire,
    ) -> None:
        for changespec_name in _record_changespec_names(record):
            cs_node = self._ensure_changespec_node(changespec_name)
            self._add_edge("changespec", agent_node.id, cs_node.id, evidence_ids=[])
            self._queue_changespec(changespec_name)
            for related in self.records_by_changespec.get(changespec_name, []):
                self._queue_record(related)

    def _add_record_bead_links(
        self,
        record: AgentArtifactRecordWire,
        agent_node: EpisodeNodeWire,
    ) -> None:
        for bead_id in _record_bead_ids(record):
            bead_node = self._ensure_bead_node(bead_id)
            evidence_ids = [source.id for source in self._add_bead_sources(bead_id)]
            self._add_edge(
                "bead", agent_node.id, bead_node.id, evidence_ids=evidence_ids
            )
            for related in self.records_by_bead.get(bead_id, []):
                self._queue_record(related)

    def _queue_related_records(
        self,
        record: AgentArtifactRecordWire,
        agent_node: EpisodeNodeWire,
    ) -> None:
        for kind, timestamp in _record_related_timestamps(record):
            for related in self.records_by_timestamp.get(timestamp, []):
                related_node = self._ensure_agent_node(related)
                if kind in {"parent_agent", "retry_of"}:
                    from_node_id, to_node_id = related_node.id, agent_node.id
                else:
                    from_node_id, to_node_id = agent_node.id, related_node.id
                self._add_edge(kind, from_node_id, to_node_id, evidence_ids=[])
                self._queue_record(related)

        family = _record_family(record)
        if family:
            for related in self.records_by_family.get(family, []):
                if related.artifact_dir == record.artifact_dir:
                    continue
                related_node = self._ensure_agent_node(related)
                self._add_edge(
                    "agent_family",
                    agent_node.id,
                    related_node.id,
                    evidence_ids=[],
                    metadata={"family": family},
                )
                self._queue_record(related)

    def _add_chat_turns(
        self,
        parsed: ParsedChatTranscript,
        chat_node: EpisodeNodeWire,
        chat_source: EpisodeSourceRefWire,
    ) -> None:
        for turn in parsed.turns:
            turn_key = f"{parsed.path}:{turn.turn_index}"
            turn_node = self._add_node(
                "chat_turn",
                turn_key,
                label=f"Turn {turn.turn_index}",
                source_id=chat_source.id,
                metadata=_compact_metadata(
                    {
                        "turn_index": str(turn.turn_index),
                        "prompt_excerpt": turn.prompt_excerpt,
                        "response_excerpt": turn.response_excerpt,
                    }
                ),
            )
            self._add_edge(
                "contains_turn",
                chat_node.id,
                turn_node.id,
                evidence_ids=[chat_source.id],
            )
            draft_turn = _EpisodeChatTurnRef(
                id=turn_node.id,
                chat_source_id=chat_source.id,
                chat_path=parsed.path,
                turn_index=turn.turn_index,
                prompt_excerpt=turn.prompt_excerpt,
                response_excerpt=turn.response_excerpt,
            )
            self.chat_turns_by_id[draft_turn.id] = draft_turn

    def _add_fork_ref(
        self,
        parsed: ParsedChatTranscript,
        chat_node: EpisodeNodeWire,
        chat_source: EpisodeSourceRefWire,
        *,
        fork_ref_argument: str,
        xprompt_name: str,
        resolved_chat_path: str | None,
    ) -> None:
        if resolved_chat_path is not None:
            target = self._ensure_chat_node(resolved_chat_path)
            self._add_edge(
                xprompt_name,
                chat_node.id,
                target.id,
                evidence_ids=[chat_source.id],
                metadata={"argument": fork_ref_argument},
            )
            self._queue_chat(resolved_chat_path)
            return

        for record in _dedupe_records(
            [
                *self.records_by_agent.get(fork_ref_argument, []),
                *self.records_by_family.get(fork_ref_argument, []),
            ]
        ):
            target = self._ensure_agent_node(record)
            self._add_edge(
                xprompt_name,
                chat_node.id,
                target.id,
                evidence_ids=[chat_source.id],
                metadata={"argument": fork_ref_argument},
            )
            self._queue_record(record)

    def _add_changespec_commit_links(
        self,
        changespec: ChangeSpec,
        changespec_node: EpisodeNodeWire,
        source_id: str,
    ) -> None:
        for commit in sorted(
            changespec.commits or [],
            key=lambda entry: (entry.number, entry.proposal_letter or ""),
        ):
            commit_key = f"{changespec.name}:{commit.display_number}"
            commit_node = self._add_node(
                "commit",
                commit_key,
                label=f"{changespec.name} ({commit.display_number})",
                source_id=source_id,
                metadata={
                    "changespec": changespec.name,
                    "entry": commit.display_number,
                    "note": commit.note,
                },
            )
            self._add_edge(
                "changespec_commit",
                changespec_node.id,
                commit_node.id,
                evidence_ids=[source_id],
            )
            self._add_commit_paths(commit, commit_node, source_id)

    def _add_commit_paths(
        self,
        commit: CommitEntry,
        commit_node: EpisodeNodeWire,
        changespec_source_id: str,
    ) -> None:
        if commit.chat:
            chat_path = _resolve_chat_selector(commit.chat)
            chat_node = self._ensure_chat_node(chat_path)
            self._add_edge(
                "changespec_chat",
                commit_node.id,
                chat_node.id,
                evidence_ids=[changespec_source_id],
            )
            self._queue_chat(chat_path)
            for record in self._records_for_chat(chat_path):
                self._queue_record(record)
        for path, kind, edge_kind in (
            (commit.diff, "artifact", "changespec_diff"),
            (commit.plan, "plan", "changespec_plan"),
        ):
            if path:
                source = self._add_source(path, kind, label=Path(path).name)
                node = self._add_file_node_for_source(source, commit_node, kind)
                self._add_edge(edge_kind, commit_node.id, node.id, [source.id])

    def _add_changespec_events(
        self,
        changespec: ChangeSpec,
        changespec_node: EpisodeNodeWire,
        source_id: str,
    ) -> None:
        for entry in sorted(
            changespec.timestamps or [],
            key=lambda item: (item.timestamp, item.event_type, item.detail),
        ):
            self._add_event(
                "changespec",
                f"{changespec.name}:{entry.timestamp}:{entry.event_type}:{entry.detail}",
                f"{entry.event_type} {entry.detail}".strip(),
                timestamp=_normalize_event_timestamp(entry.timestamp),
                evidence_ids=[source_id],
            )

    def _records_for_chat(self, chat_path: str) -> list[AgentArtifactRecordWire]:
        normalized = normalize_source_path(chat_path)
        matches: list[AgentArtifactRecordWire] = []
        for record in self.records:
            raw_meta = _read_json_object(Path(record.artifact_dir) / "agent_meta.json")
            for candidate in _record_chat_paths(record, raw_meta):
                if normalize_source_path(candidate) == normalized:
                    matches.append(record)
                    break
        return _dedupe_records(matches)

    def _changespecs_named(self, name: str) -> list[ChangeSpec]:
        if self.changespecs_by_name is None:
            self.changespecs_by_name = self._load_changespecs()
        return self.changespecs_by_name.get(name, [])

    def _load_changespecs(self) -> dict[str, list[ChangeSpec]]:
        by_name: dict[str, list[ChangeSpec]] = defaultdict(list)
        for project_file in _iter_project_files(self.projects_root):
            for changespec in parse_project_file_python(str(project_file)):
                by_name[changespec.name].append(changespec)
        for changespecs in by_name.values():
            changespecs.sort(key=lambda cs: (cs.file_path, cs.line_number))
        return by_name

    def _ensure_agent_node(
        self,
        record: AgentArtifactRecordWire,
        *,
        source_id: str | None = None,
    ) -> EpisodeNodeWire:
        return self._add_node(
            "agent_run",
            normalize_source_path(record.artifact_dir),
            label=_record_display_name(record),
            source_id=source_id,
            metadata=_compact_metadata(
                {
                    "project": record.project_name,
                    "workflow": record.workflow_dir_name,
                    "timestamp": record.timestamp,
                    "family": _record_family(record),
                    "role_suffix": _record_role_suffix(record),
                    "outcome": record.done.outcome if record.done else None,
                }
            ),
        )

    def _ensure_chat_node(self, chat_path: str) -> EpisodeNodeWire:
        source = self._add_source(chat_path, "chat", label=Path(chat_path).name)
        return self._add_node(
            "chat",
            normalize_source_path(chat_path),
            label=Path(chat_path).name,
            source_id=source.id,
            metadata={"path": normalize_source_path(chat_path)},
        )

    def _ensure_changespec_node(self, changespec_name: str) -> EpisodeNodeWire:
        return self._add_node(
            "changespec",
            changespec_name,
            label=changespec_name,
            metadata={"name": changespec_name},
        )

    def _ensure_bead_node(self, bead_id: str) -> EpisodeNodeWire:
        return self._add_node("bead", bead_id, label=bead_id, metadata={"id": bead_id})

    def _add_bead_sources(self, bead_id: str) -> list[EpisodeSourceRefWire]:
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
        self,
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
        self,
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
        self,
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
        self,
        kind: str,
        key: str,
        *,
        label: str | None = None,
        source_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> EpisodeNodeWire:
        node_id = _stable_id("node", kind, key)
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
        self,
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
        edge_id = _stable_id(
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
        self,
        kind: str,
        key: str,
        title: str,
        *,
        timestamp: str | None = None,
        description: str | None = None,
        evidence_ids: Iterable[str] = (),
    ) -> EpisodeEventWire:
        event_id = _stable_id("event", kind, key)
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

    def _source_for_node(self, node: EpisodeNodeWire) -> str | None:
        return node.source_id

    def _queue_record(self, record: AgentArtifactRecordWire) -> None:
        if normalize_source_path(record.artifact_dir) not in self.included_record_keys:
            self.record_queue.append(record)

    def _queue_chat(self, chat_path: str) -> None:
        normalized = normalize_source_path(chat_path)
        if normalized not in self.included_chat_paths:
            self.chat_queue.append(normalized)

    def _queue_changespec(self, changespec_name: str) -> None:
        if changespec_name not in self.included_changespec_names:
            self.changespec_queue.append(changespec_name)

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
            },
            warnings=sorted(self.warnings),
        )


def _record_agent_names(record: AgentArtifactRecordWire) -> list[str]:
    values = [
        record.agent_meta.name if record.agent_meta is not None else None,
        record.done.name if record.done is not None else None,
    ]
    return _unique_strings(values)


def _record_display_name(record: AgentArtifactRecordWire) -> str:
    names = _record_agent_names(record)
    return names[0] if names else record.timestamp


def _record_family(record: AgentArtifactRecordWire) -> str | None:
    meta = record.agent_meta
    if meta is None:
        return None
    return meta.agent_family or meta.workflow_name


def _record_role_suffix(record: AgentArtifactRecordWire) -> str | None:
    meta = record.agent_meta
    if meta is None:
        return None
    return meta.role_suffix or meta.agent_family_role


def _record_changespec_names(record: AgentArtifactRecordWire) -> list[str]:
    meta = record.agent_meta
    done = record.done
    values = [
        meta.changespec_name if meta is not None else None,
        meta.cl_name if meta is not None else None,
        meta.commit_changespec_name if meta is not None else None,
        done.cl_name if done is not None else None,
    ]
    return _unique_strings(values)


def _record_bead_ids(record: AgentArtifactRecordWire) -> list[str]:
    meta = record.agent_meta
    if meta is None:
        return []
    return _unique_strings(
        [
            meta.bead_id,
            meta.epic_bead_id,
            meta.phase_bead_id,
            meta.legend_bead_id,
        ]
    )


def _record_related_timestamps(
    record: AgentArtifactRecordWire,
) -> Iterator[tuple[str, str]]:
    meta = record.agent_meta
    done = record.done
    if meta is not None:
        for kind, timestamp in (
            ("parent_agent", meta.parent_timestamp),
            ("parent_agent", meta.parent_agent_timestamp),
            ("retry_of", meta.retry_of_timestamp),
            ("retry_root", meta.retry_chain_root_timestamp),
            ("retried_as", meta.retried_as_timestamp),
        ):
            if timestamp:
                yield kind, _compact_timestamp(timestamp)
    if done is not None:
        for kind, timestamp in (
            ("retry_root", done.retry_chain_root_timestamp),
            ("retried_as", done.retried_as_timestamp),
        ):
            if timestamp:
                yield kind, _compact_timestamp(timestamp)


def _record_chat_paths(
    record: AgentArtifactRecordWire,
    raw_meta: dict[str, Any],
) -> list[str]:
    paths: list[str | None] = [
        record.done.response_path if record.done is not None else None,
        _str_value(raw_meta.get("chat_path")),
    ]
    paths.extend(step.response_path for step in record.prompt_steps)
    return _unique_strings(paths)


def _record_referenced_paths(
    record: AgentArtifactRecordWire,
    raw_meta: dict[str, Any],
    raw_done: dict[str, Any],
) -> list[tuple[str, str, str]]:
    meta = record.agent_meta
    done = record.done
    paths: list[tuple[str | None, str, str]] = [
        (
            record.plan_path.plan_path if record.plan_path is not None else None,
            "plan",
            "plan",
        ),
        (meta.plan_path if meta is not None else None, "plan", "plan"),
        (meta.sdd_prompt_path if meta is not None else None, "plan", "plan"),
        (meta.sdd_plan_path if meta is not None else None, "plan", "plan"),
        (
            meta.question_request_path if meta is not None else None,
            "question",
            "question",
        ),
        (
            meta.question_response_path if meta is not None else None,
            "question",
            "question",
        ),
        (meta.commit_diff_path if meta is not None else None, "artifact", "diff"),
        (done.plan_path if done is not None else None, "plan", "plan"),
        (done.diff_path if done is not None else None, "artifact", "diff"),
        (done.output_path if done is not None else None, "artifact", "output"),
        (_str_value(raw_meta.get("chat_path")), "chat", "response_chat"),
        (
            _str_value(raw_meta.get("dynamic_memory_path")),
            "dynamic_memory",
            "memory_context",
        ),
        (
            _str_value(raw_meta.get("memory_reads_path")),
            "memory_read",
            "memory_context",
        ),
        (
            _str_value(raw_done.get("dynamic_memory_path")),
            "dynamic_memory",
            "memory_context",
        ),
        (
            _str_value(raw_done.get("memory_reads_path")),
            "memory_read",
            "memory_context",
        ),
    ]
    if done is not None:
        paths.extend((path, "image", "artifact") for path in done.image_paths)
        paths.extend((path, "pdf", "artifact") for path in done.markdown_pdf_paths)
    for key in ("source_paths", "artifact_paths"):
        paths.extend(
            (path, "artifact", "artifact") for path in _str_list(raw_done.get(key))
        )
        paths.extend(
            (path, "artifact", "artifact") for path in _str_list(raw_meta.get(key))
        )
    return [
        (path, kind, edge_kind)
        for path, kind, edge_kind in paths
        if path is not None and path
    ]


def _record_started_timestamp(record: AgentArtifactRecordWire) -> str | None:
    meta = record.agent_meta
    if meta is not None and meta.run_started_at:
        return meta.run_started_at
    return _timestamp_dir_to_iso(record.timestamp)


def _record_from_artifact_dir(
    artifact_dir: Path,
    projects_root: Path,
) -> AgentArtifactRecordWire:
    project_name, workflow_name = _project_workflow_from_artifact_dir(
        artifact_dir,
        projects_root,
    )
    agent_meta = _marker_from_json(AgentMetaWire, artifact_dir / "agent_meta.json")
    done = _marker_from_json(DoneMarkerWire, artifact_dir / "done.json")
    running = _marker_from_json(RunningMarkerWire, artifact_dir / "running.json")
    waiting = _marker_from_json(WaitingMarkerWire, artifact_dir / "waiting.json")
    pending = _marker_from_json(
        PendingQuestionMarkerWire,
        artifact_dir / "pending_question.json",
    )
    workflow_state = _marker_from_json(
        WorkflowStateWire,
        artifact_dir / "workflow_state.json",
    )
    plan_path = _marker_from_json(PlanPathMarkerWire, artifact_dir / "plan_path.json")
    prompt_steps = [
        marker
        for marker in (
            _marker_from_json(PromptStepMarkerWire, path)
            for path in sorted(artifact_dir.glob("prompt_step_*.json"))
        )
        if marker is not None
    ]
    project_dir = projects_root / project_name
    return AgentArtifactRecordWire(
        project_name=project_name,
        project_dir=str(project_dir),
        project_file=str(project_dir / f"{project_name}.sase"),
        workflow_dir_name=workflow_name,
        artifact_dir=str(artifact_dir),
        timestamp=artifact_dir.name,
        agent_meta=agent_meta,
        done=done,
        running=running,
        waiting=waiting,
        pending_question=pending,
        workflow_state=workflow_state,
        plan_path=plan_path,
        prompt_steps=prompt_steps,
        raw_prompt_snippet=None,
        has_done_marker=(artifact_dir / "done.json").exists(),
    )


def _marker_from_json[MarkerT](cls: type[MarkerT], path: Path) -> MarkerT | None:
    data = _read_json_object(path)
    if not data:
        return None
    allowed = {field.name for field in fields(cast(Any, cls))}
    filtered = {key: value for key, value in data.items() if key in allowed}
    if cls is PromptStepMarkerWire and "file_name" not in filtered:
        filtered["file_name"] = path.name
    try:
        return cls(**filtered)
    except TypeError:
        return None


def _project_workflow_from_artifact_dir(
    artifact_dir: Path,
    projects_root: Path,
) -> tuple[str, str]:
    try:
        relative = artifact_dir.resolve(strict=False).relative_to(
            projects_root.resolve(strict=False)
        )
    except ValueError:
        return "home", "ace-run"
    parts = relative.parts
    if len(parts) >= 4 and parts[1] == "artifacts":
        return parts[0], parts[2]
    return "home", "ace-run"


def _iter_project_files(projects_root: Path) -> Iterator[Path]:
    if not projects_root.is_dir():
        return
    seen: set[str] = set()
    for pattern in ("*.sase", "*.gp", "*-archive.sase", "*-archive.gp"):
        for path in sorted(projects_root.glob(f"*/{pattern}")):
            key = normalize_source_path(path)
            if key not in seen and path.is_file():
                seen.add(key)
                yield path


def _resolve_chat_selector(chat: str | Path) -> str:
    chat_text = str(chat)
    if chat_text.startswith("~") or chat_text.startswith("/") or "/" in chat_text:
        return normalize_source_path(chat_text)
    resolved = resolve_chat_file_path(chat_text)
    if resolved is not None:
        return normalize_source_path(resolved)
    if not chat_text.endswith(".md"):
        resolved_md = resolve_chat_file_path(f"{chat_text}.md")
        if resolved_md is not None:
            return normalize_source_path(resolved_md)
    return normalize_source_path(chat_text)


def _timestamp_in_range(
    timestamp: str,
    *,
    since: str | None,
    until: str | None,
) -> bool:
    comparable = _compact_timestamp(timestamp)
    if since is not None and comparable < _range_bound(since, end=False):
        return False
    if until is not None and comparable > _range_bound(until, end=True):
        return False
    return True


def _range_bound(value: str, *, end: bool) -> str:
    stripped = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", stripped):
        suffix = "235959" if end else "000000"
        return stripped.replace("-", "") + suffix
    return _compact_timestamp(stripped)


def _compact_timestamp(value: str) -> str:
    stripped = value.strip()
    if re.fullmatch(r"\d{14}", stripped):
        return stripped
    if re.fullmatch(r"\d{6}_\d{6}", stripped):
        try:
            return datetime.strptime(stripped, "%y%m%d_%H%M%S").strftime("%Y%m%d%H%M%S")
        except ValueError:
            return stripped.replace("_", "")
    return stripped.replace("_", "").replace("-", "").replace(":", "").replace("T", "")


def _timestamp_dir_to_iso(timestamp: str) -> str | None:
    try:
        parsed = datetime.strptime(timestamp, "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def _normalize_event_timestamp(timestamp: str) -> str:
    if re.fullmatch(r"\d{6}_\d{6}", timestamp):
        try:
            parsed = datetime.strptime(timestamp, "%y%m%d_%H%M%S")
        except ValueError:
            return timestamp
        return parsed.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
    return timestamp


def _epoch_to_iso(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds, UTC).isoformat().replace("+00:00", "Z")


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _first_project_name(records: list[AgentArtifactRecordWire]) -> str | None:
    return records[0].project_name if records else None


def _unique_strings(values: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None or value == "" or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _str_value(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _compact_metadata(values: dict[str, str | None]) -> dict[str, str]:
    return {
        key: value
        for key, value in sorted(values.items())
        if value is not None and value != ""
    }


def _dedupe_records(
    records: Iterable[AgentArtifactRecordWire],
) -> list[AgentArtifactRecordWire]:
    seen: set[str] = set()
    result: list[AgentArtifactRecordWire] = []
    for record in sorted(
        records,
        key=lambda item: (
            item.project_name,
            item.workflow_dir_name,
            item.timestamp,
            item.artifact_dir,
        ),
    ):
        key = normalize_source_path(record.artifact_dir)
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


def _limit_records(
    records: Iterable[AgentArtifactRecordWire],
    limit: int | None,
) -> list[AgentArtifactRecordWire]:
    ordered = _dedupe_records(records)
    return ordered if limit is None else ordered[:limit]


def _stable_id(prefix: str, *parts: str) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


__all__ = [
    "EpisodeDraft",
    "EpisodeSelector",
    "collect_episode_draft",
]
