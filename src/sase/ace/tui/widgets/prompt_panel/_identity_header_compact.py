"""Two-row compact identity lines for prompt-panel documents."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text

from sase.agent.status_buckets import QUEUED_STATUS, QUEUED_STATUS_COLOR
from sase.llm_provider.model_label import model_value_text
from sase.plan_tier_presentation import PLAN_TIER_PRESENTATIONS
from sase.project_display_names import humanize_cl_name

from ...models.agent import Agent, wait_display_agent
from ...agent_count_chip import format_agent_count_chip
from ...models.agent_tribe_summary import AgentTribeSummarySnapshot
from ...models.fold_scale import TRIBE_FOLD_SCALE, FoldScale, fold_scale_position
from ...models.fold_state import FoldLevel
from ...models.tribe_display import tribe_identity_style
from .._agent_list_styling import (
    _AGENT_NAME_ANNOTATION_STYLE,
    _FAMILY_NAME_STYLE,
    _PROC_SHELL_ID_STYLE,
)
from ._agent_display_header_metadata import _UNASSIGNED_AGENT_NAME_DISPLAY
from ._agent_display_state import DetailHeaderSummary
from ._agent_display_tribe_common import STATUS_STYLES as _TRIBE_STATUS_STYLES
from ._agent_shell_section import ResponsiveShellSection
from ._agent_wait_section import ResponsiveWaitSection
from ._fold_language import FOLD_CHARS, FOLD_STYLES
from ._workflow_render import WORKFLOW_STATUS_STYLES

_CHIP_SEPARATOR_STYLE = "dim"
_XPROMPT_KIND_STYLES: dict[str, tuple[str, str]] = {
    "workflow": ("⌘", "bold #FFAF5F"),
    "swarm": ("❋", "bold #FF87D7"),
}
_XPROMPT_DEFAULT_GLYPH = "▣"
_XPROMPT_DEFAULT_STYLE = "bold #87FFAF"
_XPROMPT_CHIP_LIMIT = 3
_WAIT_CHIP_GLYPH = "⏳"
_WAIT_CHIP_GLYPH_STYLE = "#AF87FF"
_MACHINE_CHIP_GLYPH = "⇄"
_MACHINE_CHIP_STYLE = "bold #5FD7FF"
_RETRY_CHIP_STYLE = "#FF8700"
_FEED_ERROR_CHIP_STYLE = "#FFAF5F"
_ACTIVITY_CHIP_STYLE = "bold #D7AF5F"
_AUTO_APPROVE_DEFAULT_STYLE = "bold #BCBCBC"
_NAME_FALLBACK_STYLE = "dim"
_FALLBACK_LINE_STYLE = "dim"
_MAX_CWD_CELLS = 48


def _chips_row(chips: list[Text]) -> Text:
    """Join styled chips into one truncating compact row."""
    row = Text(no_wrap=True, overflow="ellipsis")
    for index, chip in enumerate(chips):
        if index:
            row.append(" · ", style=_CHIP_SEPARATOR_STYLE)
        row.append_text(chip)
    return row


def _compact_text(first: Text, second: Text) -> Text:
    """Combine two rows into one two-line compact renderable."""
    compact = Text(no_wrap=True, overflow="ellipsis")
    compact.append_text(first)
    compact.append("\n")
    compact.append_text(second)
    return compact


def _name_chip(agent: Agent) -> Text:
    """Return the row-1 name chip in the node's kind name style."""
    chip = Text()
    presented_name = agent.presented_agent_name or agent.agent_name
    if not presented_name:
        chip.append(_UNASSIGNED_AGENT_NAME_DISPLAY, style=_NAME_FALLBACK_STYLE)
        return chip
    if agent.is_family_container_row:
        style = _FAMILY_NAME_STYLE
    elif agent.is_proc_shell:
        style = _PROC_SHELL_ID_STYLE
    else:
        style = _AGENT_NAME_ANNOTATION_STYLE
    chip.append(presented_name, style=style)
    return chip


