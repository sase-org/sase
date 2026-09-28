"""Status parenthetical for one agent-list row.

Appends ``(STATUS …)`` plus the monitor-outcome and running-retry
badges that sit immediately after it in :func:`format_agent_option`.
"""

from datetime import datetime

from rich.text import Text

from sase.agent.status_buckets import (
    QUEUED_STATUS,
    QUEUED_STATUS_COLOR,
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
from ..models.agent_runner_slots import format_capacity_value
from ..models.agent_status import (
    RUNNING_COLOR,
    STOPPED_COLOR,
    STOPPED_GLYPH,
    STOPPED_STATUS,
)
from ..wait_status_presentation import format_wait_dependency_summary
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
from ._queue_weight_badge import (
    append_agent_queue_badges,
    queue_capacity_budget_display_enabled,
)
from ..models._agent_clan import status_display_agent
from ..models.finalizer_row_state import (
    glance_finalizer_state,
    row_status_is_finalizing,
)
from sase.ace.tui.tool_runs.attribution import (
    row_identity_from_agent,
    select_live_runs,
)
from sase.ace.tui.tool_runs.flag import tool_runs_enabled
from sase.ace.tui.tool_runs.row_chip import row_chip_for_runs
from sase.ace.tui.tool_runs.snapshot import get_snapshot, tool_runs_disabled_reason
from sase.core.time import local_now


def _append_finalizer_chip(text: Text, agent: Agent) -> None:
    """Append the ⊛ chip after the status parenthesis (plan §3.5)."""
    state = glance_finalizer_state(agent)
    if state.chip_text:
        text.append(f" {state.chip_text}", style=state.chip_style or "dim")


def _append_tool_run_chip(
    text: Text, agent: Agent, *, now: datetime | None = None
) -> None:
    """Append the live-only ⚒ row chip after the ⊛ chip (plan §3.6).

    Pure side-cache lookup: reads the app-level glance snapshot plus
    ``now``. Never stats, opens SQLite, or reads a log. No-op while the
    ``ace_tool_runs`` beta flag is off.
    """

    if not tool_runs_enabled():
        return
    if tool_runs_disabled_reason() is not None:
        return
    snapshot = get_snapshot()
    if snapshot is None or not snapshot.runs:
        return
    row = row_identity_from_agent(agent)
    selected = select_live_runs(snapshot.runs, row)
    if not selected:
        return
    reference = now if now is not None else local_now()
    try:
        now_ts = reference.timestamp()
    except Exception:
        import time as _time

        now_ts = _time.time()
    chip = row_chip_for_runs(selected, now_ts, snapshot.silent_after_s)
    if chip is None:
        return
    chip_text, chip_style = chip
    text.append(f" {chip_text}", style=chip_style)


def append_queued_status_extras(text: Text, agent: Agent) -> None:
    """Append admission rank, legacy slot occupancy, priority, and hold extras."""
    wait_agent = wait_display_agent(agent)
    position = wait_agent.runner_slot_queue_position
    queue_size = wait_agent.runner_slot_queue_size
    if position is not None:
        queue_label = f" #{position}"
        if queue_size is not None:
            queue_label += f"/{queue_size}"
        text.append(queue_label, style=QUEUED_STATUS_COLOR)
    slot_label = ""
    if (
        not queue_capacity_budget_display_enabled()
        and wait_agent.wait_runners_explicit
        and wait_agent.wait_runners is not None
    ):
        occupied = wait_agent.runner_occupied_capacity
        if occupied is None and wait_agent.runner_slots_in_use is not None:
            occupied = float(wait_agent.runner_slots_in_use)
        if occupied is not None:
            slot_label = (
                f" ▶{format_capacity_value(occupied, minimum_decimal=False)}"
                f"→{wait_agent.wait_runners}"
            )
    if wait_agent.wait_priority_explicit and wait_agent.wait_priority is not None:
        slot_label = f"{slot_label} p{wait_agent.wait_priority}"
    if slot_label:
        text.append(slot_label, style=f"dim {QUEUED_STATUS_COLOR}")
    if wait_agent.held_by:
        text.append(
            f" held by {wait_agent.held_by}",
            style=f"dim {QUEUED_STATUS_COLOR}",
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
    append_agent_queue_badges(text, agent)
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
    elif agent.is_named_proc and agent.status == "SETTLING":
        text.append(display_status, style="bold #FFAF5F")
    elif agent.status == "STARTING":
        text.append(display_status, style="bold #87D7FF")  # Sky blue
    elif agent.status == "RUNNING":
        if row_status_is_finalizing(agent):
            text.append("FINALIZING", style=f"bold {RUNNING_COLOR}")
        else:
            text.append(display_status, style=f"bold {RUNNING_COLOR}")
    elif agent.status == "DONE":
        text.append(display_status, style="bold #5FD75F")  # Green
    elif agent.status == STOPPED_STATUS:
        text.append(
            f"{STOPPED_GLYPH} {display_status}",
            style=f"bold {STOPPED_COLOR}",
        )
    elif agent.status == "FAILED":
        text.append(display_status, style="bold #FF5F5F")  # Red
    elif agent.status == "FAILED (RETRIED)":
        # Spawn-on-retry: dim red + warm yellow ↻ glyph indicates a
        # terminal failure that handed off to a downstream retry, as
        # opposed to a dead-end failure with no recovery attempt.
        text.append("FAILED ", style="dim #FF5F5F")
        text.append("↻", style="bold #FFAF00")
        text.append(" (RETRIED)", style="dim #FF5F5F")
    elif agent.status == WORKING_PLAN_STATUS:
        text.append(display_status, style="bold #00AF87")  # Deep teal
    elif agent.status == WORKING_TALE_STATUS:
        text.append(display_status, style="bold #00AFAF")  # Deep turquoise
    elif agent.status == QUEUED_STATUS:
        text.append(display_status, style=f"bold {QUEUED_STATUS_COLOR}")
        append_queued_status_extras(text, agent)
    elif agent.status == "WAITING":
        text.append(display_status, style="bold #AF87FF")  # Amethyst
        wait_agent = wait_display_agent(agent)
        single_bead_id = (
            wait_agent.waiting_for_beads[0]
            if not wait_agent.waiting_for
            and not wait_agent.waiting_for_hoods
            and len(wait_agent.waiting_for_beads) == 1
            else None
        )
        count_text = format_wait_dependency_summary(
            wait_dependency_counts,
            single_bead_id=single_bead_id,
        )
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
            not wait_agent.waiting_for
            and not wait_agent.waiting_for_beads
            and not wait_agent.waiting_for_hoods
            if wait_deps_satisfied is None
            else wait_deps_satisfied
            and not wait_agent.waiting_for_beads
            and not wait_agent.waiting_for_hoods
        )
        wait_remaining = wait_remaining_seconds(agent, now=now)
        if wait_remaining is not None and wait_remaining > 0 and deps_satisfied:
            text.append(
                f" {format_compact_duration(wait_remaining)}",
                style="#AF87FF",
            )
        elif (
            (
                wait_agent.waiting_for
                or wait_agent.waiting_for_beads
                or wait_agent.waiting_for_hoods
            )
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
    elif agent.status == "RETRYING":
        countdown = ""
        retry_source = status_display_agent(agent).retry_next_at_epoch
        if retry_source:
            import time

            remaining = max(0, int(retry_source - time.time()))
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
    _append_finalizer_chip(text, agent)
    _append_tool_run_chip(text, agent, now=now)
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
