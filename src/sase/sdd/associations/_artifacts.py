"""Indexed agent-artifact associations for plans."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from sase.association_agents import (
    AgentAssociationRef,
    artifact_agent_association,
    merge_agent_associations,
)
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

from ._normalization import PlanReferenceNormalizer


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
    normalizer: PlanReferenceNormalizer,
    identity: AgentIdentitySnapshot,
) -> dict[str, dict[str, AgentAssociationRef]]:
    """Group visible artifact agents by every recorded plan path."""

    agents: defaultdict[str, dict[str, AgentAssociationRef]] = defaultdict(dict)
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
        association = artifact_agent_association(raw_name, identity)
        if association is None:
            continue
        plan_values = (
            meta.sdd_plan_path if meta is not None else None,
            meta.plan_path if meta is not None else None,
            getattr(meta, "archived_plan_path", None) if meta is not None else None,
            record.plan_path.plan_path if record.plan_path is not None else None,
            done.plan_path if done is not None else None,
            meta.epic_plan_ref if meta is not None else None,
        )
        for value in plan_values:
            plan_ref = normalizer.normalize(value)
            if plan_ref is not None:
                agents[plan_ref][association.label] = merge_agent_associations(
                    agents[plan_ref].get(association.label),
                    association,
                )
    return dict(agents)


__all__ = ["artifact_associations", "load_artifact_records"]
