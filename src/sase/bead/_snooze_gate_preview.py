"""Human-facing text rendered by the BeadSnooze gate.

Every renderer here is reconstructed byte for byte by gate validation, so all
of it is a pure function of the persisted payload. The snooze block, the
notification note, and the preset close reason all render stored absolute
instants through :func:`sase.bead_time_presentation.bead_instant_label` rather
than a live clock, because a recomputed age would drift and fail that
comparison as the gate sat pending.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sase.bead.model import CloseRecord, SnoozeRecord, TaskPlusOneEvidence
from sase.bead.task_gate import (
    render_task_triage_preview,
    task_triage_presentation_note,
)
from sase.bead_time_presentation import bead_instant_label
from sase.task_type_gate_presentation import TaskTypeGateDisplay


def bead_snooze_close_reason(until: str) -> str:
    """Return the preset close reason a bare Close accepts."""
    return (
        f"Snoozed until {bead_instant_label(until)} with no new evidence; "
        "closing as stale."
    )


def render_bead_snooze_preview(
    *,
    bead_id: str,
    title: str,
    description: str,
    notes: str,
    snooze: SnoozeRecord,
    created_by: str = "",
    created_at: str = "",
    size: str | None = None,
    refs: Sequence[str] = (),
    plus_one_evidence: Sequence[TaskPlusOneEvidence] = (),
    close_history: Sequence[CloseRecord] = (),
    task_type: str = "",
    task_type_fields: Mapping[str, str] | None = None,
    task_type_display: TaskTypeGateDisplay | None = None,
) -> str:
    """Render the woken task's detail, snooze block first.

    Every rendered field is a persisted absolute instant, never a recomputed
    age: gate validation reconstructs this preview byte for byte, so a
    relative time would make the gate fail validation as it aged.
    """
    return _bead_snooze_block(snooze) + render_task_triage_preview(
        bead_id=bead_id,
        title=title,
        description=description,
        notes=notes,
        created_by=created_by,
        created_at=created_at,
        size=size,
        refs=refs,
        plus_one_evidence=plus_one_evidence,
        close_history=close_history,
        task_type=task_type,
        task_type_fields=task_type_fields,
        task_type_display=task_type_display,
    )


def _bead_snooze_block(snooze: SnoozeRecord) -> str:
    """Render the callout describing who deferred this task, and until when."""
    lines = [
        f"> [!NOTE] **◈ Snoozed by `@{snooze.snoozed_by}` on "
        f"{bead_instant_label(snooze.snoozed_at)}**",
        ">",
        f"> **Wakes:** {bead_instant_label(snooze.until)}",
    ]
    if snooze.plus_one_target is not None:
        remaining = snooze.plus_ones_remaining
        lines.append(
            f"> **+1 target:** {remaining} more "
            f"({snooze.plus_one_target} total) wakes it early"
        )
    reason = snooze.reason.strip()
    if reason:
        lines.append(f"> **Reason:** {reason}")
    return "\n".join(lines) + "\n\n"


def bead_snooze_presentation_note(
    bead_id: str,
    title: str,
    count: int,
    *,
    until: str,
    reopen_count: int = 0,
) -> str:
    """Return the stable notification summary for one snooze wake gate.

    The wake time rides along as an immutable instant rather than a countdown,
    because gate validation recomputes this note and compares it with the
    persisted one; a relative time would drift and fail that comparison.
    """
    base = task_triage_presentation_note(
        bead_id, title, count, reopen_count=reopen_count
    )
    return f"{base} · ◈ {bead_instant_label(until)}"
