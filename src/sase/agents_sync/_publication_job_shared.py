"""Shared state and safe outbox probes for the agent publication job."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any

from sase.agents_sync._commit_publication_outbox import active_agent_publications
from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
from sase.agents_sync.referenced_by_outbox import list_referenced_by_requests

_DONE_MARKER_GRACE_SECONDS = 10 * 60


@dataclass(slots=True)
class PublicationJobSummary:
    """Counters and per-project heartbeat state from one scheduler pass."""

    projects: int = 0
    hood_drained: int = 0
    link_drained: int = 0
    referenced_by_drained: int = 0
    active_remaining: int = 0
    parked: int = 0
    lock_busy: int = 0
    deferred_projects: int = 0
    errors: int = 0
    skipped_overlap: bool = False
    standing: int = 0
    diagnostics: list[str] = field(default_factory=list)
    standing_report: list[str] = field(default_factory=list)
    project_stats: dict[str, dict[str, object]] = field(default_factory=dict)


@dataclass(slots=True)
class ProjectPass:
    hood_drained: int = 0
    link_drained: int = 0
    link_retained: int = 0
    referenced_by_drained: int = 0
    lock_busy: bool = False
    deferred: bool = False
    error: str | None = None
    retained_hints: list[dict[str, Any]] = field(default_factory=list)
    claim_unfinished: bool = False
    outcome: str = "idle"


def active_items(project_key: str) -> tuple[AgentPublicationOutboxItem, ...]:
    """Return every active request; errors propagate to the project handler."""

    return active_agent_publications(project_key)


def safe_active_items(project_key: str) -> tuple[AgentPublicationOutboxItem, ...]:
    try:
        return active_agent_publications(project_key)
    except Exception:
        return ()


def publication_is_ready(
    item: AgentPublicationOutboxItem,
    *,
    now: float | None = None,
) -> bool:
    """Return whether one active request should be selected for work now.

    Parked rows stay out of selection until the Rust recheck predicate says
    they are due. Explicit ``sase agent sync`` paths bypass this gate by
    draining selected keys directly.
    """

    if item.parked_reason is not None:
        from sase.agents_sync.publication_outbox_operations import (
            publication_is_parked_due,
        )

        if not publication_is_parked_due(item, now=now):
            return False
    if not item.artifacts_dir:
        return True
    if (Path(item.artifacts_dir).expanduser() / "done.json").is_file():
        return True
    observed = time.time() if now is None else now
    return observed - item.created_at >= _DONE_MARKER_GRACE_SECONDS


def safe_referenced_by_items(project_key: str) -> tuple[Any, ...]:
    try:
        return list_referenced_by_requests(project_key, include_quarantined=False)
    except Exception:
        return ()


def safe_referenced_by_count(project_key: str) -> int:
    return len(safe_referenced_by_items(project_key))
