"""Which beads currently have work in flight, and what proves it.

Two independent sources contribute to that view:

- **launching** — an active ``sase bead work <bead>`` proc, keyed by bead
  ID only. That matches today's ``active_task_launch_bead_ids`` behavior
  and is left unscoped so callers and test helpers do not churn.
- **working** — a live ``ace-run`` agent artifact whose
  ``agent_meta.bead_id`` names the bead, keyed by
  ``(project_name, bead_id)``. Artifact records carry a project, so the
  match is free and strictly correct.

Both halves must move together if that keying asymmetry is ever changed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from sase.agent.names import is_process_alive
from sase.bead.task_launch import active_task_launch_bead_ids
from sase.core.agent_scan_facade import scan_agent_artifacts
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
)
from sase.core.paths import sase_projects_dir

AGENT_BEAD_SCAN_OPTIONS = AgentArtifactScanOptionsWire(
    only_workflow_dirs=("ace-run",),
    include_prompt_step_markers=False,
    include_raw_prompt_snippets=False,
    include_done_markers=False,
    include_workflow_state=False,
    include_waiting=False,
)


def _agent_pid_is_alive(
    *,
    pid: int | None,
    stopped_at: str | None,
    process_identity: str | None,
    artifact_dir: Path | str,
) -> bool:
    """Return whether ``pid`` / ``stopped_at`` still describe a live process."""
    meta: dict[str, object] = {}
    if pid is not None:
        meta["pid"] = pid
    if stopped_at is not None:
        meta["stopped_at"] = stopped_at
    if process_identity is not None:
        meta["process_identity"] = process_identity
    return is_process_alive(meta, Path(artifact_dir))


def agent_record_is_alive(record: AgentArtifactRecordWire) -> bool:
    """Return whether *record*'s ``pid`` / ``stopped_at`` still look live."""
    meta = record.agent_meta
    return _agent_pid_is_alive(
        pid=None if meta is None else meta.pid,
        stopped_at=None if meta is None else meta.stopped_at,
        process_identity=None
        if meta is None
        else getattr(meta, "process_identity", None),
        artifact_dir=record.artifact_dir,
    )


def beads_with_live_agents(
    projects_root: Path | None = None,
) -> dict[tuple[str, str], str]:
    """Return ``{(project_name, bead_id): agent_name}`` for live ace-run workers.

    Only the newest record per ``(project_name, agent_name)`` (by
    ``record.timestamp``) is considered, matching
    ``bead_claim_checks._latest_owner_records``: a stale record must not
    outvote a fresh one. When several live agents name the same bead, the
    newest timestamp's agent name is kept for diagnostics.
    """
    root = sase_projects_dir() if projects_root is None else projects_root
    snapshot = scan_agent_artifacts(root, AGENT_BEAD_SCAN_OPTIONS)
    latest: dict[tuple[str, str], AgentArtifactRecordWire] = {}
    for record in snapshot.records:
        meta = record.agent_meta
        if (
            record.workflow_dir_name != "ace-run"
            or meta is None
            or not meta.name
            or not meta.bead_id
        ):
            continue
        key = (record.project_name, meta.name)
        previous = latest.get(key)
        if previous is None or record.timestamp > previous.timestamp:
            latest[key] = record

    working: dict[tuple[str, str], str] = {}
    chosen_timestamp: dict[tuple[str, str], str] = {}
    for record in latest.values():
        if not agent_record_is_alive(record):
            continue
        meta = record.agent_meta
        if meta is None or not meta.name or not meta.bead_id:
            continue
        pair = (record.project_name, meta.bead_id)
        previous_ts = chosen_timestamp.get(pair)
        if previous_ts is None or record.timestamp > previous_ts:
            chosen_timestamp[pair] = record.timestamp
            working[pair] = meta.name
    return working


@dataclass(frozen=True)
class BeadWorkInFlight:
    """Composite view of beads with a launch proc or a live agent.

    ``launching`` is keyed by bead ID only. ``working`` is project-scoped.
    """

    launching: frozenset[str]
    working: frozenset[tuple[str, str]]
    working_agents: Mapping[tuple[str, str], str] = field(default_factory=dict)

    def is_launching(self, bead_id: str) -> bool:
        """Return whether an active launch proc still names *bead_id*."""
        return bead_id in self.launching

    def is_worked(self, project_name: str, bead_id: str) -> bool:
        """Return whether a live agent in *project_name* owns *bead_id*."""
        return (project_name, bead_id) in self.working

    def covers(self, project_name: str, bead_id: str) -> bool:
        """Return whether either half says *bead_id* has work in flight."""
        return self.is_launching(bead_id) or self.is_worked(project_name, bead_id)

    def agent_name(self, project_name: str, bead_id: str) -> str | None:
        """Return the live agent name for *bead_id*, if one was scanned."""
        return self.working_agents.get((project_name, bead_id))


def bead_work_in_flight(
    log_warning: Callable[[str], None],
    *,
    live_agents: Callable[[], dict[tuple[str, str], str]] | None = None,
) -> BeadWorkInFlight:
    """Build both work-in-flight halves, each guarded independently.

    A failing source is treated as empty so a persistent scan outage
    cannot silence every project's task triage. Prefer passing the
    chop's ``runtime.log.warning``. *live_agents* defaults to
    :func:`beads_with_live_agents` and is resolved at call time so tests
    can monkeypatch that name.
    """
    scan_live_agents = beads_with_live_agents if live_agents is None else live_agents
    try:
        launching = active_task_launch_bead_ids()
    except Exception as exc:  # noqa: BLE001 - keep today's triage behavior.
        log_warning(f"[bead_task_triage] Failed to read active task launches: {exc}")
        launching = frozenset()

    try:
        working_agents = scan_live_agents()
    except Exception as exc:  # noqa: BLE001 - keep today's triage behavior.
        log_warning(f"[bead_task_triage] Failed to scan live agent beads: {exc}")
        working_agents = {}

    return BeadWorkInFlight(
        launching=launching,
        working=frozenset(working_agents),
        working_agents=working_agents,
    )


__all__ = [
    "AGENT_BEAD_SCAN_OPTIONS",
    "BeadWorkInFlight",
    "agent_record_is_alive",
    "bead_work_in_flight",
    "beads_with_live_agents",
]
