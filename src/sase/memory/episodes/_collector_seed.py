"""Selector seeding and queue draining for episode collection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.memory.episodes._collector_utils import (
    dedupe_records,
    limit_records,
    resolve_chat_selector,
    timestamp_in_range,
)
from sase.memory.episodes._record_helpers import (
    record_agent_names,
    record_bead_ids,
    record_changespec_names,
    record_family,
    record_from_artifact_dir,
)
from sase.memory.episodes.chat_parse import parse_chat_transcript
from sase.memory.episodes.source_refs import normalize_source_path


class CollectorSeedMixin:
    def _index_records(self: Any) -> None:
        for record in self.records:
            self.records_by_timestamp[record.timestamp].append(record)
            for name in record_agent_names(record):
                self.records_by_agent[name].append(record)
            family = record_family(record)
            if family:
                self.records_by_family[family].append(record)
            for changespec in record_changespec_names(record):
                self.records_by_changespec[changespec].append(record)
            for bead_id in record_bead_ids(record):
                self.records_by_bead[bead_id].append(record)

    def _seed(self: Any) -> None:
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

    def _seed_agent(self: Any, agent_name: str) -> None:
        matches = list(self.records_by_agent.get(agent_name, []))
        matches.extend(self.records_by_family.get(agent_name, []))
        matches = dedupe_records(matches)
        if not matches:
            raise ValueError(f"agent not found in artifact scan: {agent_name}")
        for record in limit_records(matches, self.selector.limit):
            self._queue_record(record)

    def _seed_artifact_dir(self: Any, artifact_dir: str | Path) -> None:
        key = normalize_source_path(artifact_dir)
        record = self.records_by_artifact.get(key)
        if record is None:
            record = record_from_artifact_dir(Path(key), self.projects_root)
            self.records_by_artifact[key] = record
            self.records_by_timestamp[record.timestamp].append(record)
        self._queue_record(record)

    def _seed_changespec(self: Any, changespec_name: str) -> None:
        if not self._changespecs_named(changespec_name):
            raise ValueError(f"ChangeSpec not found: {changespec_name}")
        self._queue_changespec(changespec_name)
        for record in self.records_by_changespec.get(changespec_name, []):
            self._queue_record(record)

    def _seed_chat(self: Any, chat: str | Path) -> None:
        chat_path = resolve_chat_selector(chat)
        self._queue_chat(chat_path)
        for record in self._records_for_chat(chat_path):
            self._queue_record(record)

    def _seed_project_scan(self: Any) -> None:
        records = [
            record
            for record in self.records
            if (
                self.selector.project is None
                or record.project_name == self.selector.project
            )
            and timestamp_in_range(
                record.timestamp,
                since=self.selector.since,
                until=self.selector.until,
            )
        ]
        for record in limit_records(records, self.selector.limit):
            self._queue_record(record)

    def _drain_queues(self: Any) -> None:
        while self.record_queue or self.chat_queue or self.changespec_queue:
            while self.record_queue:
                self._include_record(self.record_queue.popleft())
            while self.chat_queue:
                self._include_chat(self.chat_queue.popleft())
            while self.changespec_queue:
                self._include_changespec(self.changespec_queue.popleft())

    def _include_record(self: Any, record: AgentArtifactRecordWire) -> None:
        record_key = normalize_source_path(record.artifact_dir)
        if record_key in self.included_record_keys:
            return
        self.included_record_keys.add(record_key)
        self.project = self.selector.project or record.project_name

        trace_source = self._add_marker_source(record, "episode_trace.json")
        agent_source = self._add_marker_source(record, "agent_meta.json")
        done_source = self._add_marker_source(record, "done.json")
        source_id = (
            trace_source.id
            if trace_source is not None
            else agent_source.id
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

    def _include_chat(self: Any, chat_path: str) -> None:
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

    def _include_changespec(self: Any, changespec_name: str) -> None:
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
