"""On-demand hydration entry points for projected artifact-index records."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    load_agent_artifact_records_bounded as load_agent_artifact_records,
)
from sase.core.agent_scan_wire import AgentArtifactRecordWire

from .agent_types import LinkedRepoMetadata
from ._projected_record_detail import (
    mark_projected_agent_hydration_attempted,
    projected_agent_needs_hydration,
)
from ._projected_record_restore import apply_projected_agent_record

if TYPE_CHECKING:
    from .agent import Agent

log = logging.getLogger(__name__)


def resolve_step_output(agent: Agent) -> dict[str, Any] | None:
    """Return the currently hydrated step output without doing blocking work."""

    return agent.step_output if isinstance(agent.step_output, dict) else None


def resolve_linked_repos(
    agent: Agent,
    *,
    hydrate: bool = False,
) -> tuple[LinkedRepoMetadata, ...]:
    """Return linked repositories, optionally hydrating a projected record first."""

    if hydrate and projected_agent_needs_hydration(agent):
        hydrate_projected_agent(agent)
    return agent.linked_repos


def hydrate_projected_agent(agent: Agent) -> bool:
    """Load and apply the full index record for one projected agent.

    This function may block on SQLite and must be called from a worker thread
    when used by the TUI detail render path.
    """
    artifact_dir = agent.index_record_dir
    if agent.record_shape != "list" or not artifact_dir:
        return False

    record, retryable = load_projected_agent_record(artifact_dir)
    if record is None:
        if not retryable:
            mark_projected_agent_hydration_attempted(agent)
        return False
    return apply_projected_agent_record(
        agent,
        record,
        expected_artifact_dir=artifact_dir,
    )


def load_projected_agent_record(
    artifact_dir: str,
) -> tuple[AgentArtifactRecordWire | None, bool]:
    """Read one full record without mutating or retaining its Agent row.

    The boolean is true when the index lock made the read retryable. This is
    the worker-side half of selected-detail hydration; UI code decides
    whether the detached result still belongs to the selected row before it
    applies any payload.
    """

    index_path = default_agent_artifact_index_path()
    if not index_path.is_file():
        return None, False

    try:
        records = load_agent_artifact_records(index_path, [artifact_dir])
    except (ImportError, AttributeError, OSError, RuntimeError, ValueError):
        log.debug(
            "projected record hydration failed for %s", artifact_dir, exc_info=True
        )
        return None, False

    if records is None:
        return None, True

    if not records:
        return None, False

    return records[0], False
