"""Indexed agent-artifact associations for beads."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    query_agent_artifact_index,
    scan_agent_artifacts,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
)
from sase.core.paths import sase_projects_dir

from ._agent_names import agent_name_bead_id, global_agent_name


def load_artifact_records(project: str | None) -> tuple[AgentArtifactRecordWire, ...]:
    """Query the persistent artifact index once, scanning only as fallback."""

    options = AgentArtifactScanOptionsWire(
        include_prompt_step_markers=False,
        include_raw_prompt_snippets=False,
        max_records=None,
        newest_first=False,
        include_done_markers=True,
        include_workflow_state=False,
        include_waiting=False,
        only_projects=(project,) if project else (),
        include_project_states=("all",),
    )
    projects_root = sase_projects_dir()
    index_path = default_agent_artifact_index_path()
    if index_path.is_file():
        snapshot = query_agent_artifact_index(
            index_path,
            projects_root,
            AgentArtifactIndexQueryWire(
                include_active=True,
                include_recent_completed=False,
                include_full_history=True,
                active_limit=None,
                recent_completed_limit=None,
                include_hidden=True,
            ),
            options,
        )
    else:
        snapshot = scan_agent_artifacts(projects_root, options)
    return tuple(snapshot.records)


def artifact_associations(
    records: Iterable[AgentArtifactRecordWire],
    known_bead_ids: frozenset[str],
    identity: AgentIdentitySnapshot,
) -> dict[str, set[str]]:
    """Group visible artifact agents by the bead derived from their name."""

    agents: defaultdict[str, set[str]] = defaultdict(set)
    for record in records:
        meta = record.agent_meta
        done = record.done
        if (meta is not None and meta.hidden) or (done is not None and done.hidden):
            continue
        raw_name = (
            meta.name
            if meta is not None and meta.name
            else done.name
            if done is not None
            else None
        )
        bead_id = agent_name_bead_id(raw_name, identity)
        agent_name = global_agent_name(raw_name, identity)
        if bead_id is not None and bead_id in known_bead_ids and agent_name is not None:
            agents[bead_id].add(agent_name)
    return dict(agents)


__all__ = ["artifact_associations", "load_artifact_records"]
