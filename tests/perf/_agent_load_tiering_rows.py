"""Row-shaping and per-load-context helpers shared by the oracle and benchmark."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
import os
from pathlib import Path

from sase.ace.dismissed_agents import (
    dismissed_bundle_identities_snapshot,
    load_dismissed_agents,
)
from sase.ace.tui.actions.agents._loading_compute import compute_apply_loaded_agents
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_live_query import agent_live_query_row_id
from sase.ace.tui.models.agent_loader import (
    _load_agents_from_artifact_snapshot_sources,
    _normalize_loaded_agents,
)
from sase.core.agent_scan_wire import AgentArtifactScanWire

from tests.perf._agent_load_tiering_types import (
    LoadPathDiff,
    LoadPathRows,
    VisibleAgentRow,
)


def _tui_visible_agents(agents: list[Agent]) -> list[Agent]:
    """Apply the Agents tab's dismissal pipeline to one path's loaded rows.

    Every TUI load, source scan included, passes through
    :func:`compute_apply_loaded_agents` before display, so each path is
    compared on what the tab would show. Loader rows never come from
    dismissed bundles, so there are no recovered identities to pass.
    """
    dismissed = load_dismissed_agents()
    prep = compute_apply_loaded_agents(
        agents,
        [],
        dismissed,
        False,
        dismissed_bundle_snapshot=dismissed_bundle_identities_snapshot(),
    )
    return prep.filtered_agents


def _agents_from_snapshot(snapshot: AgentArtifactScanWire) -> list[Agent]:
    agents, workflow_agent_steps = _load_agents_from_artifact_snapshot_sources(
        snapshot,
        patch_snapshot=[],
    )
    return _normalize_loaded_agents(agents, workflow_agent_steps)


def _visible_rows(agents: Iterable[Agent]) -> dict[str, VisibleAgentRow]:
    rows: dict[str, VisibleAgentRow] = {}
    for agent in agents:
        if agent.hidden or agent.is_hidden_step:
            continue
        key = _row_key(agent)
        rows[key] = VisibleAgentRow(
            key=key,
            row_id=agent_live_query_row_id(agent),
            artifact_dir=agent.index_record_dir or agent.artifacts_dir or "",
            status=agent.status,
            hidden=bool(agent.hidden or agent.is_hidden_step),
        )
    return rows


def _row_key(agent: Agent) -> str:
    artifact_dir = agent.index_record_dir or agent.artifacts_dir
    suffix = agent.prompt_step_file_name or agent_live_query_row_id(agent)
    if artifact_dir:
        return f"{artifact_dir}#{suffix}"
    return agent_live_query_row_id(agent)


def _diff_load_path(reference: LoadPathRows, candidate: LoadPathRows) -> LoadPathDiff:
    reference_keys = set(reference.visible_rows)
    candidate_keys = set(candidate.visible_rows)
    missing = tuple(
        reference.visible_rows[key] for key in sorted(reference_keys - candidate_keys)
    )
    extra = tuple(
        candidate.visible_rows[key] for key in sorted(candidate_keys - reference_keys)
    )
    candidate_extra_keys = tuple(sorted(candidate.loaded_keys - reference_keys))
    return LoadPathDiff(
        name=candidate.name,
        missing=missing,
        visible_extra=extra,
        candidate_extra_keys=candidate_extra_keys,
    )


def _nonzero_stats(stats: object) -> dict[str, int]:
    return {
        name: value
        for name, value in vars(stats).items()
        if isinstance(value, int) and value
    }


@contextmanager
def _temporary_sase_home(sase_home: Path) -> Iterator[None]:
    previous = os.environ.get("SASE_HOME")
    os.environ["SASE_HOME"] = str(sase_home)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("SASE_HOME", None)
        else:
            os.environ["SASE_HOME"] = previous
