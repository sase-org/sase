"""Identity, capacity, auto-approve, and project fields for the agent header."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping

from rich.text import Text

from sase.plan_tier_presentation import PLAN_TIER_PRESENTATIONS
from sase.project_display_names import humanize_cl_name

from ...models.agent import Agent, wait_display_agent
from ...models.agent_runner_slots import (
    format_capacity_value,
    format_queue_weight_badge_value,
)
from ...models.agent_owner_badge import agent_owner_badge_label
from .._agent_list_styling import (
    _AGENT_NAME_ANNOTATION_STYLE,
    _AGENT_SESSION_NAME_STYLE,
    _OWNER_BADGE_STYLE,
    _NAMED_PROC_ID_STYLE,
)
from .._queue_weight_badge import (
    format_queue_capacity_badge_value,
    queue_capacity_badge_number_style,
    queue_capacity_budget_display_enabled,
)
from ._agent_display_state import DetailHeaderSummary
from ._agent_page_section import (
    AGENT_PAGE_SECTION_ID,
    ResponsiveAgentPageSection,
)
from ._helpers import project_display_label


UNASSIGNED_AGENT_NAME_DISPLAY = "unassigned"
_AUTO_APPROVE_KIND_STYLES: dict[str, tuple[str, str]] = {
    "plan": ("\u26a1 PLAN", "bold #5FD7FF"),
    **{
        tier: (f"\u26a1 {tier.upper()}", presentation.rich_style)
        for tier, presentation in PLAN_TIER_PRESENTATIONS.items()
    },
}


def append_auto_approve_field(text: Text, agent: Agent) -> None:
    """Append the ``Auto:`` auto-approve kind field for autonomous agents."""
    if not agent.approve:
        return
    kind = agent.auto_approve_plan_action or "plan"
    token, style = _AUTO_APPROVE_KIND_STYLES.get(
        kind, (f"\u26a1 {kind.upper()}", "bold #BCBCBC")
    )
    text.append("Auto: ", style="bold #87D7FF")
    text.append(f"{token}\n", style=style)


def append_identity_fields(
    text: Text,
    agent: Agent,
    summary: DetailHeaderSummary | None,
    cached_bead_display: Callable[[Agent], object],
    responsive_ranges: MutableMapping[str, tuple[int, int]] | None,
) -> ResponsiveAgentPageSection | None:
    """Append agent identity and retry-chain fields."""
    text.append("Name: ", style="bold #87D7FF")
    presented_name = agent.presented_agent_name or agent.agent_name
    if presented_name:
        name_style = (
            _AGENT_SESSION_NAME_STYLE
            if agent.is_agent_session_container_row
            else _NAMED_PROC_ID_STYLE
            if agent.is_named_proc
            else _AGENT_NAME_ANNOTATION_STYLE
        )
        text.append(f"{presented_name}\n", style=name_style)
        owner_badge = agent_owner_badge_label(agent)
        if owner_badge:
            text.append("Owner: ", style="bold #87D7FF")
            text.append(f"{owner_badge}\n", style=_OWNER_BADGE_STYLE)
        _append_capacity_fields(text, agent)
        # Structured bead identity belongs exclusively to the deferred BEAD lane.
        is_known_phase = bool(
            agent.phase_bead_id or agent.agent_session_role == "phase"
        )
        if summary is not None and summary.bead_summary is not None:
            bead_display = None
        elif is_known_phase:
            bead_display = None
        elif summary is not None:
            bead_display = summary.bead_display
        else:
            cached_display = cached_bead_display(agent)
            bead_display = cached_display if isinstance(cached_display, str) else None
        if bead_display:
            text.append("Bead: ", style="bold #87D7FF")
            text.append(f"{bead_display}\n", style="bold #FFAF00")
    else:
        text.append(f"{UNASSIGNED_AGENT_NAME_DISPLAY}\n", style="dim")

    page_section = None
    if summary is not None and summary.agent_page_url:
        page_section = ResponsiveAgentPageSection(summary.agent_page_url)
        start = len(text)
        text.append_text(page_section.logical_text)
        if responsive_ranges is not None:
            responsive_ranges[AGENT_PAGE_SECTION_ID] = (start, len(text))

    if agent.is_retry_attempt or agent.is_retried_parent:
        text.append("Retry chain: ", style="bold #87D7FF")
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
    return page_section


def _suppress_capacity_fields(agent: Agent) -> bool:
    return bool(
        agent.is_clan_container
        or agent.is_named_proc
        or agent.is_gate
        or agent.is_monitor
        or (agent.is_child_row and not agent.agent_session_parallel)
    )


def _append_capacity_fields(text: Text, agent: Agent) -> None:
    """Append authored runner-capacity metadata for real agent rows."""
    if _suppress_capacity_fields(agent):
        return
    wait_agent = wait_display_agent(agent)
    if (
        format_queue_weight_badge_value(
            wait_agent.queue_weight,
            explicit=wait_agent.queue_weight_explicit,
        )
        is not None
    ):
        text.append("Weight: ", style="bold #87D7FF")
        text.append(
            f"{format_capacity_value(wait_agent.queue_weight)} capacity units\n",
            style="#87D7D7",
        )
    if not queue_capacity_budget_display_enabled():
        return
    capacity_explicit = (
        wait_agent.queue_capacity_explicit or wait_agent.wait_runners_explicit
    )
    capacity = (
        wait_agent.queue_capacity
        if wait_agent.queue_capacity is not None
        else wait_agent.wait_runners
    )
    multiplier = wait_agent.queue_capacity_multiplier
    value = format_queue_capacity_badge_value(
        capacity,
        explicit=capacity_explicit,
        multiplier=multiplier,
    )
    if value is None:
        return
    text.append("Capacity: ", style="bold #87D7FF")
    value_style = queue_capacity_badge_number_style(
        capacity,
        explicit=capacity_explicit,
        effective_limit=wait_agent.runner_effective_limit,
        multiplier=multiplier,
    )
    if multiplier is not None and capacity is None:
        from sase.macro.queue_directive import resolve_queue_capacity_multiplier

        resolved = resolve_queue_capacity_multiplier(
            multiplier, wait_agent.runner_effective_limit
        )
        text.append(f"{value} budget", style=value_style)
        if resolved is not None:
            text.append(
                f" ({format_capacity_value(resolved)} capacity units)",
                style=value_style,
            )
    elif value == "0":
        text.append("legacy 0", style=value_style)
        text.append(" (exact-weight drain budget)", style="dim #87AFD7")
    else:
        text.append(value, style=value_style)
        text.append(" capacity units", style=value_style)
    text.append("\n")


def append_project_fields(
    text: Text,
    agent: Agent,
    *,
    meta_project: object,
    meta_patch: object,
) -> None:
    """Append project, workspace, and workflow identity fields."""
    if agent.is_named_proc:
        if agent.cl_name and agent.cl_name != "proc":
            text.append("Project: ", style="bold #87D7FF")
            label = agent.project_display_name or humanize_cl_name(agent.cl_name)
            text.append(f"{label}\n", style="#00D7AF")
        if agent.workspace_num is not None and agent.workspace_num > 0:
            text.append("Workspace: ", style="bold #87D7FF")
            text.append(f"#{agent.workspace_num}\n", style="#5FD7FF")
        if agent.monitor_cwd:
            text.append("Cwd: ", style="bold #87D7FF")
            text.append(f"{agent.monitor_cwd}\n", style="#D7D7FF")
        return

    if (
        agent.is_workflow_step_child
        and agent.step_type in {"bash", "python"}
        and agent.step_name
    ):
        text.append("Step: ", style="bold #87D7FF")
        text.append(f"{agent.step_name}\n", style="#00D7AF")
    elif meta_patch:
        text.append("Patch: ", style="bold #87D7FF")
        text.append(f"{meta_patch}", style="#00D7AF")
        if agent.cl_num:
            text.append(" (")
            text.append(agent.cl_num, style="bold underline #569CD6")
            text.append(")")
        text.append("\n")
    elif meta_project:
        text.append("Project: ", style="bold #87D7FF")
        text.append(f"{project_display_label(agent, meta_project)}\n", style="#00D7AF")
    elif agent.is_project_agent:
        text.append("Project: ", style="bold #87D7FF")
        text.append(f"{project_display_label(agent, agent.cl_name)}\n", style="#00D7AF")
    else:
        text.append("Patch: ", style="bold #87D7FF")
        text.append(humanize_cl_name(agent.cl_name), style="#00D7AF")
        if agent.cl_num:
            text.append(" (")
            text.append(agent.cl_num, style="bold underline #569CD6")
            text.append(")")
        text.append("\n")

    workspace_num = agent.effective_workspace_num
    if workspace_num is not None and workspace_num > 0:
        text.append("Workspace: ", style="bold #87D7FF")
        text.append(f"#{workspace_num}\n", style="#5FD7FF")

    if agent.workflow and not agent.appears_as_agent:
        text.append("Workflow: ", style="bold #87D7FF")
        text.append(f"{agent.workflow}\n")
