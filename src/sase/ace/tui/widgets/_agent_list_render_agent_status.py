"""Status parenthetical for one agent-list row.

Appends ``(STATUS …)`` plus the monitor-outcome and running-retry
badges that sit immediately after it in :func:`format_agent_option`.
"""

from datetime import datetime

from rich.text import Text

from sase.agent.status_buckets import (
    FEEDBACK_STATUS,
    PENDING_EPIC_STATUS,
    PENDING_TALE_STATUS,
    PLAN_APPROVED_STATUS,
    QUEUED_STATUS,
    QUEUED_STATUS_COLOR,
    TALE_APPROVED_STATUS,
    WORKING_PLAN_STATUS,
    WORKING_TALE_STATUS,
)

from ..agent_completion import WaitDependencyStatusCounts
from ..models.agent import (
    Agent,
    format_compact_duration,
    format_wait_until,
    wait_display_agent,
    wait_remaining_seconds,
)
from ..models.agent_status import (
    RUNNING_COLOR,
    STOPPED_COLOR,
    STOPPED_GLYPH,
    STOPPED_STATUS,
)
from ..wait_status_presentation import format_wait_dependency_status_counts
from ._agent_list_helpers import short_model_name
from ._agent_list_styling import (
    _GATE_FAILURE_GLYPH_STYLE,
    _GATE_FOLLOWUP_ERROR_GLYPH,
    _GATE_FOLLOWUP_ERROR_GLYPH_STYLE,
    _MONITOR_FOLLOWUP_DEGRADED_OUTCOME,
    _MONITOR_FOLLOWUP_ERROR_GLYPH,
    _MONITOR_FOLLOWUP_ERROR_GLYPH_STYLE,
    _MONITOR_STALLED_GLYPH,
    _MONITOR_STALLED_GLYPH_STYLE,
    _UNRESOLVABLE_WAIT_TARGET_GLYPH,
    _UNRESOLVABLE_WAIT_TARGET_GLYPH_STYLE,
    gate_status_presentation,
    monitor_status_presentation,
)


