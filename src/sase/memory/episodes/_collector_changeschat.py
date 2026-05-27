"""Chat transcript and ChangeSpec expansion methods for episode collection."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from sase.ace.changespec.models import ChangeSpec, CommitEntry
from sase.ace.changespec.parser import parse_project_file_python
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.core.episode_wire import EpisodeNodeWire, EpisodeSourceRefWire
from sase.memory.episodes._collector_utils import (
    compact_metadata,
    dedupe_records,
    iter_project_files,
    normalize_event_timestamp,
    read_json_object,
    resolve_chat_selector,
)
from sase.memory.episodes._models import EpisodeChatTurnRef
from sase.memory.episodes._record_helpers import record_chat_paths
from sase.memory.episodes.chat_parse import ParsedChatTranscript
from sase.memory.episodes.source_refs import normalize_source_path


class CollectorChatChangespecMixin:
    def _add_chat_turns(
        self: Any,
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
                metadata=compact_metadata(
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
            draft_turn = EpisodeChatTurnRef(
                id=turn_node.id,
                chat_source_id=chat_source.id,
                chat_path=parsed.path,
                turn_index=turn.turn_index,
                prompt_excerpt=turn.prompt_excerpt,
                response_excerpt=turn.response_excerpt,
            )
            self.chat_turns_by_id[draft_turn.id] = draft_turn

    def _add_fork_ref(
        self: Any,
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

        for record in dedupe_records(
            [
                *self.records_by_agent.get(fork_ref_argument, []),
                *self.records_by_family.get(fork_ref_argument, []),
            ]
        ):
            if not self._queue_record(record):
                continue
            target = self._ensure_agent_node(record)
            self._add_edge(
                xprompt_name,
                chat_node.id,
                target.id,
                evidence_ids=[chat_source.id],
                metadata={"argument": fork_ref_argument},
            )

    def _add_changespec_commit_links(
        self: Any,
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
        self: Any,
        commit: CommitEntry,
        commit_node: EpisodeNodeWire,
        changespec_source_id: str,
    ) -> None:
        if commit.chat:
            chat_path = resolve_chat_selector(commit.chat)
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
        self: Any,
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
                timestamp=normalize_event_timestamp(entry.timestamp),
                evidence_ids=[source_id],
            )

    def _records_for_chat(self: Any, chat_path: str) -> list[AgentArtifactRecordWire]:
        normalized = normalize_source_path(chat_path)
        matches: list[AgentArtifactRecordWire] = []
        for record in self.records:
            raw_meta = read_json_object(Path(record.artifact_dir) / "agent_meta.json")
            for candidate in record_chat_paths(record, raw_meta):
                if normalize_source_path(candidate) == normalized:
                    matches.append(record)
                    break
        return dedupe_records(matches)

    def _changespecs_named(self: Any, name: str) -> list[ChangeSpec]:
        if self.changespecs_by_name is None:
            self.changespecs_by_name = self._load_changespecs()
        return self.changespecs_by_name.get(name, [])

    def _load_changespecs(self: Any) -> dict[str, list[ChangeSpec]]:
        by_name: dict[str, list[ChangeSpec]] = defaultdict(list)
        for project_file in iter_project_files(self.projects_root):
            for changespec in parse_project_file_python(str(project_file)):
                by_name[changespec.name].append(changespec)
        for changespecs in by_name.values():
            changespecs.sort(key=lambda cs: (cs.file_path, cs.line_number))
        return by_name
