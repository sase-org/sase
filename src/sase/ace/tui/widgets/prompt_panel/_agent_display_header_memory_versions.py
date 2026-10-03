"""Memory-history enrichment for detail-header summaries."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from ...models.agent import Agent
from ._agent_display_state import DetailHeaderSummary


def enrich_memory_versions(
    summary: DetailHeaderSummary,
    agent: Agent,
    *,
    history: Any | None = None,
    service: Any | None = None,
) -> DetailHeaderSummary:
    """Resolve MEMORY lane version chips and the launch row (agents-bridge).

    Runs on the memory lane's batch before that batch publishes, so the
    chips ride the batch's own publish (no extra publish) and never delay
    the rows. Only visible rows (``MAX_VISIBLE_READS``) plus the launch
    row resolve. Failures omit their chip or row. Returns a new summary
    with the same ``memory_reads`` and ``ready_lanes``; when nothing
    resolves, returns *summary* unchanged so cached identity is stable.
    """
    from ._agent_memory_reads import MAX_VISIBLE_READS
    from ._agent_memory_versions import (
        MemoryVersionPin,
        resolve_event_chips,
        resolve_launch_row,
    )

    if history is None:
        try:
            from sase.ace.tui.memory_history import AceMemoryHistory

            history = AceMemoryHistory()
        except Exception:
            return summary
    if service is None:
        try:
            service = history.service
        except Exception:
            try:
                from sase.memory.history.service import shared_history_service

                service = shared_history_service()
            except Exception:
                return summary
    chips: dict[str, Any] = {}
    pins: dict[str, Any] = {}
    for item in summary.memory_reads[:MAX_VISIBLE_READS]:
        try:
            chip, item_pins = resolve_event_chips(
                item.event, history=history, service=service
            )
        except Exception:
            continue
        if chip is not None:
            chips[item.event.id] = chip
        pin = _single_target_pin(item, item_pins, service=service)
        if pin is not None:
            pins[item.event.id] = pin
    try:
        launch_row = resolve_launch_row(agent, history=history, service=service)
    except Exception:
        launch_row = None
    launch_pin: MemoryVersionPin | None = None
    if launch_row is not None:
        launch_pin = _launch_pin_for_row(launch_row, agent, service=service)
    new_chips = {**summary.memory_version_chips, **chips}
    new_pins = {**summary.memory_version_pins, **pins}
    new_launch_row = launch_row if launch_row is not None else summary.memory_launch_row
    new_launch_pin = launch_pin if launch_pin is not None else summary.memory_launch_pin
    if (
        new_chips == summary.memory_version_chips
        and new_pins == summary.memory_version_pins
        and new_launch_row == summary.memory_launch_row
        and new_launch_pin == summary.memory_launch_pin
    ):
        return summary
    return replace(
        summary,
        memory_version_chips=new_chips,
        memory_version_pins=new_pins,
        memory_launch_row=new_launch_row,
        memory_launch_pin=new_launch_pin,
    )


def _single_target_pin(
    item: Any, pins: list[tuple[str, int | None]], *, service: Any
) -> Any | None:
    """Return the pager pin for a single-target resolved read, if any."""
    resolved = [(target, ordinal) for target, ordinal in pins if ordinal]
    if len(resolved) != 1:
        return None
    if len(pins) != 1:
        return None
    from ._agent_memory_versions import MemoryVersionPin

    target, ordinal = resolved[0]
    event = item.event
    try:
        scope = _scope_for_pin(event, service=service)
    except Exception:
        return None
    if scope is None:
        return None
    try:
        from ._agent_memory_versions import core_selector_for_target

        repo_root = Path(str(getattr(scope, "repo_root", "") or ""))
        subject = core_selector_for_target(target, repo_root)
    except Exception:
        return None
    return MemoryVersionPin(
        scope_key=str(getattr(scope, "scope_key", "") or ""),
        repo_root=str(getattr(scope, "repo_root", "") or ""),
        subject=subject,
        revision=f"v{ordinal}",
        title=str(target).rsplit("/", 1)[-1],
    )


def _scope_for_pin(event: Any, *, service: Any) -> Any | None:
    """Return the history scope for a pin (fail-open)."""
    from ._agent_memory_versions import scope_for_event

    return scope_for_event(event, service)


def _launch_pin_for_row(row: Any, agent: Any, *, service: Any) -> Any | None:
    """Return the pager pin for a launch row, if it opens anywhere."""
    from pathlib import Path as _Path

    from ._agent_memory_versions import MemoryVersionPin

    if getattr(row, "unavailable", False):
        return None
    workspace_dir = getattr(agent, "workspace_dir", None)
    if not workspace_dir:
        return None
    try:
        scope = service.project_scope(_Path(str(workspace_dir)))
    except Exception:
        return None
    repo_root = str(getattr(scope, "repo_root", "") or "")
    scope_key = str(getattr(scope, "scope_key", "") or "")
    blob = getattr(row, "blob_oid", None)
    ordinal = getattr(row, "ordinal", None)
    if ordinal:
        return MemoryVersionPin(
            scope_key=scope_key,
            repo_root=repo_root,
            subject="AGENTS.md",
            revision=f"v{ordinal}",
            title="AGENTS.md as launched",
        )
    if blob:
        snapshot = str(_Path.home() / ".sase" / "instruction_snapshots" / str(blob))
        return MemoryVersionPin(
            scope_key=scope_key,
            repo_root=repo_root,
            subject="AGENTS.md",
            revision="snapshot",
            title="AGENTS.md as launched",
            snapshot_path=snapshot,
            snapshot_title="AGENTS.md as launched · not in git",
        )
    return None