def _auto_approve_chip(agent: Agent) -> Text | None:
    """Return the row-1 auto-approve chip when autonomous."""
    if not agent.approve:
        return None
    kind = agent.auto_approve_plan_action or "plan"
    if kind == "plan":
        token, style = ("⚡ PLAN", "bold #5FD7FF")
    elif kind == "tale":
        token, style = ("⚡ TALE", PLAN_TIER_PRESENTATIONS["tale"].rich_style)
    elif kind == "epic":
        token, style = ("⚡ EPIC", PLAN_TIER_PRESENTATIONS["epic"].rich_style)
    else:
        token = f"⚡ {kind.upper()}"
        style = _AUTO_APPROVE_DEFAULT_STYLE
    chip = Text()
    chip.append(token, style=style)
    return chip


def _machine_chip(agent: Agent) -> Text | None:
    """Return the row-1 remote machine chip for fleet rows."""
    if not agent.fleet_origin_alias:
        return None
    chip = Text()
    chip.append(
        f"{_MACHINE_CHIP_GLYPH} {agent.fleet_origin_alias}", style=_MACHINE_CHIP_STYLE
    )
    return chip


def _shell_count_chip(shell_section: ResponsiveShellSection | None) -> Text:
    """Return the family ``N shells`` row-1 summary chip."""
    total = 0
    if shell_section is not None:
        total = len(shell_section.lanes) + shell_section.hidden_count
    chip = Text()
    chip.append(f"{total} shells", style=_CHIP_SEPARATOR_STYLE)
    return chip


def _xprompt_chips(summary: DetailHeaderSummary | None) -> list[Text]:
    """Return at most three xprompt chips plus a dim overflow count."""
    xprompts = (summary.xprompts_used if summary is not None else None) or []
    chips: list[Text] = []
    for item in xprompts[:_XPROMPT_CHIP_LIMIT]:
        glyph, style = _XPROMPT_KIND_STYLES.get(
            str(item.get("kind") or ""),
            (_XPROMPT_DEFAULT_GLYPH, _XPROMPT_DEFAULT_STYLE),
        )
        chip = Text()
        chip.append(f"{glyph} #{item.get('name') or 'unknown'}", style=style)
        chips.append(chip)
    if len(xprompts) > _XPROMPT_CHIP_LIMIT:
        overflow = Text()
        overflow.append(f"+{len(xprompts) - _XPROMPT_CHIP_LIMIT}", style="dim")
        chips.append(overflow)
    return chips


def _queue_chip(agent: Agent) -> Text | None:
    """Return the runner-slot queue chip for queued agents."""
    if agent.status != QUEUED_STATUS:
        return None
    wait_agent = wait_display_agent(agent)
    position = wait_agent.runner_slot_queue_position
    size = wait_agent.runner_slot_queue_size
    chip = Text()
    if position is not None:
        label = f"Queue #{position}"
        if size is not None:
            label += f"/{size}"
    else:
        label = "Queue pending"
    chip.append(label, style=f"bold {QUEUED_STATUS_COLOR}")
    return chip


def _wait_chip(wait_section: ResponsiveWaitSection | None) -> Text | None:
    """Return the first-wait-lane chip with an overflow count."""
    if wait_section is None or not wait_section.lanes:
        return None
    chip = Text()
    chip.append(f"{_WAIT_CHIP_GLYPH} ", style=_WAIT_CHIP_GLYPH_STYLE)
    chip.append_text(wait_section.lanes[0][1])
    if len(wait_section.lanes) > 1:
        chip.append(f" +{len(wait_section.lanes) - 1}", style="dim")
    return chip


def _retry_chip(agent: Agent) -> Text | None:
    """Return the retry-history chip when retries exist or fallback is live."""
    if not (agent.retry_count > 0 or agent.using_fallback or agent.attempt_history):
        return None
    chip = Text()
    chip.append(f"↻ {agent.retry_count}/{agent.max_retries}", style=_RETRY_CHIP_STYLE)
    if agent.using_fallback:
        chip.append(" fallback", style=_RETRY_CHIP_STYLE)
    return chip


