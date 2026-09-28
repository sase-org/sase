"""No-I/O availability probes for deck subtitles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from collections.abc import Mapping

from ..file_panel._file_list import desired_file_pages
from .._llm_calls_panel_fetching import cached_tool_call_count
from .._agent_detail_helpers import _ACTIVE_STATUSES

if TYPE_CHECKING:
    from ...models.agent import Agent
    from .model import DeckId


@dataclass(frozen=True)
class DeckAvailability:
    """Content presence for one deck; None means unknown."""

    has_content: bool | None
    count: int | None
    runs_count: int | None = None
    calls_count: int | None = None


DeckAvailabilitySet = Mapping["DeckId", DeckAvailability]


def probe_files_deck(agent: Agent, *, attempt_number: int | None) -> DeckAvailability:
    """Probe Files availability without I/O."""
    if attempt_number is not None:
        return DeckAvailability(False, 0)
    if agent.is_clan_container or agent.is_named_proc:
        return DeckAvailability(False, 0)
    if agent.is_workflow_child and agent.step_type in ("bash", "python"):
        return DeckAvailability(False, 0)
    pages, _default = desired_file_pages(agent)
    if pages:
        return DeckAvailability(True, len(pages))
    if agent.status not in _ACTIVE_STATUSES and getattr(agent, "all_files", None):
        all_files = list(agent.all_files)
        if all_files:
            return DeckAvailability(True, len(all_files))
    if agent.status in _ACTIVE_STATUSES:
        return DeckAvailability(None, None)
    if agent.workspace_num is not None and not agent.fleet_origin_alias:
        return DeckAvailability(None, None)
    return DeckAvailability(False, 0)


def probe_tools_deck(agent: Agent, *, attempt_number: int | None) -> DeckAvailability:
    """Probe Tools availability without I/O.

    The deck has content when it has LLM calls **or** tool runs. The
    Runs part reads the node-summary LRU plus the glance snapshot, with
    no I/O, and opens for monitor turns and named procs that own runs.
    Pinned attempts, clans, tribes, and remote rows stay without Runs.
    """
    from ...llm_calls import supports_slow_tool_sources

    if attempt_number is not None:
        return DeckAvailability(False, 0)
    if agent.is_clan_container:
        return DeckAvailability(False, 0)
    calls_has: bool | None
    calls_count: int | None
    if agent.is_named_proc or not supports_slow_tool_sources(agent):
        calls_has, calls_count = False, 0
    else:
        count = cached_tool_call_count(agent)
        if count is None:
            calls_has, calls_count = None, None
        elif count == 0:
            calls_has, calls_count = False, 0
        else:
            calls_has, calls_count = True, count
    try:
        from ...tool_runs.flag import tool_runs_enabled
    except Exception:
        return _calls_only_availability(calls_has, calls_count)
    try:
        enabled = bool(tool_runs_enabled())
    except Exception:
        enabled = False
    if not enabled:
        return _calls_only_availability(calls_has, calls_count)
    from ...tool_runs.deck import probe_tool_runs_card

    try:
        runs_has, runs_count = probe_tool_runs_card(
            agent, attempt_number=attempt_number
        )
    except Exception:
        runs_has, runs_count = None, 0
    if runs_has is None and calls_has is None:
        return DeckAvailability(None, None, None, calls_count)
    has_content: bool | None = bool(calls_has) or bool(runs_has)
    if runs_has is None and not calls_has:
        has_content = None
    return DeckAvailability(
        has_content,
        calls_count,
        runs_count=runs_count if runs_has else 0,
        calls_count=calls_count,
    )


def _calls_only_availability(
    calls_has: bool | None, calls_count: int | None
) -> DeckAvailability:
    """Return the pre-``tools-deck-cards`` Tools availability (flag off)."""
    if calls_has is None:
        return DeckAvailability(None, None)
    if not calls_has:
        return DeckAvailability(False, 0)
    return DeckAvailability(True, calls_count)


def probe_final_deck(agent: Agent, *, attempt_number: int | None) -> DeckAvailability:
    """Probe FINAL availability without I/O (plan §3.6).

    The deck has content when the node's runs have at least one selected
    instance — a handoff-skipped run counts too, since its Overview
    explains the skip. Clans, tribes, proc nodes and legacy runs with no
    summary stay unavailable. A pinned attempt (``D``) does not force the
    deck empty: FINAL follows the pinned attempt's artifacts dir when it
    resolves, so the probe still reads the summaries.
    """
    del attempt_number
    try:
        if agent.is_clan_container or agent.is_named_proc:
            return DeckAvailability(False, 0)
    except Exception:
        return DeckAvailability(None, None)
    try:
        summaries = [agent.finalizer_status]
    except Exception:
        return DeckAvailability(None, None)
    try:
        from ...models.agent_session_members import (
            concrete_agent_session_turn_rows,
            is_sequential_agent_session_container,
        )

        if is_sequential_agent_session_container(agent):
            for turn in concrete_agent_session_turn_rows(agent):
                try:
                    summaries.append(turn.finalizer_status)
                except Exception:
                    continue
    except Exception:
        pass
    known = [s for s in summaries if s is not None]
    if not known:
        try:
            if agent.status in _ACTIVE_STATUSES:
                return DeckAvailability(None, None)
        except Exception:
            pass
        return DeckAvailability(False, 0)
    ids: set[str] = set()
    skipped = False
    running = False
    for summary in known:
        try:
            instances = list(summary.instances or ())
        except Exception:
            instances = []
        for instance in instances:
            try:
                instance_id = instance.id
            except Exception:
                continue
            if instance_id:
                ids.add(str(instance_id))
        try:
            phase = summary.phase
        except Exception:
            phase = None
        if phase == "skipped":
            skipped = True
        if phase in ("declaring", "executing"):
            running = True
    if ids or skipped:
        return DeckAvailability(True, len(ids))
    if running:
        return DeckAvailability(None, None)
    try:
        if agent.status in _ACTIVE_STATUSES:
            return DeckAvailability(None, None)
    except Exception:
        pass
    return DeckAvailability(False, 0)
