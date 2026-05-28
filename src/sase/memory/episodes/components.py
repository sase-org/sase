"""Connected-component planning for episode v2 collection."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

from sase.core.agent_scan_facade import scan_agent_artifacts
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanWire,
)
from sase.core.episode_wire import EpisodeWeakRefsWire
from sase.core.paths import sase_projects_dir
from sase.history.chat_catalog import list_chat_transcripts
from sase.memory.episodes._collector_engine import EpisodeCollectorEngine
from sase.memory.episodes._collector_utils import (
    compact_timestamp,
    dedupe_records,
    first_project_name,
    read_json_object,
    resolve_chat_selector,
    timestamp_in_range,
    unique_strings,
)
from sase.memory.episodes._models import EpisodeDraft, EpisodeSelector
from sase.memory.episodes._record_helpers import (
    record_agent_names,
    record_bead_ids,
    record_changespec_names,
    record_chat_paths,
    record_family,
    record_referenced_paths,
    record_related_timestamps,
)
from sase.memory.episodes.chat_parse import parse_chat_transcript
from sase.memory.episodes.identity import (
    read_episode_alias_rows,
    read_episode_member_rows,
    resolve_alias_episode_id,
)
from sase.memory.episodes.source_refs import normalize_source_path


@dataclass(frozen=True)
class EpisodeComponentEdge:
    """A deterministic strong edge used to define component membership."""

    kind: str
    from_key: str
    to_key: str
    evidence_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EpisodeComponentPlan:
    """One connected episode component selected for collection."""

    project: str
    component_key: str
    component_root_kind: str
    root_timestamp: str | None
    root_chat_key: str | None
    artifact_dirs: list[str]
    chat_paths: list[str]
    strong_edges: list[EpisodeComponentEdge]
    weak_refs: EpisodeWeakRefsWire
    seed_reason: str
    existing_episode_ids: list[str] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return (
            json.dumps(
                self.to_json_dict(),
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )


def build_episode_component_plans(
    selector: EpisodeSelector | None = None,
    *,
    projects_root: Path | str | None = None,
    scan: AgentArtifactScanWire | None = None,
    repo_root: Path | str | None = None,
    chat_paths: Iterable[str | Path] | None = None,
    include_chat_catalog: bool = True,
) -> list[EpisodeComponentPlan]:
    """Build deterministic connected-component plans from strong lineage edges."""

    selected = selector or EpisodeSelector()
    if selected.explicit_selector_count() > 1:
        raise ValueError("specify only one of agent, artifact_dir, changespec, or chat")
    root = (
        Path(projects_root).expanduser()
        if projects_root is not None
        else sase_projects_dir()
    )
    snapshot = scan if scan is not None else _scan_projects(root)
    planner = _ComponentPlanner(
        selected,
        projects_root=root,
        scan=snapshot,
        repo_root=Path(repo_root).expanduser() if repo_root is not None else Path.cwd(),
        chat_paths=chat_paths,
        include_chat_catalog=include_chat_catalog,
    )
    return planner.build()


def collect_episode_draft_for_component_plan(
    plan: EpisodeComponentPlan,
    *,
    projects_root: Path | str | None = None,
    scan: AgentArtifactScanWire | None = None,
    repo_root: Path | str | None = None,
) -> EpisodeDraft:
    """Collect one rich source graph constrained to a component plan."""

    root = (
        Path(projects_root).expanduser()
        if projects_root is not None
        else sase_projects_dir()
    )
    snapshot = scan if scan is not None else _scan_projects(root)
    component_artifact_keys = {
        normalize_source_path(path) for path in plan.artifact_dirs
    }
    component_chat_paths = {normalize_source_path(path) for path in plan.chat_paths}
    collector = EpisodeCollectorEngine(
        EpisodeSelector(project=plan.project),
        projects_root=root,
        scan=snapshot,
        repo_root=Path(repo_root).expanduser() if repo_root is not None else Path.cwd(),
        component_artifact_keys=component_artifact_keys,
        component_chat_paths=component_chat_paths,
        component_metadata=_plan_metadata(plan),
    )
    return collector.collect_component(
        artifact_dirs=plan.artifact_dirs,
        chat_paths=plan.chat_paths,
    )


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, key: str) -> None:
        self.parent.setdefault(key, key)

    def find(self, key: str) -> str:
        self.add(key)
        parent = self.parent[key]
        if parent != key:
            self.parent[key] = self.find(parent)
        return self.parent[key]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if right_root < left_root:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root


class _ComponentPlanner:
    def __init__(
        self,
        selector: EpisodeSelector,
        *,
        projects_root: Path,
        scan: AgentArtifactScanWire,
        repo_root: Path,
        chat_paths: Iterable[str | Path] | None,
        include_chat_catalog: bool,
    ) -> None:
        self.selector = selector
        self.projects_root = projects_root
        self.scan = scan
        self.repo_root = repo_root
        self.include_chat_catalog = include_chat_catalog
        self.records = sorted(
            scan.records,
            key=lambda record: (
                record.project_name,
                record.workflow_dir_name,
                compact_timestamp(record.timestamp),
                normalize_source_path(record.artifact_dir),
            ),
        )
        self.records_by_key = {_record_key(record): record for record in self.records}
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
        self._index_records()
        self.chat_paths = self._initial_chat_paths(chat_paths)
        self.uf = _UnionFind()
        self.strong_edges_by_key: dict[
            tuple[str, str, str, tuple[str, ...]], EpisodeComponentEdge
        ] = {}
        self.seed_reasons_by_key: dict[str, set[str]] = defaultdict(set)

    def build(self) -> list[EpisodeComponentPlan]:
        self._add_record_edges()
        self._add_chat_edges()
        seed_keys = self._seed_keys()
        if not seed_keys:
            return []
        components_by_root: dict[str, set[str]] = defaultdict(set)
        for key in seed_keys:
            root = self.uf.find(key)
            components_by_root[root].update(self._component_members(root))
        plans = [
            self._build_plan(root, members)
            for root, members in sorted(components_by_root.items())
        ]
        return sorted(
            plans,
            key=lambda plan: (
                plan.project,
                plan.root_timestamp or "",
                plan.root_chat_key or "",
                plan.component_key,
            ),
        )

    def _index_records(self) -> None:
        for record in self.records:
            self.records_by_timestamp[compact_timestamp(record.timestamp)].append(
                record
            )
            for name in record_agent_names(record):
                self.records_by_agent[name].append(record)
            family = record_family(record)
            if family:
                self.records_by_family[family].append(record)
            for changespec in record_changespec_names(record):
                self.records_by_changespec[changespec].append(record)

    def _initial_chat_paths(
        self,
        explicit_chat_paths: Iterable[str | Path] | None,
    ) -> set[str]:
        paths = {
            normalize_source_path(path)
            for path in explicit_chat_paths or ()
            if str(path)
        }
        for record in self.records:
            raw_meta = read_json_object(Path(record.artifact_dir) / "agent_meta.json")
            paths.update(
                normalize_source_path(path)
                for path in record_chat_paths(record, raw_meta)
            )
        if self.include_chat_catalog:
            try:
                paths.update(
                    normalize_source_path(info.absolute_path)
                    for info in list_chat_transcripts()
                )
            except OSError:
                pass
        return paths

    def _add_record_edges(self) -> None:
        for record in self.records:
            record_key = _record_key(record)
            self.uf.add(record_key)
            raw_meta = read_json_object(Path(record.artifact_dir) / "agent_meta.json")
            for chat_path in record_chat_paths(record, raw_meta):
                chat_key = _chat_key(chat_path)
                self.chat_paths.add(normalize_source_path(chat_path))
                self._add_strong_edge("record_chat", record_key, chat_key)
            for step in record.prompt_steps:
                if step.response_path:
                    chat_key = _chat_key(step.response_path)
                    self.chat_paths.add(normalize_source_path(step.response_path))
                    self._add_strong_edge("workflow_step_chat", record_key, chat_key)
                if step.artifacts_dir:
                    target = self.records_by_key.get(
                        _record_key_from_path(step.artifacts_dir)
                    )
                    if target is not None:
                        self._add_strong_edge(
                            "workflow_step_agent",
                            record_key,
                            _record_key(target),
                        )
            for kind, timestamp in record_related_timestamps(record):
                for related in self.records_by_timestamp.get(timestamp, []):
                    related_key = _record_key(related)
                    if related_key == record_key:
                        continue
                    if kind in {"parent_agent", "retry_of"}:
                        from_key, to_key = related_key, record_key
                    else:
                        from_key, to_key = record_key, related_key
                    self._add_strong_edge(kind, from_key, to_key)

    def _add_chat_edges(self) -> None:
        queue: deque[str] = deque(sorted(self.chat_paths))
        seen: set[str] = set()
        while queue:
            chat_path = normalize_source_path(queue.popleft())
            if chat_path in seen:
                continue
            seen.add(chat_path)
            chat_key = _chat_key(chat_path)
            self.uf.add(chat_key)
            parsed = parse_chat_transcript(chat_path)
            for linked_path in parsed.linked_chat_paths:
                target_path = normalize_source_path(linked_path)
                self.chat_paths.add(target_path)
                queue.append(target_path)
                self._add_strong_edge("linked_chat", chat_key, _chat_key(target_path))
            for fork_ref in parsed.fork_refs:
                if fork_ref.resolved_chat_path is not None:
                    target_path = normalize_source_path(fork_ref.resolved_chat_path)
                    self.chat_paths.add(target_path)
                    queue.append(target_path)
                    self._add_strong_edge(
                        fork_ref.xprompt_name,
                        chat_key,
                        _chat_key(target_path),
                        evidence_keys=[fork_ref.full_match],
                    )
                    continue
                for record in dedupe_records(
                    [
                        *self.records_by_agent.get(fork_ref.argument, []),
                        *self.records_by_family.get(fork_ref.argument, []),
                    ]
                ):
                    self._add_strong_edge(
                        fork_ref.xprompt_name,
                        chat_key,
                        _record_key(record),
                        evidence_keys=[fork_ref.full_match],
                    )

    def _seed_keys(self) -> set[str]:
        if self.selector.agent is not None:
            return self._seed_records(
                [
                    *self.records_by_agent.get(self.selector.agent, []),
                    *self.records_by_family.get(self.selector.agent, []),
                ],
                f"agent:{self.selector.agent}",
            )
        if self.selector.artifact_dir is not None:
            key = _record_key_from_path(self.selector.artifact_dir)
            self.seed_reasons_by_key[key].add(
                f"artifact_dir:{key.removeprefix('artifact:')}"
            )
            self.uf.add(key)
            return {key}
        if self.selector.changespec is not None:
            return self._seed_records(
                self.records_by_changespec.get(self.selector.changespec, []),
                f"changespec:{self.selector.changespec}",
            )
        if self.selector.chat is not None:
            chat_path = resolve_chat_selector(self.selector.chat)
            key = _chat_key(chat_path)
            self.seed_reasons_by_key[key].add(
                f"chat:{normalize_source_path(chat_path)}"
            )
            self.uf.add(key)
            return {key}
        return self._project_scan_seed_keys()

    def _project_scan_seed_keys(self) -> set[str]:
        project = self.selector.project
        records = [
            record
            for record in self.records
            if (project is None or record.project_name == project)
            and timestamp_in_range(
                record.timestamp,
                since=self.selector.since,
                until=self.selector.until,
            )
        ]
        seed_keys = self._seed_records(
            records[: self.selector.limit]
            if self.selector.limit is not None
            else records,
            self._project_scan_seed_reason(),
        )
        if project is None:
            for chat_path in sorted(self.chat_paths):
                timestamp = _chat_timestamp(chat_path)
                if timestamp is None:
                    continue
                if not timestamp_in_range(
                    timestamp,
                    since=self.selector.since,
                    until=self.selector.until,
                ):
                    continue
                key = _chat_key(chat_path)
                self.seed_reasons_by_key[key].add(self._project_scan_seed_reason())
                self.uf.add(key)
                seed_keys.add(key)
        return seed_keys

    def _seed_records(
        self,
        records: Iterable[AgentArtifactRecordWire],
        reason: str,
    ) -> set[str]:
        keys: set[str] = set()
        for record in dedupe_records(records):
            key = _record_key(record)
            self.seed_reasons_by_key[key].add(reason)
            self.uf.add(key)
            keys.add(key)
        return keys

    def _project_scan_seed_reason(self) -> str:
        parts = ["project_scan"]
        if self.selector.project:
            parts.append(f"project={self.selector.project}")
        if self.selector.since:
            parts.append(f"since={self.selector.since}")
        if self.selector.until:
            parts.append(f"until={self.selector.until}")
        return ":".join(parts)

    def _component_members(self, root: str) -> set[str]:
        members = {key for key in self.uf.parent if self.uf.find(key) == root}
        changed = True
        while changed:
            changed = False
            for edge in self.strong_edges_by_key.values():
                if edge.from_key in members or edge.to_key in members:
                    if edge.from_key not in members or edge.to_key not in members:
                        members.add(edge.from_key)
                        members.add(edge.to_key)
                        changed = True
        return members

    def _build_plan(self, root: str, members: set[str]) -> EpisodeComponentPlan:
        records = [
            self.records_by_key[key]
            for key in sorted(members)
            if key.startswith("artifact:") and key in self.records_by_key
        ]
        chat_paths = sorted(
            key.removeprefix("chat:") for key in members if key.startswith("chat:")
        )
        project = self._component_project(records)
        root_kind, root_timestamp, root_chat_key, component_key = _component_root(
            project,
            records,
            chat_paths,
        )
        strong_edges = sorted(
            (
                edge
                for edge in self.strong_edges_by_key.values()
                if edge.from_key in members and edge.to_key in members
            ),
            key=lambda edge: (
                edge.kind,
                edge.from_key,
                edge.to_key,
                tuple(edge.evidence_keys),
            ),
        )
        weak_refs = self._weak_refs(records)
        member_keys = {
            *members,
            f"component:{component_key}",
        }
        return EpisodeComponentPlan(
            project=project,
            component_key=component_key,
            component_root_kind=root_kind,
            root_timestamp=root_timestamp,
            root_chat_key=root_chat_key,
            artifact_dirs=[
                normalize_source_path(record.artifact_dir) for record in records
            ],
            chat_paths=chat_paths,
            strong_edges=strong_edges,
            weak_refs=weak_refs,
            seed_reason=self._seed_reason(members),
            existing_episode_ids=_existing_episode_ids_for_members(
                project,
                member_keys,
                projects_root=self.projects_root,
            ),
        )

    def _component_project(self, records: list[AgentArtifactRecordWire]) -> str:
        if records:
            return records[0].project_name
        return self.selector.project or first_project_name(self.records) or "home"

    def _weak_refs(self, records: list[AgentArtifactRecordWire]) -> EpisodeWeakRefsWire:
        changespec_names: list[str] = []
        bead_ids: list[str] = []
        agent_families: list[str] = []
        touched_paths: list[str] = []
        for record in records:
            changespec_names.extend(record_changespec_names(record))
            bead_ids.extend(record_bead_ids(record))
            family = record_family(record)
            if family:
                agent_families.append(family)
            raw_meta = read_json_object(Path(record.artifact_dir) / "agent_meta.json")
            raw_done = read_json_object(Path(record.artifact_dir) / "done.json")
            touched_paths.extend(
                normalize_source_path(path)
                for path, kind, _edge_kind in record_referenced_paths(
                    record,
                    raw_meta,
                    raw_done,
                )
                if kind != "chat"
            )
            for step in record.prompt_steps:
                if step.diff_path:
                    touched_paths.append(normalize_source_path(step.diff_path))
        return EpisodeWeakRefsWire(
            changespec_names=sorted(unique_strings(changespec_names)),
            bead_ids=sorted(unique_strings(bead_ids)),
            agent_families=sorted(unique_strings(agent_families)),
            touched_paths=sorted(unique_strings(touched_paths)),
        )

    def _seed_reason(self, members: set[str]) -> str:
        reasons: list[str] = []
        for member in sorted(members):
            reasons.extend(sorted(self.seed_reasons_by_key.get(member, [])))
        return unique_strings(reasons)[0] if reasons else "strong_lineage"

    def _add_strong_edge(
        self,
        kind: str,
        from_key: str,
        to_key: str,
        *,
        evidence_keys: Iterable[str] = (),
    ) -> None:
        if from_key == to_key:
            self.uf.add(from_key)
            return
        evidence = sorted(unique_strings(evidence_keys))
        key = (kind, from_key, to_key, tuple(evidence))
        self.strong_edges_by_key[key] = EpisodeComponentEdge(
            kind=kind,
            from_key=from_key,
            to_key=to_key,
            evidence_keys=evidence,
        )
        self.uf.union(from_key, to_key)


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


def _plan_metadata(plan: EpisodeComponentPlan) -> dict[str, str]:
    return {
        "component_key": plan.component_key,
        "component_root_kind": plan.component_root_kind,
        "component_root_timestamp": plan.root_timestamp or "",
        "component_root_chat_key": plan.root_chat_key or "",
        "component_seed_reason": plan.seed_reason,
        "component_strong_edge_count": str(len(plan.strong_edges)),
        "existing_episode_ids": ",".join(plan.existing_episode_ids),
        "weak_changespec_names": ",".join(plan.weak_refs.changespec_names),
        "weak_bead_ids": ",".join(plan.weak_refs.bead_ids),
        "weak_agent_families": ",".join(plan.weak_refs.agent_families),
        "weak_touched_paths": ",".join(plan.weak_refs.touched_paths),
    }


def _component_root(
    project: str,
    records: list[AgentArtifactRecordWire],
    chat_paths: list[str],
) -> tuple[str, str | None, str | None, str]:
    if records:
        root_record = sorted(
            records,
            key=lambda record: (
                compact_timestamp(record.timestamp),
                normalize_source_path(record.artifact_dir),
            ),
        )[0]
        timestamp = compact_timestamp(root_record.timestamp)
        artifact_key = normalize_source_path(root_record.artifact_dir)
        return (
            "artifact",
            timestamp,
            None,
            f"component/artifact/{project}/{timestamp}/{artifact_key}",
        )
    root_chat_key = chat_paths[0] if chat_paths else None
    if root_chat_key is not None:
        return "chat", None, root_chat_key, f"component/chat/{root_chat_key}"
    return "empty", None, None, f"component/empty/{project}"


def _existing_episode_ids_for_members(
    project: str,
    member_keys: set[str],
    *,
    projects_root: Path,
) -> list[str]:
    episode_ids = {
        row.canonical_episode_id
        for row in read_episode_member_rows(project, projects_root=projects_root)
        if row.member_key in member_keys
    }
    aliases = read_episode_alias_rows(project, projects_root=projects_root)
    resolved = {
        resolve_alias_episode_id(episode_id, aliases) for episode_id in episode_ids
    }
    return sorted(resolved)


def _record_key(record: AgentArtifactRecordWire) -> str:
    return _record_key_from_path(record.artifact_dir)


def _record_key_from_path(path: str | Path) -> str:
    return f"artifact:{normalize_source_path(path)}"


def _chat_key(path: str | Path) -> str:
    return f"chat:{normalize_source_path(path)}"


def _chat_timestamp(path: str) -> str | None:
    stem = Path(path).stem
    if "-" not in stem:
        return None
    suffix = stem.rsplit("-", 1)[-1]
    if len(suffix) == 13 and suffix[6] == "_":
        return compact_timestamp(suffix)
    return None


__all__ = [
    "EpisodeComponentEdge",
    "EpisodeComponentPlan",
    "build_episode_component_plans",
    "collect_episode_draft_for_component_plan",
]
