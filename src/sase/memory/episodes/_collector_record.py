"""Agent-record expansion methods for episode collection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_facade import list_agent_artifacts
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.core.episode_wire import EpisodeNodeWire
from sase.memory.episodes._collector_utils import epoch_to_iso, read_json_object
from sase.memory.episodes._record_helpers import (
    record_bead_ids,
    record_changespec_names,
    record_chat_paths,
    record_display_name,
    record_family,
    record_referenced_paths,
    record_related_timestamps,
    record_started_timestamp,
)
from sase.memory.episodes.source_refs import normalize_source_path


class CollectorRecordMixin:
    def _add_agent_events(
        self: Any,
        record: AgentArtifactRecordWire,
        agent_node: EpisodeNodeWire,
        source_id: str | None,
    ) -> None:
        evidence = [source_id] if source_id is not None else []
        started = record_started_timestamp(record)
        if started is not None:
            self._add_event(
                "agent_start",
                f"{record.artifact_dir}:start",
                f"Agent {record_display_name(record)} started",
                timestamp=started,
                evidence_ids=evidence,
            )
        done = record.done
        if done is not None and done.finished_at is not None:
            self._add_event(
                "agent_finish",
                f"{record.artifact_dir}:finish",
                f"Agent {record_display_name(record)} finished",
                timestamp=epoch_to_iso(done.finished_at),
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
        self: Any,
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
        self: Any,
        record: AgentArtifactRecordWire,
        agent_node: EpisodeNodeWire,
    ) -> None:
        raw_meta = read_json_object(Path(record.artifact_dir) / "agent_meta.json")
        raw_done = read_json_object(Path(record.artifact_dir) / "done.json")

        for chat_path in record_chat_paths(record, raw_meta):
            chat_node = self._ensure_chat_node(chat_path)
            chat_source = self._source_for_node(chat_node)
            self._add_edge(
                "response_chat",
                agent_node.id,
                chat_node.id,
                evidence_ids=[chat_source] if chat_source else [],
            )
            self._queue_chat(chat_path)

        for path, kind, edge_kind in record_referenced_paths(
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
        self: Any,
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
                if target is not None and self._queue_record(target):
                    target_node = self._ensure_agent_node(target)
                    self._add_edge(
                        "workflow_step_agent",
                        step_node.id,
                        target_node.id,
                        evidence_ids=[step_source.id]
                        if step_source is not None
                        else [],
                    )

    def _add_record_changespec_links(
        self: Any,
        record: AgentArtifactRecordWire,
        agent_node: EpisodeNodeWire,
    ) -> None:
        for changespec_name in record_changespec_names(record):
            cs_node = self._ensure_changespec_node(changespec_name)
            self._add_edge("changespec", agent_node.id, cs_node.id, evidence_ids=[])
            if self.component_scope:
                continue
            self._queue_changespec(changespec_name)
            for related in self.records_by_changespec.get(changespec_name, []):
                self._queue_record(related)

    def _add_record_bead_links(
        self: Any,
        record: AgentArtifactRecordWire,
        agent_node: EpisodeNodeWire,
    ) -> None:
        for bead_id in record_bead_ids(record):
            bead_node = self._ensure_bead_node(bead_id)
            evidence_ids = [source.id for source in self._add_bead_sources(bead_id)]
            self._add_edge(
                "bead", agent_node.id, bead_node.id, evidence_ids=evidence_ids
            )
            if self.component_scope:
                continue
            for related in self.records_by_bead.get(bead_id, []):
                self._queue_record(related)

    def _queue_related_records(
        self: Any,
        record: AgentArtifactRecordWire,
        agent_node: EpisodeNodeWire,
    ) -> None:
        record_key = normalize_source_path(record.artifact_dir)
        for kind, timestamp in record_related_timestamps(record):
            for related in self.records_by_timestamp.get(timestamp, []):
                related_key = normalize_source_path(related.artifact_dir)
                if related_key == record_key:
                    continue
                if not self._queue_record(related):
                    continue
                related_node = self._ensure_agent_node(related)
                if kind in {"parent_agent", "retry_of"}:
                    from_node_id, to_node_id = related_node.id, agent_node.id
                else:
                    from_node_id, to_node_id = agent_node.id, related_node.id
                self._add_edge(kind, from_node_id, to_node_id, evidence_ids=[])

        if self.component_scope:
            return

        family = record_family(record)
        if family:
            for related in self.records_by_family.get(family, []):
                if related.artifact_dir == record.artifact_dir:
                    continue
                if not self._queue_record(related):
                    continue
                related_node = self._ensure_agent_node(related)
                self._add_edge(
                    "agent_family",
                    agent_node.id,
                    related_node.id,
                    evidence_ids=[],
                    metadata={"family": family},
                )
