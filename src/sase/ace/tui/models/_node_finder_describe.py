"""Node Finder per-agent naming, kind, and row description.

Split from :mod:`sase.ace.tui.models.node_finder`: pure helpers that
describe one agent as a finder row. Free of Textual imports by design;
UI-adjacent helpers behind Textual import chains are imported lazily
inside the functions that need them.
"""

from __future__ import annotations

from typing import Any

from sase.project_display_names import humanize_cl_name

from ._agent_tree import agent_tree_title
from .agent import Agent, AgentType
from .agent_named_procs import named_proc_command_title


def node_finder_name(agent: Agent) -> str:
    """Return the name the Agents row shows for *agent*."""
    if agent.is_clan_container:
        return (
            agent.presented_agent_name
            or agent.agent_clan
            or agent.display_name
            or humanize_cl_name(agent.cl_name)
        )
    if agent.is_named_proc:
        return (
            agent.proc_label
            or agent.presented_agent_name
            or agent.agent_name
            or agent.display_name
            or humanize_cl_name(agent.cl_name)
        )
    return (
        agent.presented_agent_name
        or agent.agent_name
        or agent.display_name
        or humanize_cl_name(agent.cl_name)
    )


def node_finder_title(agent: Agent) -> str | None:
    """Return the displayed title when it differs from the name."""
    title = agent_tree_title(agent)
    if not title or title == node_finder_name(agent):
        return None
    return title


#: Cached :func:`identity_kind_for_agent` without importing the Textual
#: widget chain at module load (this model stays Textual-free by design).
_IDENTITY_KIND_FN: Any = None

#: Cached kind style constants, bound lazily for the same reason. The
#: batch descriptor below reuses these instead of duplicating values.
_KIND_STYLES: dict[str, Any] | None = None


def kind_styles() -> dict[str, Any]:
    """Return the shared kind label/accent constants, binding them once."""
    global _KIND_STYLES  # noqa: PLW0603
    styles = _KIND_STYLES
    if styles is None:
        from sase.ace.tui.widgets.prompt_panel._agent_display_agent_session import (
            SESSION_IDENTITY_COLOR,
        )
        from sase.ace.tui.widgets.prompt_panel._identity_header import (
            AGENT_FALLBACK_IDENTITY_COLOR,
            STEP_FALLBACK_IDENTITY_COLOR,
            WORKFLOW_IDENTITY_COLOR,
            _STEP_TYPE_COLORS,
        )
        from sase.ace.tui.widgets._agent_list_styling import (
            _AGENT_NAME_ANNOTATION_STYLE,
            _GATE_ROW_STYLE,
            _MONITOR_ROW_STYLE,
            _NAMED_PROC_ROW_STYLE,
        )

        styles = {
            "session": SESSION_IDENTITY_COLOR,
            "proc": _NAMED_PROC_ROW_STYLE,
            "agent_entry": _AGENT_NAME_ANNOTATION_STYLE,
            "gate": _GATE_ROW_STYLE,
            "monitor": _MONITOR_ROW_STYLE,
            "step_fallback": STEP_FALLBACK_IDENTITY_COLOR,
            "workflow": WORKFLOW_IDENTITY_COLOR,
            "agent": AGENT_FALLBACK_IDENTITY_COLOR,
            "step_colors": _STEP_TYPE_COLORS,
        }
        _KIND_STYLES = styles
    return styles


def node_finder_kind(agent: Agent) -> tuple[str, str]:
    """Return the kind label and accent color for *agent*."""
    if agent.is_clan_container:
        return ("CLAN", "#D75FFF")
    global _IDENTITY_KIND_FN  # noqa: PLW0603
    kind_fn = _IDENTITY_KIND_FN
    if kind_fn is None:
        from sase.ace.tui.widgets.prompt_panel._identity_header import (
            identity_kind_for_agent,
        )

        kind_fn = identity_kind_for_agent
        _IDENTITY_KIND_FN = kind_fn
    return kind_fn(agent)