def _feed_error_chip(agent: Agent) -> Text | None:
    """Return the remote feed-error chip for fleet rows with diagnostics."""
    if not agent.fleet_diagnostic:
        return None
    chip = Text()
    chip.append(agent.fleet_diagnostic, style=_FEED_ERROR_CHIP_STYLE)
    return chip


def _activity_chip(agent: Agent) -> Text | None:
    """Return the activity chip when the node reports one."""
    if not agent.activity:
        return None
    chip = Text()
    chip.append(agent.activity, style=_ACTIVITY_CHIP_STYLE)
    return chip


def _fold_chip(level: FoldLevel, scale: FoldScale) -> Text:
    """Return the fold position chip for fold-aware documents."""
    position, size = fold_scale_position(level, scale)
    chip = Text()
    chip.append(f"{FOLD_CHARS[level]} {position}/{size}", style=FOLD_STYLES[level])
    return chip


def _fallback_context_line(agent: Agent) -> Text:
    """Return the quiet dim context line used when row 2 would be empty."""
    parts: list[str] = []
    project = agent.project_display_name or humanize_cl_name(agent.cl_name)
    if project:
        parts.append(project)
    workspace_num = agent.effective_workspace_num
    if workspace_num is not None and workspace_num > 0:
        parts.append(f"#{workspace_num}")
    first_stamp = _first_timestamp_summary(agent)
    if first_stamp is not None:
        parts.append(first_stamp)
    line = Text()
    line.append(" · ".join(parts), style=_FALLBACK_LINE_STYLE)
    return line


def _first_timestamp_summary(agent: Agent) -> str | None:
    """Summarize the first timestamp line as ``TAG HH:MM:SS``."""
    display = agent.timestamps_display
    if not display:
        return None
    first_line = display.splitlines()[0] if display.splitlines() else ""
    segments = [segment.strip() for segment in first_line.split("|")]
    if not segments or not segments[0]:
        return None
    tag = segments[0]
    if len(segments) < 2 or not segments[1]:
        return tag
    moment = segments[1].split()[-1]
    return f"{tag} {moment}"


def _shorten_cwd(cwd: str) -> str:
    """Collapse home and middle-truncate an overlong working directory."""
    home = str(Path.home())
    if cwd == home:
        return "~"
    if cwd.startswith(home + "/"):
        cwd = "~" + cwd[len(home) :]
    if len(cwd) <= _MAX_CWD_CELLS:
        return cwd
    keep = (_MAX_CWD_CELLS - 1) // 2
    return f"{cwd[:keep]}…{cwd[-keep:]}"


def build_agent_compact_lines(
    *,
    agent: Agent,
    summary: DetailHeaderSummary | None = None,
    wait_section: ResponsiveWaitSection | None = None,
    shell_section: ResponsiveShellSection | None = None,
    fold_level: FoldLevel | None = None,
    fold_scale: FoldScale | None = None,
) -> Text:
    """Build the two-row compact identity for one agent document."""
    if agent.is_proc_shell:
        return _build_proc_shell_compact_lines(agent)
    first: list[Text] = [_name_chip(agent)]
    if agent.is_family_container_row:
        first.append(_shell_count_chip(shell_section))
    else:
        model_value = model_value_text(
            agent.model,
            agent.llm_provider,
            agent.reasoning_effort,
            agent.model_alias,
        )
        if model_value is not None:
            first.append(model_value)
    auto_chip = _auto_approve_chip(agent)
    if auto_chip is not None:
        first.append(auto_chip)
    machine_chip = _machine_chip(agent)
    if machine_chip is not None:
        first.append(machine_chip)

    second: list[Text] = []
    second.extend(_xprompt_chips(summary))
    queue_chip = _queue_chip(agent)
    if queue_chip is not None:
        second.append(queue_chip)
    wait_chip = _wait_chip(wait_section)
    if wait_chip is not None:
        second.append(wait_chip)
    retry_chip = _retry_chip(agent)
    if retry_chip is not None:
        second.append(retry_chip)
    feed_error_chip = _feed_error_chip(agent)
    if feed_error_chip is not None:
        second.append(feed_error_chip)
    activity_chip = _activity_chip(agent)
    if activity_chip is not None:
        second.append(activity_chip)
    if (
        agent.is_family_container_row
        and fold_level is not None
        and fold_scale is not None
    ):
        second.append(_fold_chip(fold_level, fold_scale))

    second_row = _chips_row(second) if second else _fallback_context_line(agent)
    return _compact_text(_chips_row(first), second_row)


