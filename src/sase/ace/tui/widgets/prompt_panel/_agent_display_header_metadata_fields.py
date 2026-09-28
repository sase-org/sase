"""Orchestrator for core agent header metadata fields."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text

from sase.core.wait_dependency_resolution import TribeWaitBinding

from ...models.agent import Agent
from ._agent_display_header_metadata_identity import (
    append_auto_approve_field,
    append_identity_fields,
    append_project_fields,
)
from ._agent_display_header_metadata_remote import append_fleet_fields
from ._agent_display_header_metadata_sections import (
    append_retry_fields,
    append_timestamp_fields,
    append_tool_runs_field,
    append_turn_or_model_fields,
    append_wait_field,
)
from ._agent_display_state import DetailHeaderSummary, HeaderHintState
from ._agent_page_section import ResponsiveAgentPageSection
from ._agent_turn_section import ResponsiveTurnSection
from ._agent_wait_section import ResponsiveWaitSection
from ._helpers import extract_meta_fields


@dataclass(frozen=True, slots=True)
class _AgentMetadataFields:
    """Core metadata fields and responsive sections appended to a header."""

    meta_fields: list[tuple[str, str]]
    page_section: ResponsiveAgentPageSection | None
    wait_section: ResponsiveWaitSection | None
    turn_section: ResponsiveTurnSection | None


def append_agent_metadata_fields(
    text: Text,
    agent: Agent,
    *,
    cheap: bool,
    hint_state: HeaderHintState | None,
    summary: DetailHeaderSummary | None,
    agent_status_buckets: Mapping[str, str] | None,
    cached_bead_display: Callable[[Agent], object],
    clan_wait_member_statuses: Mapping[str, Sequence[tuple[str, str]]] | None = None,
    tribe_wait_bindings: Mapping[tuple[object, str], TribeWaitBinding] | None = None,
    runner_queue_ahead_count: int | None = None,
    responsive_ranges: MutableMapping[str, tuple[int, int]] | None = None,
    detach_identity: bool = False,
) -> _AgentMetadataFields:
    """Append core metadata and return workflow fields plus responsive lanes."""
    page_section = append_identity_fields(
        text,
        agent,
        summary,
        cached_bead_display,
        responsive_ranges,
    )

    step_output = agent.step_output if isinstance(agent.step_output, dict) else None
    meta_project = step_output.get("meta_project") if step_output is not None else None
    meta_patch = (
        step_output.get("meta_patch")
        or step_output.get("meta_changespec")  # legacy compatibility alias
        if step_output is not None
        else None
    )
    meta_fields = extract_meta_fields(step_output) if step_output is not None else []
    append_project_fields(
        text,
        agent,
        meta_project=meta_project,
        meta_patch=meta_patch,
    )
    append_fleet_fields(text, agent)

    append_auto_approve_field(text, agent)
    turn_section = append_turn_or_model_fields(text, agent, responsive_ranges)

    if (
        not agent.is_named_proc
        and summary is not None
        and (not cheap or detach_identity)
    ):
        from ._agent_xprompts import append_agent_xprompts_section

        project_key = (
            Path(agent.project_file).parent.name if agent.project_file else None
        )
        append_agent_xprompts_section(
            text,
            summary.xprompts_used,
            project_key=project_key,
            project_display_name=agent.project_display_name,
        )

    if agent.vcs_provider:
        text.append("VCS: ", style="bold #87D7FF")
        text.append(f"{agent.vcs_provider}\n", style="#5FD7AF")
    if agent.pid:
        text.append("PID: ", style="bold #87D7FF")
        text.append(f"{agent.pid}\n", style="#FF87D7 bold")
    if agent.bug:
        text.append("BUG: ", style="bold #87D7FF")
        text.append(f"{agent.bug}\n", style="bold underline #569CD6")
    append_tool_runs_field(text, agent, summary)

    if agent.is_named_proc:
        wait_section = None
    else:
        wait_section = append_wait_field(
            text,
            agent,
            agent_status_buckets,
            clan_wait_member_statuses,
            tribe_wait_bindings,
            runner_queue_ahead_count,
            summary.wait_bead_statuses if summary is not None else None,
            responsive_ranges,
        )
        append_retry_fields(text, agent)
    append_timestamp_fields(text, agent, hint_state)
    return _AgentMetadataFields(meta_fields, page_section, wait_section, turn_section)
