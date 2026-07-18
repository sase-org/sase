"""Header rendering for the agent prompt panel."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from datetime import datetime as DateTime
from pathlib import Path
from typing import TYPE_CHECKING, Self

from rich.console import Console, ConsoleOptions, RenderResult
from rich.style import StyleType
from rich.syntax import Syntax
from rich.text import Span, Text

from sase.agent.status_buckets import (
    AGENT_STATUS_BUCKET_GLYPHS,
    status_bucket_for_values,
)
from sase.ace.tui.tools._constants import SLOW_TOOL_CALL_THRESHOLD_MS
from sase.project_display_names import humanize_cl_name

from ...models.agent import Agent, AgentType
from ...models.agent_bead import cached_bead_display
from ...models.fold_state import FoldLevel
from .._agent_list_styling import (
    _AGENT_NAME_ANNOTATION_STYLE,
    _FAMILY_NAME_STYLE,
)
from ._agent_bead_section import ResponsiveBeadSection
from ._agent_display_state import DetailHeaderSummary, HeaderHintState
from ._agent_display_family import (
    FAMILY_IDENTITY_COLOR,
    append_family_fold_heading,
    append_family_member_roster,
    effective_family_fold_level,
    fold_number,
)
from ._agent_plan_section import ResponsivePlanSection
from ._file_path_hints import append_text_with_file_hints
from ._helpers import (
    WORKFLOW_VARIABLES_SECTION_LABEL,
    append_major_section_divider,
    append_model_field,
    append_section_heading,
    extract_meta_fields,
    project_display_label,
    should_render_agent_detail_model,
)

if TYPE_CHECKING:
    from ...models._agent_clan_sections import ClanSectionSnapshot
    from ._member_roster import MemberJumpMap
from ._agent_output_variables import append_agent_output_variables_section


_UNASSIGNED_AGENT_NAME_DISPLAY = "unassigned"
_UNKNOWN_WAIT_AGENT_GLYPH = "?"
_UNKNOWN_WAIT_AGENT_GLYPH_STYLE = "bold #FFAF5F"
_WAITING_VALUE_STYLE = "#FF87D7"
# Glyphs mirror ``AGENT_STATUS_BUCKET_GLYPHS``; colors mirror agent-row status
# accents in ``_agent_list_render_agent.py`` / ``models.agent_status``.
_WAIT_STATUS_BADGES: dict[str, tuple[str, str]] = {
    "Running": (AGENT_STATUS_BUCKET_GLYPHS["Running"], "bold #FFD700"),
    "Waiting": (AGENT_STATUS_BUCKET_GLYPHS["Waiting"], "bold #AF87FF"),
    "Starting": (AGENT_STATUS_BUCKET_GLYPHS["Starting"], "bold #87D7FF"),
    "Done": (AGENT_STATUS_BUCKET_GLYPHS["Done"], "bold #5FD75F"),
    "Failed": (AGENT_STATUS_BUCKET_GLYPHS["Failed"], "bold #FF5F5F"),
    "Stopped": (AGENT_STATUS_BUCKET_GLYPHS["Stopped"], "bold #8787AF"),
}
_AUTO_APPROVE_KIND_STYLES: dict[str, tuple[str, str]] = {
    "plan": ("\u26a1 PLAN", "bold #5FD7FF"),
    "tale": ("\u26a1 TALE", "bold #FFD75F"),
    "epic": ("\u26a1 EPIC", "bold #AF87FF"),
}
_LEGACY_MEMBER_STATUS_STYLES: dict[str, str] = {
    "Stopped": "bold #FFAF5F",
    "Starting": "bold #87D7FF",
    "Running": "bold #FFD700",
    "Waiting": "bold #AF87FF",
    "Failed": "bold #FF5F5F",
    "Done": "bold #5FD75F",
}


class _AgentHeaderRenderable:
    """Mutable logical header with retained responsive context sections."""

    __slots__ = ("_sections", "_text")

    def __init__(
        self,
        text: Text,
        sections: tuple[
            tuple[int, int, ResponsiveBeadSection | ResponsivePlanSection], ...
        ],
    ) -> None:
        self._text = text
        self._sections = sections

    @property
    def plain(self) -> str:
        """Return the complete logical header text for inspection and search."""
        return self._text.plain

    @property
    def spans(self) -> list[Span]:
        """Return logical text spans, including the plan section fields."""
        return self._text.spans

    @property
    def end(self) -> str:
        """Return the Rich line ending applied after this header renderable."""
        return self._text.end

    @end.setter
    def end(self, value: str) -> None:
        """Set the Rich line ending applied after this header renderable."""
        self._text.end = value

    def append(
        self,
        text: str | Text,
        style: StyleType | None = None,
    ) -> Self:
        """Append content after the plan section without moving the section."""
        self._text.append(text, style=style)
        return self

    def append_text(self, text: Text) -> Self:
        """Append styled Rich text after the plan section."""
        self._text.append_text(text)
        return self

    def stylize(
        self,
        style: StyleType,
        start: int = 0,
        end: int | None = None,
    ) -> None:
        """Apply a Rich style to a logical header range."""
        self._text.stylize(style, start, end)

    def __rich_console__(
        self,
        _console: Console,
        _options: ConsoleOptions,
    ) -> RenderResult:
        cursor = 0
        for start, end, section in self._sections:
            prefix = self._text[cursor:start]
            prefix.end = ""
            yield prefix
            yield section
            cursor = end

        suffix = self._text[cursor:]
        suffix.end = self._text.end
        yield suffix


AgentHeader = Text | _AgentHeaderRenderable


def _append_auto_approve_field(text: Text, agent: Agent) -> None:
    """Append the ``Auto:`` auto-approve kind field for autonomous agents."""
    if not agent.approve:
        return
    kind = agent.auto_approve_plan_action or "plan"
    token, style = _AUTO_APPROVE_KIND_STYLES.get(
        kind, (f"\u26a1 {kind.upper()}", "bold #BCBCBC")
    )
    text.append("Auto: ", style="bold #87D7FF")
    text.append(f"{token}\n", style=style)


def _append_legacy_parallel_members_section(text: Text, agent: Agent) -> None:
    """Preserve archived parallel-family member summaries.

    Modern parallel launches project to synthetic clan containers and return
    from :func:`build_header_text` before this compatibility path. Only old
    records carrying ``agent_family_parallel`` retain the root-shaped panel.
    """
    if not agent.agent_family_parallel:
        return

    from ...models._agent_clan import clan_members

    members = sorted(
        clan_members(agent),
        key=lambda member: (
            member.start_time is None,
            member.start_time.isoformat() if member.start_time is not None else "",
            member.agent_name or "",
        ),
    )
    if not members:
        return

    append_major_section_divider(text)
    heading = Text("MEMBERS", style="bold #D7AF5F underline")
    heading.append(f" · {len(members)}", style="dim")
    append_section_heading(text, heading, section_id="members")

    for member in members:
        role = member.agent_family_role or "member"
        name = member.agent_name or _UNASSIGNED_AGENT_NAME_DISPLAY
        bucket = status_bucket_for_values(member.status)
        glyph = AGENT_STATUS_BUCKET_GLYPHS[bucket]
        status_style = _LEGACY_MEMBER_STATUS_STYLES[bucket]
        model = member.model or "default"

        text.append(role, style="italic #AF87FF")
        text.append(" · ", style="dim")
        text.append(name, style=_AGENT_NAME_ANNOTATION_STYLE)
        text.append(" · ", style="dim")
        text.append(f"{glyph} {member.display_status}", style=status_style)
        text.append(" · ", style="dim")
        text.append(model, style="#5FD7FF")
        text.append(" · ", style="dim")
        text.append(f"{member.duration_display}\n", style="dim #D7D7FF")


def build_header_text(
    agent: Agent,
    *,
    cheap: bool = False,
    hint_state: HeaderHintState | None = None,
    summary: DetailHeaderSummary | None = None,
    agent_status_buckets: Mapping[str, str] | None = None,
    slow_tool_call_threshold_ms: int = SLOW_TOOL_CALL_THRESHOLD_MS,
    unread_agent_ids: Collection[tuple[AgentType, str, str | None]] = (),
    clan_snapshot: ClanSectionSnapshot | None = None,
    clan_fold_level: FoldLevel = FoldLevel.COLLAPSED,
    clan_section_fold_overrides: Mapping[str, FoldLevel] | None = None,
    family_fold_level: FoldLevel | None = None,
    family_section_fold_overrides: Mapping[str, FoldLevel] | None = None,
    member_jump_map_publisher: Callable[[MemberJumpMap], None] | None = None,
) -> tuple[AgentHeader, Syntax | None]:
    """Build the agent metadata section with trailing separator.

    Contains agent metadata (name, workspace, model, timestamps, etc.),
    error information, and a trailing separator line.

    Args:
        agent: The agent to render a header for.
        cheap: When True, skip any disk-touching enrichments (e.g. xprompt
            metadata loaded from disk). Used by the j/k immediate
            path so the header renders within one frame; the debounced full
            update fills in the omitted fields.
        hint_state: Optional mutable file-hint state. When provided, path-like
            timestamp details are rendered with selectable hint markers.
        summary: Optional precomputed/cached header enrichments. Expensive
            sections are rendered only from this object; the header builder
            does not do artifact listing, diff discovery, or bead lookup.
        agent_status_buckets: Exact currently known agent names mapped to
            status buckets. When provided, each waited-for name gets a status
            badge, or an unknown-name badge when absent.

    Returns:
        Tuple of (header_text, error_traceback_syntax).
    """
    if agent.is_clan_container:
        from ._agent_display_clan import build_clan_detail_text

        return (
            build_clan_detail_text(
                agent,
                unread_ids=unread_agent_ids,
                snapshot=clan_snapshot,
                fold_level=clan_fold_level,
                section_fold_overrides=clan_section_fold_overrides,
                member_jump_map_publisher=member_jump_map_publisher,
            ),
            None,
        )

    header_text = Text()
    family_overrides = family_section_fold_overrides or {}
    family_fold_enabled = (
        agent.is_family_container_row and family_fold_level is not None
    )
    resolved_family_fold_level = family_fold_level or FoldLevel.COLLAPSED

    # Agent name is always the first metadata row in the details panel.
    header_text.append("Name: ", style="bold #87D7FF")
    presented_name = agent.presented_agent_name or agent.agent_name
    if presented_name:
        name_style = (
            _FAMILY_NAME_STYLE
            if agent.is_family_container_row
            else _AGENT_NAME_ANNOTATION_STYLE
        )
        header_text.append(f"{presented_name}\n", style=name_style)
        # Phase identity belongs exclusively to the deferred BEAD context lane.
        # The cold path remains memory-only and omits that lane until its typed
        # summary arrives. Non-phase compatibility rows still use only cached
        # bead state and never touch bead storage here.
        is_known_phase = bool(agent.phase_bead_id or agent.agent_family_role == "phase")
        if summary is not None and summary.phase_bead is not None:
            bead_display = None
        elif is_known_phase:
            bead_display = None
        elif summary is not None:
            bead_display = summary.bead_display
        else:
            cached_display = cached_bead_display(agent)
            bead_display = cached_display if isinstance(cached_display, str) else None
        if bead_display:
            header_text.append("Bead: ", style="bold #87D7FF")
            header_text.append(f"{bead_display}\n", style="bold #FFAF00")
    else:
        header_text.append(f"{_UNASSIGNED_AGENT_NAME_DISPLAY}\n", style="dim")

    # Spawn-on-retry: render a retry-chain breadcrumb when the agent is
    # part of one (either a retry attempt or a parent that handed off).
    if agent.is_retry_attempt or agent.is_retried_parent:
        header_text.append("Retry chain: ", style="bold #87D7FF")
        header_text.append("↻ ", style="bold #FFAF00")
        if agent.is_retry_attempt:
            header_text.append(f"attempt #{agent.retry_attempt}", style="#FFAF00")
            if agent.retry_error_category:
                header_text.append(
                    f" ({agent.retry_error_category})", style="dim #FFAF00"
                )
        if agent.is_retried_parent:
            if agent.is_retry_attempt:
                header_text.append(", ", style="dim")
            header_text.append("handed off to retry", style="dim #FFAF00")
        header_text.append("\n")

    # Extract meta_* overrides from step_output
    step_output = agent.step_output if isinstance(agent.step_output, dict) else None
    meta_project = step_output.get("meta_project") if step_output is not None else None
    meta_changespec = (
        step_output.get("meta_changespec") if step_output is not None else None
    )
    meta_fields = extract_meta_fields(step_output) if step_output is not None else []

    # For workflow step agents, show "Step" instead of "ChangeSpec".
    if agent.is_workflow_step_child and agent.step_name:
        header_text.append("Step: ", style="bold #87D7FF")
        header_text.append(f"{agent.step_name}\n", style="#00D7AF")
    elif meta_changespec:
        header_text.append("ChangeSpec: ", style="bold #87D7FF")
        header_text.append(f"{meta_changespec}", style="#00D7AF")
        if agent.cl_num:
            header_text.append(" (")
            header_text.append(agent.cl_num, style="bold underline #569CD6")
            header_text.append(")")
        header_text.append("\n")
    elif meta_project:
        header_text.append("Project: ", style="bold #87D7FF")
        header_text.append(
            f"{project_display_label(agent, meta_project)}\n", style="#00D7AF"
        )
    elif agent.is_project_agent:
        header_text.append("Project: ", style="bold #87D7FF")
        header_text.append(
            f"{project_display_label(agent, agent.cl_name)}\n", style="#00D7AF"
        )
    else:
        # ChangeSpec name
        header_text.append("ChangeSpec: ", style="bold #87D7FF")
        header_text.append(humanize_cl_name(agent.cl_name), style="#00D7AF")
        if agent.cl_num:
            header_text.append(" (")
            header_text.append(agent.cl_num, style="bold underline #569CD6")
            header_text.append(")")
        header_text.append("\n")

    # Workspace (if available)
    # Hide workspace for deferred-workspace agents (workspace_num=0 means
    # no workspace allocated yet, used by WAITING agents)
    workspace_num = agent.effective_workspace_num
    if workspace_num is not None and workspace_num > 0:
        header_text.append("Workspace: ", style="bold #87D7FF")
        header_text.append(f"#{workspace_num}\n", style="#5FD7FF")

    # Workflow (if available) -- only for multi-step workflows, not
    # appears-as-agent workflows (which are embedded, not standalone)
    if agent.workflow and not agent.appears_as_agent:
        header_text.append("Workflow: ", style="bold #87D7FF")
        header_text.append(f"{agent.workflow}\n")

    # Auto-approve kind (autonomous agents). Rendered immediately before the
    # Model/Xprompts rows so an auto-approved agent shows ``Auto:`` ahead of
    # them rather than after.
    _append_auto_approve_field(header_text, agent)

    # Model (with provider-themed styling). Rendered after ``Auto:`` and
    # before the ``Xprompts:`` section. This is agent-field-only and reads no
    # disk artifacts, so it renders on both the cheap and full paths without
    # touching the disk-backed xprompt summary.
    if should_render_agent_detail_model(agent):
        append_model_field(
            header_text, agent.model, agent.llm_provider, agent.reasoning_effort
        )

    # Xprompts (if available) - only for agent/prompt steps.
    # Skipped on the cheap path: load_xprompts_used touches disk, and
    # the debounced full update will populate this field shortly after.
    if not cheap and summary is not None:
        from ._agent_xprompts import append_agent_xprompts_section

        project_key = (
            Path(agent.project_file).parent.name if agent.project_file else None
        )
        append_agent_xprompts_section(
            header_text,
            summary.xprompts_used,
            project_key=project_key,
            project_display_name=agent.project_display_name,
        )

    # VCS provider
    if agent.vcs_provider:
        header_text.append("VCS: ", style="bold #87D7FF")
        header_text.append(f"{agent.vcs_provider}\n", style="#5FD7AF")

    # PID (if available)
    if agent.pid:
        header_text.append("PID: ", style="bold #87D7FF")
        header_text.append(f"{agent.pid}\n", style="#FF87D7 bold")

    # BUG field (if available)
    if agent.bug:
        header_text.append("BUG: ", style="bold #87D7FF")
        header_text.append(f"{agent.bug}\n", style="bold underline #569CD6")

    # Waiting info (dependencies, time floor, and final runner-slot stage).
    from sase.ace.tui.models.agent import wait_display_agent

    wait_agent = wait_display_agent(agent)
    has_slot_wait = bool(
        wait_agent.slot_requested_at and wait_agent.wait_runners is not None
    )
    if (
        wait_agent.waiting_for
        or wait_agent.wait_duration
        or wait_agent.wait_until
        or has_slot_wait
    ):
        from sase.ace.tui.models.agent import (
            format_compact_duration,
            format_wait_until,
            wait_remaining_seconds,
        )

        header_text.append("Wait: ", style="bold #87D7FF")
        appended_dependency_names = False
        if wait_agent.waiting_for:
            for index, name in enumerate(wait_agent.waiting_for):
                if index:
                    header_text.append(", ", style=_WAITING_VALUE_STYLE)
                header_text.append(name, style=_WAITING_VALUE_STYLE)
                if agent_status_buckets is not None:
                    bucket = agent_status_buckets.get(name)
                    badge = (
                        _WAIT_STATUS_BADGES.get(bucket) if bucket is not None else None
                    )
                    if badge is None:
                        glyph, style = (
                            _UNKNOWN_WAIT_AGENT_GLYPH,
                            _UNKNOWN_WAIT_AGENT_GLYPH_STYLE,
                        )
                    else:
                        glyph, style = badge
                    header_text.append(" ")
                    header_text.append(glyph, style=style)
            appended_dependency_names = True
        time_part: str | None = None
        if wait_agent.wait_until:
            target_label = format_wait_until(wait_agent.wait_until)
            time_part = f"until {target_label}"
        elif wait_agent.wait_duration:
            time_part = format_compact_duration(wait_agent.wait_duration)
        if time_part:
            if appended_dependency_names:
                header_text.append(" + ", style=_WAITING_VALUE_STYLE)
            header_text.append(time_part, style=_WAITING_VALUE_STYLE)
            appended_dependency_names = True
        remaining = wait_remaining_seconds(agent)
        if remaining is not None and remaining > 0:
            header_text.append(
                f" ({format_compact_duration(remaining)} left)",
                style="dim #AF87FF",
            )
        if has_slot_wait:
            if appended_dependency_names:
                header_text.append(" + ", style=_WAITING_VALUE_STYLE)
            in_use = wait_agent.runner_slots_in_use
            threshold = wait_agent.wait_runners
            assert threshold is not None
            if wait_agent.wait_runners_explicit:
                header_text.append(f"runners ≤ {threshold}", style=_WAITING_VALUE_STYLE)
                if threshold == 0:
                    header_text.append(" (drain barrier)", style="bold #AF87FF")
                if in_use is not None:
                    noun = "runner" if in_use == 1 else "runners"
                    header_text.append(
                        f" · {in_use} {noun} still running",
                        style="dim #AF87FF",
                    )
            elif in_use is not None:
                header_text.append(
                    f"runners: {in_use}/{threshold + 1} in use",
                    style=_WAITING_VALUE_STYLE,
                )
            else:
                header_text.append(
                    f"runners: cap {threshold + 1}",
                    style=_WAITING_VALUE_STYLE,
                )
            position = wait_agent.runner_slot_queue_position
            queue_size = wait_agent.runner_slot_queue_size
            if position is not None and queue_size is not None:
                header_text.append(
                    f" · eligible #{position} of {queue_size}",
                    style="dim #AF87FF",
                )
            elif in_use is not None and in_use > threshold:
                header_text.append(
                    " · not currently eligible",
                    style="dim #AF87FF",
                )
        header_text.append("\n")

    # Retry info (for agents that have retried or are using fallback)
    if agent.retry_count > 0 or agent.using_fallback or agent.attempt_history:
        header_text.append("Retries: ", style="bold #87D7FF")
        header_text.append(
            f"{agent.retry_count}/{agent.max_retries}\n", style="#FF8700"
        )
        for record in agent.attempt_history:
            try:
                hhmmss = record.start_hhmmss
            except (ValueError, OSError):
                hhmmss = "??:??:??"
            snippet = record.error_snippet or record.status
            fb_marker = " (fallback)" if record.used_fallback else ""
            header_text.append(
                f"  Attempt {record.attempt_number} · {hhmmss}{fb_marker} · "
                f"{record.status}: {snippet}\n",
                style="dim #FF8700",
            )
        if agent.fallback_model:
            header_text.append("Fallback: ", style="bold #87D7FF")
            if agent.using_fallback:
                header_text.append(f"{agent.fallback_model}\n", style="bold #FF8700")
            else:
                header_text.append(f"{agent.fallback_model}\n", style="dim #FF8700")

    # Timestamp(s)
    if agent.activity:
        header_text.append("Activity: ", style="bold #87D7FF")
        header_text.append(f"{agent.activity}\n", style="bold #D7AF5F")

    header_text.append("Timestamps: ", style="bold #87D7FF")
    if hint_state is None:
        header_text.append(f"{agent.timestamps_display}\n", style="#D7D7FF")
    else:
        hint_state.hint_counter = append_text_with_file_hints(
            header_text,
            f"{agent.timestamps_display}\n",
            hint_state.hint_counter,
            hint_state.hint_mappings,
            hint_state.workspace_dir,
            style="#D7D7FF",
        )

    if family_fold_enabled:
        header_text.append("Fold: ", style="bold #87D7FF")
        header_text.append(
            f"{fold_number(resolved_family_fold_level)}/3\n",
            style=f"dim {FAMILY_IDENTITY_COLOR}",
        )
        append_family_member_roster(
            header_text,
            agent,
            panel_level=resolved_family_fold_level,
            section_fold_overrides=family_overrides,
            member_jump_map_publisher=member_jump_map_publisher,
        )

    _append_legacy_parallel_members_section(header_text, agent)

    append_agent_output_variables_section(
        header_text,
        agent,
        fold_level=(
            effective_family_fold_level(
                "output-variables",
                resolved_family_fold_level,
                family_overrides,
            )
            if family_fold_enabled
            else None
        ),
    )

    # Meta fields from step output
    if meta_fields:
        append_major_section_divider(header_text)
        meta_level = effective_family_fold_level(
            "workflow-variables",
            resolved_family_fold_level,
            family_overrides,
        )
        if family_fold_enabled:
            append_family_fold_heading(
                header_text,
                WORKFLOW_VARIABLES_SECTION_LABEL,
                section_id="workflow-variables",
                level=meta_level,
                count=len(meta_fields),
            )
        else:
            append_section_heading(
                header_text,
                WORKFLOW_VARIABLES_SECTION_LABEL,
            )
        if not family_fold_enabled or meta_level != FoldLevel.COLLAPSED:
            for name, value in meta_fields:
                header_text.append(f"{name}: ", style="bold #87D7FF")
                header_text.append(f"{value}\n", style="#5FD75F")

    bead_section: ResponsiveBeadSection | None = None
    plan_section: ResponsivePlanSection | None = None
    responsive_ranges: dict[str, tuple[int, int]] = {}
    if not cheap and summary is not None:
        from ._agent_context import append_agent_context_section

        if summary.phase_bead is not None:
            bead_section = ResponsiveBeadSection(summary.phase_bead)
        if summary.associated_plan is not None:
            plan_section = ResponsivePlanSection(summary.associated_plan)
        append_agent_context_section(
            header_text,
            memory_reads=summary.memory_reads,
            skill_uses=summary.skill_uses,
            opened_workspaces=summary.opened_workspaces,
            bead_section=bead_section,
            plan_section=plan_section,
            agent=agent,
            delta_entries=summary.delta_entries,
            linked_delta_groups=summary.linked_delta_groups,
            artifact_file_paths=summary.artifact_file_paths,
            hint_state=hint_state,
            responsive_ranges=responsive_ranges,
            fold_level=(resolved_family_fold_level if family_fold_enabled else None),
            section_fold_overrides=family_overrides,
        )

    if not cheap and summary is not None:
        from ._agent_slow_tools import append_slow_tool_calls_section

        append_slow_tool_calls_section(
            header_text,
            sources=summary.slow_tool_sources,
            agent=agent,
            now=DateTime.now(),
            hint_state=hint_state,
            threshold_ms=slow_tool_call_threshold_ms,
            fold_level=(
                effective_family_fold_level(
                    "slow-tool-calls",
                    resolved_family_fold_level,
                    family_overrides,
                )
                if family_fold_enabled
                else None
            ),
        )

    # Failed agents always expose an ERROR section and raw-output breadcrumb.
    is_failed = agent.display_status == "FAILED"
    if agent.error_message or is_failed:
        header_text.append("\n")
        error_level = effective_family_fold_level(
            "error",
            resolved_family_fold_level,
            family_overrides,
        )
        if family_fold_enabled:
            append_family_fold_heading(
                header_text,
                "ERROR",
                style="bold #FF5F5F underline",
                section_id="error",
                level=error_level,
                count=1,
            )
        else:
            append_section_heading(
                header_text,
                "ERROR",
                style="bold #FF5F5F underline",
                section_id="error",
            )
        error_message = agent.error_message or "Runner failed without error details."
        if not family_fold_enabled or error_level != FoldLevel.COLLAPSED:
            header_text.append(f"{error_message}\n", style="bold #FF5F5F")
    if agent.output_path and is_failed:
        header_text.append("Output: ", style="bold #87D7FF")
        header_text.append(f"{agent.output_path}\n", style="dim")

    # Compute traceback renderable for ERROR section (included in all paths)
    error_tb_syntax: Syntax | None = None
    if agent.error_traceback:
        error_tb_syntax = Syntax(
            agent.error_traceback,
            "pytb",
            theme="monokai",
            word_wrap=True,
        )

    # Separator
    header_text.append("\n")
    header_text.append("\u2500" * 50 + "\n", style="dim")
    header_text.append("\n")

    responsive_sections: list[
        tuple[int, int, ResponsiveBeadSection | ResponsivePlanSection]
    ] = []
    if bead_section is not None and "BEAD" in responsive_ranges:
        start, end = responsive_ranges["BEAD"]
        responsive_sections.append((start, end, bead_section))
    if plan_section is not None and "PLAN" in responsive_ranges:
        start, end = responsive_ranges["PLAN"]
        responsive_sections.append((start, end, plan_section))
    if responsive_sections:
        responsive_sections.sort(key=lambda section: section[0])
        return (
            _AgentHeaderRenderable(
                header_text,
                tuple(responsive_sections),
            ),
            error_tb_syntax,
        )
    return header_text, error_tb_syntax
