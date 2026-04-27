"""Pure-data compute helpers for :class:`AgentLoadingMixin`.

These helpers are safe to call from a worker thread — they do not touch
widgets, do not read app state, and (apart from the self-healing
artifact cleanup) do not write to disk. The mixin in :mod:`._loading`
folds their output back into ``self`` on the UI thread.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

from ._loading_helpers import (
    DISMISSABLE_STATUSES,
    is_always_visible,
    is_axe_spawned_agent,
)

log = logging.getLogger(__name__)

# Per-process cache of artifact dirs already reconciled by the loader's
# self-healing pass.  First call inspects the dir (and may call
# ``delete_agent_artifacts``); subsequent full reloads skip it, saving the
# stat/glob syscalls when many dismissed agents accumulate.
_CLEANED_ARTIFACT_DIRS: set[str] = set()


def compute_loader_cleanup(
    dismissed_snapshot: set[tuple[AgentType, str, str | None]],
    dismissed_from_loader: list[Agent],
) -> tuple[
    set[tuple[AgentType, str, str | None]],
    set[str],
]:
    """Compute orphaned-dismissed entries and clean loader-sourced artifacts."""
    # Self-heal dismissed entries with no in-memory agent and no bundle file.
    from ....dismissed_agents import has_dismissed_bundle
    from ._killing import delete_agent_artifacts

    found_suffixes = {
        a.raw_suffix for a in dismissed_from_loader if a.raw_suffix is not None
    }
    orphaned: set[tuple[AgentType, str, str | None]] = set()
    for identity in dismissed_snapshot:
        _, _, raw_suffix = identity
        if raw_suffix is None or raw_suffix in found_suffixes:
            continue
        if not has_dismissed_bundle(raw_suffix):
            orphaned.add(identity)

    # Self-healing: clean stale artifacts only for loader-sourced dismissed agents.
    cleaned_dirs: set[str] = set()
    for a in dismissed_from_loader:
        if a._loaded_from_dismissed_bundle:
            continue
        artifacts_dir = a.artifacts_dir or a.get_artifacts_dir()
        if artifacts_dir is None or artifacts_dir in _CLEANED_ARTIFACT_DIRS:
            continue
        if not Path(artifacts_dir).is_dir():
            cleaned_dirs.add(artifacts_dir)
            continue
        delete_agent_artifacts(artifacts_dir)
        cleaned_dirs.add(artifacts_dir)

    return orphaned, cleaned_dirs


@dataclass
class PreparedApplyData:
    """Output of :func:`compute_apply_loaded_agents` (worker thread).

    All fields are plain Python values — no widget access, no ``self``
    state mutation — so the compute is safe to run via
    ``asyncio.to_thread`` while the Textual event loop continues
    dispatching ``j``/``k`` keystrokes.
    """

    filtered_agents: list[Agent]
    has_always_visible: bool
    hidden_count: int
    hideable_agents: list[Agent]
    dismissed_agent_objects: list[Agent]
    recovered_bundle_identities: set[tuple[AgentType, str, str | None]] = field(
        default_factory=set
    )
    auto_dismissed_identities: set[tuple[AgentType, str, str | None]] = field(
        default_factory=set
    )


def compute_apply_loaded_agents(
    all_agents: list[Agent],
    dismissed_from_loader: list[Agent],
    dismissed_snapshot: set[tuple[AgentType, str, str | None]],
    hide_non_run_agents: bool,
) -> PreparedApplyData:
    """Pure-data filter pipeline for ``_apply_loaded_agents``.

    Computes the recovered-bundle / auto-dismiss deltas, applies the
    dismissed-set filter, marks axe-spawned agents hidden, and partitions
    the result into always-visible vs hideable. Returns a
    :class:`_PreparedApplyData` snapshot for the UI thread to fold into
    ``self``. Safe to call from a worker thread — does not access widgets,
    does not write to disk, does not mutate ``self`` state.
    """
    recovered = {
        a.identity
        for a in dismissed_from_loader
        if a._loaded_from_dismissed_bundle and a.identity not in dismissed_snapshot
    }

    # The filter must treat freshly-recovered identities as dismissed so a
    # re-recovered agent doesn't briefly leak into the visible list before
    # the UI thread persists the recovery delta.
    effective_dismissed = dismissed_snapshot | recovered
    dismissed_suffixes: set[str] = {
        raw_suffix for _, _, raw_suffix in effective_dismissed if raw_suffix is not None
    }
    dismissed_cl_suffixes: set[tuple[str, str]] = {
        (cl_name, raw_suffix)
        for _, cl_name, raw_suffix in effective_dismissed
        if raw_suffix is not None
    }

    # Filter out dismissed agents.  Non-RUNNING agents use the broad
    # dismissed_suffixes index (suffix-only).  RUNNING agents use the
    # narrower dismissed_cl_suffixes index (cl_name, raw_suffix) to
    # avoid cross-CL contamination while still catching agents that
    # reappear with a different AgentType after dedup (e.g. a killed
    # WORKFLOW agent whose artifacts are deleted but whose RUNNING
    # field entry persists, producing an AgentType.RUNNING agent).
    # RUNNING agents with cl_name="unknown" fall back to suffix-only
    # matching since "unknown" is a transient placeholder from the
    # RUNNING field that gets resolved during dedup.
    filtered = [
        a
        for a in all_agents
        if a.identity not in effective_dismissed
        and (
            a.status == "RUNNING"
            or (a.raw_suffix is None or a.raw_suffix not in dismissed_suffixes)
        )
        and not (
            a.status == "RUNNING"
            and a.raw_suffix is not None
            and (
                (a.cl_name, a.raw_suffix) in dismissed_cl_suffixes
                or (a.cl_name == "unknown" and a.raw_suffix in dismissed_suffixes)
            )
        )
    ]

    # Auto-dismiss hidden agents that have completed successfully.
    # Failed agents are kept visible so the user can investigate.
    auto_dismissed_ids = {
        a.identity
        for a in filtered
        if a.hidden and a.status in DISMISSABLE_STATUSES and a.status != "FAILED"
    }
    if auto_dismissed_ids:
        filtered = [a for a in filtered if a.identity not in auto_dismissed_ids]

    # Mark axe-spawned agents as hidden so the icon renders correctly.
    for agent in filtered:
        if not agent.hidden and is_axe_spawned_agent(agent):
            agent.hidden = True

    # Categorize agents: always-visible (dismissable OR running) vs hideable
    always_visible: list[Agent] = []
    hideable: list[Agent] = []
    for a in filtered:
        if is_always_visible(a):
            always_visible.append(a)
        else:
            hideable.append(a)

    has_always_visible = len(always_visible) > 0
    if has_always_visible and hide_non_run_agents and hideable:
        result_agents = always_visible
        hidden_count = len(hideable)
    else:
        result_agents = filtered
        hidden_count = 0

    return PreparedApplyData(
        filtered_agents=result_agents,
        has_always_visible=has_always_visible,
        hidden_count=hidden_count,
        hideable_agents=hideable,
        dismissed_agent_objects=dismissed_from_loader,
        recovered_bundle_identities=recovered,
        auto_dismissed_identities=auto_dismissed_ids,
    )
