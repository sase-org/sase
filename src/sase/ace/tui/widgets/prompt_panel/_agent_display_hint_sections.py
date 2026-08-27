"""Whole-document hint renderers for proc-shell, monitor, and gate agents."""

from __future__ import annotations

from collections.abc import Mapping

from rich.text import Text

from sase.ace.tui.tools.report import SlowToolCallReportSpec

from ...models.agent import Agent
from ...models.fold_state import FoldLevel
from ._agent_display_header import AgentHeader
from ._agent_display_header_summary import detail_header_summary_is_complete
from ._agent_display_hint_annotators import (
    hint_gate_annotator,
    hint_monitor_annotator,
    hint_proc_shell_annotator,
)
from ._agent_display_state import AgentHintRender, DetailHeaderSummary, HeaderHintState
from ._agent_gate_section import GATE_SECTION_ID, build_gate_output, build_gate_section
from ._agent_monitor_section import (
    MONITOR_SECTION_ID,
    build_monitor_output,
    build_monitor_section,
)
from ._agent_proc_shell_section import (
    PROC_SHELL_SECTION_ID,
    build_proc_shell_output,
    build_proc_shell_preview,
    build_proc_shell_section,
)


def render_proc_shell_hint_document(
    panel: object,
    agent: Agent,
    header_text: AgentHeader,
    hint_counter: int,
    hint_mappings: dict[int, str],
    workspace_dir: str | None,
    lane_fold_level: FoldLevel,
    lane_fold_overrides: Mapping[str, FoldLevel],
    header_hint_state: HeaderHintState,
    tool_call_reports: dict[str, SlowToolCallReportSpec],
) -> AgentHintRender:
    """Render a proc-shell agent's hint document and publish it to *panel*."""
    annotate, hint_count = hint_proc_shell_annotator(
        hint_counter,
        hint_mappings,
        workspace_dir,
    )
    section_level = (
        lane_fold_overrides.get(PROC_SHELL_SECTION_ID, lane_fold_level)
        if isinstance(lane_fold_overrides, Mapping)
        else lane_fold_level
    )
    for part in build_proc_shell_preview(agent, annotate=annotate):
        if isinstance(part, Text):
            header_text.append_text(part)
    for part in build_proc_shell_section(
        agent,
        panel_level=section_level,
        annotate=annotate,
    ):
        if isinstance(part, Text):
            header_text.append_text(part)
    for part in build_proc_shell_output(agent, annotate=annotate):
        if isinstance(part, Text):
            header_text.append_text(part)
    hint_counter = hint_count()
    panel.update(panel._prepare_cached_hint_renderable(header_text))  # type: ignore[attr-defined]
    return AgentHintRender(
        file_hints=hint_mappings,
        tool_call_reports=tool_call_reports,
        commit_views=header_hint_state.commit_views,
        glossary_reports=header_hint_state.glossary_reports,
        memory_reports=header_hint_state.memory_reports,
        artifact_read_refs=header_hint_state.artifact_read_refs,
        header_enrichment_pending=False,
    )


def render_monitor_hint_document(
    panel: object,
    agent: Agent,
    header_text: AgentHeader,
    hint_counter: int,
    hint_mappings: dict[int, str],
    workspace_dir: str | None,
    lane_fold_level: FoldLevel,
    lane_fold_overrides: Mapping[str, FoldLevel],
    header_hint_state: HeaderHintState,
    tool_call_reports: dict[str, SlowToolCallReportSpec],
    summary: DetailHeaderSummary | None,
) -> AgentHintRender:
    """Render a monitor agent's hint document and publish it to *panel*."""
    annotate, hint_count = hint_monitor_annotator(
        hint_counter,
        hint_mappings,
        workspace_dir,
    )
    section_level = (
        lane_fold_overrides.get(MONITOR_SECTION_ID, lane_fold_level)
        if isinstance(lane_fold_overrides, Mapping)
        else lane_fold_level
    )
    for part in build_monitor_section(
        agent,
        panel_level=section_level,
        annotate=annotate,
    ):
        if isinstance(part, Text):
            header_text.append_text(part)
    for part in build_monitor_output(agent, annotate=annotate):
        if isinstance(part, Text):
            header_text.append_text(part)
    hint_counter = hint_count()
    panel.update(panel._prepare_cached_hint_renderable(header_text))  # type: ignore[attr-defined]
    if summary is None:
        panel._start_agent_detail_header_enrichment_from_context(agent)  # type: ignore[attr-defined]
    return AgentHintRender(
        file_hints=hint_mappings,
        tool_call_reports=tool_call_reports,
        commit_views=header_hint_state.commit_views,
        glossary_reports=header_hint_state.glossary_reports,
        memory_reports=header_hint_state.memory_reports,
        artifact_read_refs=header_hint_state.artifact_read_refs,
        header_enrichment_pending=not detail_header_summary_is_complete(summary),
    )


def render_gate_hint_document(
    panel: object,
    agent: Agent,
    header_text: AgentHeader,
    hint_counter: int,
    hint_mappings: dict[int, str],
    workspace_dir: str | None,
    lane_fold_level: FoldLevel,
    lane_fold_overrides: Mapping[str, FoldLevel],
    header_hint_state: HeaderHintState,
    tool_call_reports: dict[str, SlowToolCallReportSpec],
    summary: DetailHeaderSummary | None,
) -> AgentHintRender:
    """Render a gate agent's hint document and publish it to *panel*."""
    annotate, hint_count = hint_gate_annotator(
        hint_counter,
        hint_mappings,
        workspace_dir,
    )
    section_level = (
        lane_fold_overrides.get(GATE_SECTION_ID, lane_fold_level)
        if isinstance(lane_fold_overrides, Mapping)
        else lane_fold_level
    )
    for part in build_gate_section(
        agent,
        panel_level=section_level,
    ):
        if isinstance(part, Text):
            header_text.append_text(part)
    for part in build_gate_output(agent, annotate=annotate):
        if isinstance(part, Text):
            header_text.append_text(part)
    hint_counter = hint_count()
    panel.update(panel._prepare_cached_hint_renderable(header_text))  # type: ignore[attr-defined]
    if summary is None:
        panel._start_agent_detail_header_enrichment_from_context(agent)  # type: ignore[attr-defined]
    return AgentHintRender(
        file_hints=hint_mappings,
        tool_call_reports=tool_call_reports,
        commit_views=header_hint_state.commit_views,
        glossary_reports=header_hint_state.glossary_reports,
        memory_reports=header_hint_state.memory_reports,
        artifact_read_refs=header_hint_state.artifact_read_refs,
        header_enrichment_pending=not detail_header_summary_is_complete(summary),
    )