def _build_proc_shell_compact_lines(agent: Agent) -> Text:
    """Build the two-row compact identity for one proc-shell document."""
    first: list[Text] = [_name_chip(agent)]
    if agent.cl_name and agent.cl_name != "proc":
        project = Text()
        project.append(
            agent.project_display_name or humanize_cl_name(agent.cl_name),
            style="#00D7AF",
        )
        first.append(project)

    second: list[Text] = []
    if agent.monitor_cwd:
        cwd = Text()
        cwd.append(_shorten_cwd(agent.monitor_cwd), style="#D7D7FF")
        second.append(cwd)
    activity_chip = _activity_chip(agent)
    if activity_chip is not None:
        second.append(activity_chip)

    second_row = _chips_row(second) if second else _fallback_context_line(agent)
    return _compact_text(_chips_row(first), second_row)


def build_tribe_compact_lines(
    *,
    snapshot: AgentTribeSummarySnapshot,
    fold_level: FoldLevel,
) -> Text:
    """Build the two-row compact identity for one tribe document."""
    first = Text()
    first.append(
        snapshot.label,
        style=tribe_identity_style(snapshot.panel_key, bold=True),
    )
    first.append(" ", style="")
    first.append(
        snapshot.status,
        style=_TRIBE_STATUS_STYLES.get(snapshot.status_bucket, "bold"),
    )
    count_chip = format_agent_count_chip(
        stopped=snapshot.counts.stopped,
        running=snapshot.counts.running,
        queued=snapshot.counts.queued,
        waiting=snapshot.counts.waiting,
        failed=snapshot.counts.failed,
        unread=snapshot.counts.unread,
        done=snapshot.counts.done,
    )
    if count_chip.cell_len:
        first.append(" ", style="")
        first.append_text(count_chip)

    composition: list[str] = []
    if snapshot.clan_count:
        composition.append(
            f"{snapshot.clan_count} clan{'s' if snapshot.clan_count != 1 else ''}"
        )
    if snapshot.family_count:
        composition.append(
            f"{snapshot.family_count} "
            f"famil{'ies' if snapshot.family_count != 1 else 'y'}"
        )
    composition.append(
        f"{snapshot.lane_count} lane{'s' if snapshot.lane_count != 1 else ''}"
    )
    if snapshot.nested_count:
        composition.append(f"{snapshot.nested_count} nested")
    second = Text()
    second.append(" · ".join(composition), style="")
    second.append(" · ", style=_CHIP_SEPARATOR_STYLE)
    second.append(snapshot.runtime_span, style="bold #BCBCBC")
    second.append(" · ", style=_CHIP_SEPARATOR_STYLE)
    second.append_text(_fold_chip(fold_level, TRIBE_FOLD_SCALE))
    return _compact_text(
        _chips_row([first]),
        _chips_row([second]),
    )


def build_workflow_compact_lines(*, agent: Agent) -> Text:
    """Build the two-row compact identity for one workflow document."""
    first: list[Text] = []
    name = Text()
    name.append(agent.workflow or "unknown", style="#AF87D7 bold")
    first.append(name)
    model_value = model_value_text(
        agent.model,
        agent.llm_provider,
        agent.reasoning_effort,
        agent.model_alias,
    )
    if model_value is not None:
        first.append(model_value)

    second: list[Text] = []
    status = Text()
    status.append(
        agent.status,
        style=WORKFLOW_STATUS_STYLES.get(agent.status, "#D7D7FF"),
    )
    second.append(status)
    activity_chip = _activity_chip(agent)
    if activity_chip is not None:
        second.append(activity_chip)

    second_row = _chips_row(second) if second else _fallback_context_line(agent)
    return _compact_text(_chips_row(first), second_row)


__all__ = [
    "build_agent_compact_lines",
    "build_tribe_compact_lines",
    "build_workflow_compact_lines",
]
