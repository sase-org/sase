"""Build the Agents-tab ``V`` metadata pager document.

Pure build code: no widget access, no Textual imports. Callers dispatch this
through ``asyncio.to_thread`` (or an equivalent worker) before touching UI
state, since resolving the SASE CONTEXT summary does real file/bead I/O.
"""

from __future__ import annotations

from rich.text import Text

from sase.agent.status_buckets import AGENT_STATUS_BUCKET_GLYPHS, agent_status_bucket
from sase.llm_provider.model_label import append_model_field
from sase.pager.document import PagerDocument, PagerSection
from sase.pager.link_context import LinkResolutionContext
from sase.pager.link_scan import PagerOrigin
from sase.project_display_names import humanize_cl_name

from ...models.agent import Agent
from ...models.agent_owner_badge import agent_owner_badge_label
from ...widgets._agent_list_styling import (
    _AGENT_NAME_ANNOTATION_STYLE,
    _FAMILY_NAME_STYLE,
    _OWNER_BADGE_STYLE,
    _PROC_SHELL_ID_STYLE,
)
from ...widgets.prompt_panel._agent_bead_section import ResponsiveBeadSection
from ...widgets.prompt_panel._agent_context import append_agent_context_section
from ...widgets.prompt_panel._agent_display_header_metadata import (
    _LEGACY_MEMBER_STATUS_STYLES,
)
from ...widgets.prompt_panel._agent_display_header_summary import (
    build_detail_header_summary,
)
from ...widgets.prompt_panel._agent_display_state import DetailHeaderSummary
from ...widgets.prompt_panel._agent_plan_section import ResponsivePlanSection
from ...widgets.prompt_panel._helpers import project_display_label
from ._metadata_pager_conversation import build_agent_conversation_sections

_LABEL_STYLE = "bold #87D7FF"
_AGENT_KIND = "agent"
_SASE_CONTEXT_HEADING = "SASE CONTEXT"


def _label(text: Text, label: str) -> None:
    text.append(f"{label}: ", style=_LABEL_STYLE)


def _name_style(agent: Agent) -> str:
    if agent.is_family_container_row:
        return _FAMILY_NAME_STYLE
    if agent.is_proc_shell:
        return _PROC_SHELL_ID_STYLE
    return _AGENT_NAME_ANNOTATION_STYLE


def _identity_section(agent: Agent) -> PagerSection | None:
    text = Text()
    presented_name = agent.presented_agent_name or agent.agent_name
    if presented_name:
        _label(text, "Name")
        text.append(f"{presented_name}\n", style=_name_style(agent))
    owner_badge = agent_owner_badge_label(agent)
    if owner_badge:
        _label(text, "Owner")
        text.append(f"{owner_badge}\n", style=_OWNER_BADGE_STYLE)
    if agent.agent_family:
        _label(text, "Family")
        text.append(f"{agent.agent_family}\n", style=_FAMILY_NAME_STYLE)
    if agent.agent_clan:
        _label(text, "Clan")
        text.append(f"{agent.agent_clan}\n")
    if agent.tribe:
        _label(text, "Tribe")
        text.append(f"{agent.tribe}\n")
    if agent.clan_tribes:
        _label(text, "Tribes")
        text.append(f"{', '.join(agent.clan_tribes)}\n")
    if agent.status:
        bucket = agent_status_bucket(agent)
        glyph = AGENT_STATUS_BUCKET_GLYPHS.get(bucket, "?")
        style = _LEGACY_MEMBER_STATUS_STYLES.get(bucket, "bold")
        _label(text, "Status")
        text.append(f"{glyph} {agent.display_status}", style=style)
        if agent.status_bucket:
            text.append(f" ({agent.status_bucket})", style="dim")
        text.append("\n")
    if agent.is_retry_attempt or agent.is_retried_parent:
        _label(text, "Retry chain")
        text.append("↻ ", style="bold #FFAF00")
        if agent.is_retry_attempt:
            text.append(f"attempt #{agent.retry_attempt}", style="#FFAF00")
            if agent.retry_error_category:
                text.append(f" ({agent.retry_error_category})", style="dim #FFAF00")
        if agent.is_retried_parent:
            if agent.is_retry_attempt:
                text.append(", ", style="dim")
            text.append("handed off to retry", style="dim #FFAF00")
        text.append("\n")
    if not text.plain:
        return None
    return PagerSection(
        identity="agent-identity", title="IDENTITY", kind=_AGENT_KIND, body=text
    )


