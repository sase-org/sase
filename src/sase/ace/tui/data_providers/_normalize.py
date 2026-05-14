"""Agent row normalization shared by daemon snapshots and deltas."""

from __future__ import annotations

from collections.abc import Iterable

from ..models._agent_ordering import sort_and_reorder
from ..models._agent_status_overrides import apply_status_overrides
from ..models._dedup import (
    dedup_axe_spawned_agents,
    dedup_by_pid,
    dedup_running_vs_workflow,
    dedup_workflow_entries,
    remove_vcs_workspace_claims,
)
from ..models.agent import Agent


def prepare_daemon_agents(agents: Iterable[Agent]) -> list[Agent]:
    rows = list(agents)
    rows = dedup_axe_spawned_agents(rows)
    rows = remove_vcs_workspace_claims(rows)
    rows = dedup_workflow_entries(rows)
    rows = dedup_running_vs_workflow(rows)
    rows = dedup_by_pid(rows)
    apply_status_overrides(rows)
    return sort_and_reorder(rows, [])