def describe_node_finder_row_from_facts(
    *,
    is_clan: bool,
    is_proc: bool,
    is_wf_step: bool,
    step_type: str | None,
    presented: str | None,
    agent_name: str | None,
    display_name: str,
    cl_name: str,
    is_session_container: bool,
    is_monitor: bool,
    is_gate: bool,
    is_agent_entry: bool,
    agent_clan: str | None,
    proc_label: str | None,
    proc_safe_preview: str | None,
    step_name: str | None,
    is_session_member_child: bool,
    is_pre_prompt_step: bool,
    agent_type: AgentType,
    is_workflow_child: bool,
    appears_as_agent: bool,
    styles: dict[str, Any] | None = None,
) -> tuple[bool, str, str, str, str]:
    """Return ``(jumpable, name, title, kind_label, kind_accent)`` from facts.

    Batch entry point for the snapshot builder: the caller reads each agent
    role/naming property once per open into a facet table and reuses it for
    the fold filter, grouping, and every row, instead of re-parsing
    plan-chain suffixes per property per row. Behavior matches
    :func:`describe_node_finder_row` exactly for the same inputs.
    """
    if is_clan:
        name = presented or agent_clan or display_name or humanize_cl_name(cl_name)
    elif is_proc:
        name = (
            proc_label
            or presented
            or agent_name
            or display_name
            or humanize_cl_name(cl_name)
        )
    else:
        name = presented or agent_name or display_name or humanize_cl_name(cl_name)

    if is_wf_step and step_type in ("bash", "python"):
        step_title = step_name or display_name
        raw_title = step_title or None
    elif is_proc:
        raw_title = proc_label or named_proc_command_title(proc_safe_preview)
    elif (
        not is_clan
        and not is_session_container
        and (
            is_monitor
            or is_gate
            or (is_wf_step and step_type == "agent")
            or is_session_member_child
        )
    ):
        raw_title = None
    else:
        raw_title = display_name or None
    if not raw_title or raw_title == name:
        title: str | None = None
    else:
        title = raw_title

    jumpable = not is_pre_prompt_step and not (is_wf_step and step_type != "agent")

    resolved_styles = styles if styles is not None else kind_styles()
    if is_clan:
        kind_label, kind_accent = "CLAN", "#D75FFF"
    elif is_session_container:
        kind_label, kind_accent = "SESSION", resolved_styles["session"]
    elif is_proc:
        kind_label, kind_accent = "NAMED PROC", resolved_styles["proc"]
    elif is_agent_entry:
        kind_label, kind_accent = "AGENT TURN", resolved_styles["agent_entry"]
    elif is_gate:
        kind_label, kind_accent = "GATE TURN", resolved_styles["gate"]
    elif is_monitor:
        kind_label, kind_accent = "MONITOR TURN", resolved_styles["monitor"]
    elif is_wf_step and step_type:
        kind_label = "STEP"
        step_colors = resolved_styles["step_colors"]
        kind_accent = step_colors.get(step_type, resolved_styles["step_fallback"])
    elif (
        agent_type is AgentType.WORKFLOW
        and not is_workflow_child
        and not appears_as_agent
    ):
        kind_label, kind_accent = "WORKFLOW", resolved_styles["workflow"]
    else:
        kind_label, kind_accent = "AGENT", resolved_styles["agent"]

    return (jumpable, name, title or "", kind_label, kind_accent)