def _model_section(agent: Agent) -> PagerSection | None:
    text = Text()
    append_model_field(
        text, agent.model, agent.llm_provider, agent.reasoning_effort, agent.model_alias
    )
    if agent.fallback_model:
        _label(text, "Fallback")
        style = "bold #FF8700" if agent.using_fallback else "dim #FF8700"
        text.append(f"{agent.fallback_model}\n", style=style)
    if not text.plain:
        return None
    return PagerSection(
        identity="agent-model", title="MODEL", kind=_AGENT_KIND, body=text
    )


def _workspace_section(agent: Agent) -> PagerSection | None:
    text = Text()
    workspace_num = agent.effective_workspace_num
    if workspace_num is not None and workspace_num > 0:
        _label(text, "Workspace")
        text.append(f"#{workspace_num}\n", style="#5FD7FF")
    if agent.workspace_dir:
        _label(text, "Directory")
        text.append(f"{agent.workspace_dir}\n", style="#D7D7FF")
    if agent.is_project_agent:
        _label(text, "Project")
        text.append(f"{project_display_label(agent, agent.cl_name)}\n", style="#00D7AF")
    else:
        _label(text, "Patch")
        text.append(humanize_cl_name(agent.cl_name), style="#00D7AF")
        if agent.cl_num:
            text.append(" (")
            text.append(agent.cl_num, style="bold underline #569CD6")
            text.append(")")
        text.append("\n")
    if agent.vcs_provider:
        _label(text, "VCS")
        text.append(f"{agent.vcs_provider}\n", style="#5FD7AF")
    if agent.linked_repos:
        _label(text, "Linked repos")
        text.append("\n")
        for repo in agent.linked_repos:
            text.append(f"  {repo.name}", style="#5FD7FF")
            text.append(f" — {repo.workspace_dir}\n", style="dim")
    if not text.plain:
        return None
    return PagerSection(
        identity="agent-workspace", title="WORKSPACE", kind=_AGENT_KIND, body=text
    )


def _timeline_section(agent: Agent) -> PagerSection | None:
    text = Text()
    if agent.timestamps_display:
        _label(text, "Timestamps")
        text.append(f"{agent.timestamps_display}\n", style="#D7D7FF")
    duration_label = "Elapsed" if agent.stop_time is None else "Duration"
    _label(text, duration_label)
    text.append(f"{agent.duration_display}\n", style="#D7D7FF")
    if not text.plain:
        return None
    return PagerSection(
        identity="agent-timeline", title="TIMELINE", kind=_AGENT_KIND, body=text
    )


def _content_section(agent: Agent) -> PagerSection | None:
    text = Text()
    if agent.response_path:
        _label(text, "Response")
        text.append(f"{agent.response_path}\n", style="dim")
    if agent.diff_path:
        _label(text, "Diff")
        text.append(f"{agent.diff_path}\n", style="dim")
    if agent.output_path:
        _label(text, "Output")
        text.append(f"{agent.output_path}\n", style="dim")
    plan_path = agent.plan_path or agent.archived_plan_path or agent.sdd_plan_path
    if plan_path:
        _label(text, "Plan")
        text.append(f"{plan_path}\n", style="dim")
    artifacts_dir = agent.get_artifacts_dir()
    if artifacts_dir:
        _label(text, "Artifacts dir")
        text.append(f"{artifacts_dir}\n", style="dim")
    if agent.extra_files:
        _label(text, "Extra files")
        text.append("\n")
        for extra_file in agent.extra_files:
            text.append(f"  {extra_file}\n", style="dim")
    if not text.plain:
        return None
    return PagerSection(
        identity="agent-content", title="CONTENT", kind=_AGENT_KIND, body=text
    )


