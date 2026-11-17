"""Compact-wire loaders for active home agents (``running.json`` rows).

Compact twin of the home-running half of
:mod:`sase.ace.tui.models._loaders._running_loaders`: same selection
filter (project ``home``, workflow ``ace-run``), same liveness gate, and
the same best-effort stale-marker cleanup. Rows are built directly from
compact list facts through the shared compact metadata adapter.

Only local home rows are covered: local RUNNING-field claims keep their
existing filesystem path until the workflow-cutover phase adds the
remaining consumers. The constructors read only compact wire dataclasses
(:mod:`sase.core.agent_scan_list_wire`). They never call the full-record
Python decoder and never build full marker dataclasses.
"""

from __future__ import annotations

from pathlib import Path

from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.agent_scan_list_wire import (
    AgentArtifactListRecordWire,
    AgentArtifactListSnapshotWire,
)
from sase.core.paths import sase_projects_dir

from ....hooks.processes import is_process_running
from ._compact_meta_enrichment import enrich_agent_from_compact_meta
from ._compact_prompt_markers import enrich_agent_from_compact_prompt_steps
from .._timestamps import parse_timestamp_14_digit
from ..agent import Agent, AgentType


def _compact_claim_pid_is_live(pid: int | None) -> bool:
    return pid is not None and is_process_running(pid)


def _release_stale_compact_running_home_marker(artifact_dir: Path) -> None:
    """Best-effort cleanup for a dead local home-mode ``running.json`` marker."""
    running_file = artifact_dir / "running.json"
    try:
        running_file.unlink(missing_ok=True)
        update_agent_artifact_index_for_marker_mutation(artifact_dir)
    except OSError:
        pass


def resolve_compact_running_home_records(
    snapshot: AgentArtifactListSnapshotWire,
) -> list[AgentArtifactListRecordWire]:
    """Select live local home running rows and clean up stale markers.

    Mirrors ``resolve_running_home_records_from_snapshot``: project
    ``home`` plus workflow ``ace-run`` plus a present running marker plus
    a live PID. Dead markers are unlinked best-effort with the absolute
    artifact path embedded in the record.
    """
    records: list[AgentArtifactListRecordWire] = []
    for record in snapshot.records:
        if record.project_name != "home":
            continue
        if record.workflow_dir_name != "ace-run":
            continue
        running = record.running
        if running is None:
            continue
        if not _compact_claim_pid_is_live(running.pid):
            _release_stale_compact_running_home_marker(Path(record.artifact_dir))
            continue
        records.append(record)
    return records


def load_running_home_agents_from_compact_records(
    records: list[AgentArtifactListRecordWire],
    *,
    project_file: str,
) -> list[Agent]:
    """Build Agent rows from live compact home running records."""
    agents: list[Agent] = []
    for record in records:
        running = record.running
        if running is None:
            continue
        agent = Agent(
            agent_type=AgentType.RUNNING,
            cl_name=running.cl_name or "~",
            project_file=project_file,
            status="STARTING",
            start_time=parse_timestamp_14_digit(record.timestamp),
            workflow="ace(run)",
            pid=running.pid,
            runner_is_live=True,
            raw_suffix=record.timestamp,
            model=running.model,
            llm_provider=running.llm_provider,
            vcs_provider=running.vcs_provider,
            workspace_dir=running.workspace_dir,
            record_shape="list",
            index_record_dir=record.artifact_dir,
        )
        enrich_agent_from_compact_meta(
            agent,
            record.meta,
            record.waiting,
            record.pending_question,
        )
        enrich_agent_from_compact_prompt_steps(agent, record.prompt_steps)
        agents.append(agent)
    return agents


def load_running_home_agents_from_compact_snapshot(
    snapshot: AgentArtifactListSnapshotWire,
) -> list[Agent]:
    """Build live home running rows from one compact list snapshot.

    Compact twin of :func:`load_running_home_agents_from_snapshot`.
    """
    from sase.ace.patch.project_spec_path import preferred_project_spec_path

    home_project_file = preferred_project_spec_path(
        str(sase_projects_dir() / "home"), "home"
    )
    return load_running_home_agents_from_compact_records(
        resolve_compact_running_home_records(snapshot),
        project_file=home_project_file,
    )