def append_agent_row_status(
    text: Text,
    agent: Agent,
    *,
    now: datetime | None = None,
    wait_deps_satisfied: bool | None = None,
    wait_dependency_counts: WaitDependencyStatusCounts | None = None,
    has_unresolvable_wait_target: bool = False,
) -> None:
    """Append the status parenthetical and adjacent outcome badges."""
    # Status (wrapped in parentheses, parens are dim)
    display_status = agent.display_status
    row_prefix = text.plain
    status_opener = "(" if not row_prefix or row_prefix[-1].isspace() else " ("
    text.append(status_opener, style="dim")
    presentation = gate_status_presentation(agent) or monitor_status_presentation(agent)
    if presentation is not None:
        style, glyph = presentation
        text.append(display_status, style=style)
        if glyph:
            text.append(f" {glyph}", style=style)
    elif agent.is_proc_shell and agent.status == "SETTLING":
        text.append(display_status, style="bold #FFAF5F")
    elif agent.status == "STARTING":
        text.append(display_status, style="bold #87D7FF")  # Sky blue
    elif agent.status == "RUNNING":
        text.append(display_status, style=f"bold {RUNNING_COLOR}")
    elif agent.status in ("DONE", "PLAN DONE", "TALE DONE"):
        text.append(display_status, style="bold #5FD75F")  # Green
    elif agent.status == "PLAN REJECTED":
        text.append(display_status, style="bold #D7AF5F")  # Muted gold
    elif agent.status == STOPPED_STATUS:
        text.append(
            f"{STOPPED_GLYPH} {display_status}",
            style=f"bold {STOPPED_COLOR}",
        )
    elif agent.status == "EPIC CREATED":
        text.append(display_status, style="bold #5FD7AF")  # Sea-green
    elif agent.status == "FAILED":
        text.append(display_status, style="bold #FF5F5F")  # Red
    elif agent.status == "FAILED (RETRIED)":
        # Spawn-on-retry: dim red + warm yellow ↻ glyph indicates a
        # terminal failure that handed off to a downstream retry, as
        # opposed to a dead-end failure with no recovery attempt.
        text.append("FAILED ", style="dim #FF5F5F")
        text.append("↻", style="bold #FFAF00")
        text.append(" (RETRIED)", style="dim #FF5F5F")
    elif agent.status == "PLAN":
        text.append(display_status, style="bold #FF87AF")  # Pink
    elif agent.status == PENDING_TALE_STATUS:
        text.append(display_status, style="bold #FF87AF")  # Pink
    elif agent.status == PENDING_EPIC_STATUS:
        text.append(display_status, style="bold #D787FF")  # Orchid
    elif agent.status == FEEDBACK_STATUS:
        text.append(display_status, style="bold #FF5FD7")  # Magenta
    elif agent.status == PLAN_APPROVED_STATUS:
        text.append(display_status, style="bold #00D7AF")  # Green-blue (teal)
    elif agent.status == TALE_APPROVED_STATUS:
        text.append(display_status, style="bold #00D7D7")  # Turquoise
    elif agent.status == WORKING_PLAN_STATUS:
        text.append(display_status, style="bold #00AF87")  # Deep teal
    elif agent.status == WORKING_TALE_STATUS:
        text.append(display_status, style="bold #00AFAF")  # Deep turquoise
    elif agent.status == "PLAN COMMITTED":
        text.append(display_status, style="bold #5FD75F")  # Green
    elif agent.status == "EPIC APPROVED":
        text.append(display_status, style="bold #5FD7AF")  # Sea-green
    elif agent.status == QUEUED_STATUS:
        text.append(display_status, style=f"bold {QUEUED_STATUS_COLOR}")
        position = agent.runner_slot_queue_position
        queue_size = agent.runner_slot_queue_size
        if position is not None:
            queue_label = f" #{position}"
            if queue_size is not None:
                queue_label += f"/{queue_size}"
            text.append(queue_label, style=QUEUED_STATUS_COLOR)
        wait_agent = wait_display_agent(agent)
        slot_label = ""
        if (
            wait_agent.wait_runners_explicit
            and wait_agent.wait_runners is not None
            and wait_agent.runner_slots_in_use is not None
        ):
            slot_label = f" ▶{wait_agent.runner_slots_in_use}→{wait_agent.wait_runners}"
        if wait_agent.wait_priority_explicit and wait_agent.wait_priority is not None:
            slot_label = f"{slot_label} p{wait_agent.wait_priority}"
        if slot_label:
            text.append(slot_label, style=f"dim {QUEUED_STATUS_COLOR}")
    elif agent.status == "WAITING":
        text.append(display_status, style="bold #AF87FF")  # Amethyst
        wait_agent = wait_display_agent(agent)
        count_text = format_wait_dependency_status_counts(wait_dependency_counts)
        if count_text.cell_len:
            text.append(" ")
            text.append_text(count_text)
        if has_unresolvable_wait_target and wait_agent.waiting_for:
            text.append(" ")
            text.append(
                _UNRESOLVABLE_WAIT_TARGET_GLYPH,
                style=_UNRESOLVABLE_WAIT_TARGET_GLYPH_STYLE,
            )
        deps_satisfied = (
            not wait_agent.waiting_for and not wait_agent.waiting_for_beads
            if wait_deps_satisfied is None
            else wait_deps_satisfied and not wait_agent.waiting_for_beads
        )
        wait_remaining = wait_remaining_seconds(agent, now=now)
        if wait_remaining is not None and wait_remaining > 0 and deps_satisfied:
            text.append(
                f" {format_compact_duration(wait_remaining)}",
                style="#AF87FF",
            )
        elif (
            (wait_agent.waiting_for or wait_agent.waiting_for_beads)
            and wait_agent.wait_duration is not None
            and not wait_agent.wait_until
        ):
            text.append(
                f" +{format_compact_duration(wait_agent.wait_duration)}",
                style="#AF87FF",
            )
        elif wait_agent.wait_until:
            target_label = format_wait_until(wait_agent.wait_until, now=now)
            if wait_remaining is not None and wait_remaining > 0:
                text.append(
                    f" (until {target_label}, "
                    f"{format_compact_duration(wait_remaining)})",
                    style="#AF87FF",
                )
            else:
                text.append(f" (until {target_label})", style="#AF87FF")
    elif agent.status == "QUESTION":
        text.append(display_status, style="bold #FFAF00")  # Amber/orange
    elif agent.status == "ANSWERED":
        # Transient post-answer state: distinct bright azure, set apart from
        # QUESTION amber, RUNNING gold, and approved-plan teal.
        text.append(display_status, style="bold #5FD7FF")  # Bright cyan/azure
    elif agent.status == "RETRYING":
        countdown = ""
        if agent.retry_next_at_epoch:
            import time

            remaining = max(0, int(agent.retry_next_at_epoch - time.time()))
            countdown = f" ({remaining}s)"
        text.append(f"RETRYING{countdown}", style="bold #FF8700")  # Orange
    else:
        text.append(display_status, style="dim")
    if agent.is_monitor and agent.monitor_state in {"failed", "timeout", "lost"}:
        if agent.monitor_state == "timeout":
            text.append(" ⧖", style="bold #FFAF5F")
        elif agent.monitor_state == "failed" and agent.monitor_exit_code is not None:
            text.append(f" ✗ {agent.monitor_exit_code}", style="bold #FF5F5F")
    if (
        agent.is_monitor
        and agent.monitor_state in {"completed", "failed", "timeout", "stopped", "lost"}
        and agent.monitor_exit_code is None
    ):
        # A terminal monitor whose supervisor never reported a real exit
        # code (dead on arrival, or a pre-reboot supervisor whose command
        # outcome is unknown): distinct from the "✗ <code>"/"⧖" badges
        # above, which mean the command itself ran and reported.
        text.append(f" {_MONITOR_STALLED_GLYPH}", style=_MONITOR_STALLED_GLYPH_STYLE)
    if agent.is_gate and agent.gate_state == "failed":
        text.append(" ✗", style=_GATE_FAILURE_GLYPH_STYLE)
    text.append(")", style="dim")
    if agent.is_monitor and (
        agent.monitor_followup_error
        or agent.monitor_followup_outcome == _MONITOR_FOLLOWUP_DEGRADED_OUTCOME
    ):
        text.append(
            f" {_MONITOR_FOLLOWUP_ERROR_GLYPH}",
            style=_MONITOR_FOLLOWUP_ERROR_GLYPH_STYLE,
        )
    if agent.is_gate and (
        agent.gate_followup_error
        or agent.gate_followup_outcome == _MONITOR_FOLLOWUP_DEGRADED_OUTCOME
    ):
        text.append(
            f" {_GATE_FOLLOWUP_ERROR_GLYPH}",
            style=_GATE_FOLLOWUP_ERROR_GLYPH_STYLE,
        )
    # Retry/fallback annotations for RUNNING agents that have retried
    if agent.status == "RUNNING" and agent.retry_count > 0:
        annotation = f" ↻{agent.retry_count}"
        if agent.using_fallback and agent.fallback_model:
            short_name = short_model_name(agent.fallback_model)
            annotation += f"▸{short_name}"
        text.append(annotation, style="bold #FF8700")  # Orange