def _sase_context_lanes_text(agent: Agent, summary: DetailHeaderSummary) -> Text:
    """Return the SASE CONTEXT lane content, without its own embedded heading.

    ``append_agent_context_section`` always prefixes its rendered lanes with a
    major-section divider and a ``SASE CONTEXT`` heading, which is correct for
    the panel (no other chrome names the section) but would double up with
    the pager's own auto-generated section rule. Locating the heading text
    and slicing everything after it is more robust than hard-coding the
    preamble's line count, which is an internal formatting detail of
    ``append_major_section_divider``/``append_section_heading``.
    """
    scratch = Text()
    plan_section = (
        ResponsivePlanSection(summary.associated_plan)
        if summary.associated_plan is not None
        else None
    )
    append_agent_context_section(
        scratch,
        memory_reads=summary.memory_reads,
        glossary_reads=summary.glossary_reads,
        skill_uses=summary.skill_uses,
        opened_workspaces=summary.opened_workspaces,
        bead_section=None,
        plan_section=plan_section,
        agent=agent,
        delta_entries=summary.delta_entries,
        linked_delta_groups=summary.linked_delta_groups,
        artifact_file_paths=summary.artifact_file_paths,
        artifact_reads=summary.artifact_reads,
        bead_touch_entries=summary.bead_touch_entries,
        ready_lanes=summary.ready_lanes,
    )
    plain = scratch.plain
    heading_start = plain.find(_SASE_CONTEXT_HEADING)
    if heading_start < 0:
        return scratch
    newline_index = plain.find("\n", heading_start)
    if newline_index < 0:
        return Text()
    return scratch[newline_index + 1 :]


def _sase_context_section(
    agent: Agent, summary: DetailHeaderSummary
) -> PagerSection | None:
    text = _sase_context_lanes_text(agent, summary)
    if not text.plain.strip():
        return None
    return PagerSection(
        identity="agent-sase-context",
        title=_SASE_CONTEXT_HEADING,
        kind=_AGENT_KIND,
        body=text,
    )


def _bead_section(summary: DetailHeaderSummary) -> PagerSection | None:
    bead_summary = summary.bead_summary
    if bead_summary is None:
        return None
    return PagerSection(
        identity="agent-bead",
        title="BEAD",
        kind="bead",
        body=ResponsiveBeadSection(bead_summary),
    )


def build_agent_metadata_document(
    agent: Agent,
    *,
    link_context: LinkResolutionContext | None = None,
) -> PagerDocument:
    """Read the agent's full SASE CONTEXT summary and assemble one document.

    Does real file/bead I/O to resolve the SASE CONTEXT lanes and so must run
    off the event loop -- callers dispatch this through ``asyncio.to_thread``
    before touching UI state.
    """
    summary = build_detail_header_summary(agent)
    sections = tuple(
        section
        for section in (
            _identity_section(agent),
            _model_section(agent),
            _workspace_section(agent),
            _timeline_section(agent),
            _content_section(agent),
            _sase_context_section(agent, summary),
            _bead_section(summary),
            *build_agent_conversation_sections(agent),
        )
        if section is not None
    )
    if not sections:
        sections = (
            PagerSection(
                identity="agent-identity",
                title="IDENTITY",
                kind=_AGENT_KIND,
                body=Text("No metadata available for this agent.\n", style="dim"),
            ),
        )
    title = agent.presented_agent_name or agent.agent_name or agent.cl_name
    return PagerDocument(
        sections=sections,
        title=title,
        origin=PagerOrigin.AGENT,
        link_context=link_context,
    )


__all__ = ["build_agent_metadata_document"]