def _describe_node_finder_row_for_snapshot(
    agent: Agent,
    *,
    is_monitor: bool | None = None,
    is_gate: bool | None = None,
    styles: dict[str, Any] | None = None,
) -> tuple[bool, str, str, str, str]:
    """Return ``(jumpable, name, title, kind_label, kind_accent)`` for snapshots.

    Snapshot fast path: reuses the per-open ``is_monitor``/``is_gate`` facet
    table and one shared kind-style binding instead of re-parsing plan-chain
    suffixes and rebinding styles per row. All other facts are read lazily
    exactly as :func:`describe_node_finder_row` does, so behavior matches
    for every agent shape.
    """
    resolved_monitor = agent.is_monitor if is_monitor is None else is_monitor
    resolved_gate = agent.is_gate if is_gate is None else is_gate
    is_clan = agent.is_clan_container
    is_proc = agent.is_named_proc
    is_wf_step = agent.is_workflow_step_child
    step_type = agent.step_type
    presented = agent.presented_agent_name
    agent_name = agent.agent_name
    display_name = agent.display_name
    cl_name = agent.cl_name
    is_session_container = agent.is_agent_session_container_row
    is_agent_entry = agent.is_agent_entry
    if is_clan:
        name = (
            presented or agent.agent_clan or display_name or humanize_cl_name(cl_name)
        )
    elif is_proc:
        proc_label = agent.proc_label
        name = (
            proc_label
            or presented
            or agent_name
            or display_name
            or humanize_cl_name(cl_name)
        )
    else:
        name = presented or agent_name or display_name or humanize_cl_name(cl_name)

    if is_wf_step and step_type in ("bash", "python"):
        step_title = agent.step_name or display_name
        raw_title = step_title or None
    elif is_proc:
        raw_title = agent.proc_label or named_proc_command_title(
            agent.proc_safe_preview
        )
    elif (
        not is_clan
        and not is_session_container
        and (
            resolved_monitor
            or resolved_gate
            or (is_wf_step and step_type == "agent")
            or agent.is_agent_session_member_child
        )
    ):
        raw_title = None
    else:
        raw_title = display_name or None
    if not raw_title or raw_title == name:
        title: str | None = None
    else:
        title = raw_title

    jumpable = not agent.is_pre_prompt_step and not (
        is_wf_step and step_type != "agent"
    )

    resolved_styles = styles if styles is not None else kind_styles()
    if is_clan:
        kind_label, kind_accent = "CLAN", "#D75FFF"
    elif is_session_container:
        kind_label, kind_accent = "SESSION", resolved_styles["session"]
    elif is_proc:
        kind_label, kind_accent = "NAMED PROC", resolved_styles["proc"]
    elif is_agent_entry:
        kind_label, kind_accent = "AGENT TURN", resolved_styles["agent_entry"]
    elif resolved_gate:
        kind_label, kind_accent = "GATE TURN", resolved_styles["gate"]
    elif resolved_monitor:
        kind_label, kind_accent = "MONITOR TURN", resolved_styles["monitor"]
    elif is_wf_step and step_type:
        kind_label = "STEP"
        step_colors = resolved_styles["step_colors"]
        kind_accent = step_colors.get(step_type, resolved_styles["step_fallback"])
    elif (
        agent.agent_type is AgentType.WORKFLOW
        and not agent.is_workflow_child
        and not agent.appears_as_agent
    ):
        kind_label, kind_accent = "WORKFLOW", resolved_styles["workflow"]
    else:
        kind_label, kind_accent = "AGENT", resolved_styles["agent"]

    return (jumpable, name, title or "", kind_label, kind_accent)


def describe_node_finder_row(
    agent: Agent,
) -> tuple[bool, str, str, str, str]:
    """Return ``(jumpable, name, title, kind_label, kind_accent)`` for *agent*.

    Batch equivalent of :func:`node_finder_jumpable`, :func:`node_finder_name`,
    :func:`node_finder_title`, and :func:`node_finder_kind` that reads each
    agent property once. Snapshot building calls the ``_for_snapshot`` batch
    entry point per row instead of this single-row wrapper; the singles remain
    the behavior contract (see the differential test over every agent shape).
    """
    return _describe_node_finder_row_for_snapshot(agent)


def node_finder_jumpable(agent: Agent) -> bool:
    """Return whether *agent* can ever be a Node Finder jump target."""
    if agent.is_pre_prompt_step:
        return False
    if agent.is_workflow_step_child and agent.step_type != "agent":
        return False
    return True
