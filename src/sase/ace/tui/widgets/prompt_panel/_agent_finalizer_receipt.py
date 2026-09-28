"""⊛ FINAL Reply receipt appended to each turn's phase render (plan §3.5).

Built only from the member turn's summary and returned as plain ``Text``
so the hint flatteners accept it. One-line call sites live in the session,
legacy, lone-turn, hint-twin, and monitor phase builders; all logic stays
here so ``toobig`` stays green.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from rich.text import Text

from sase.core.time import parse_local
from sase.finalizers.view_vocabulary import (
    FINAL_DECK_ACCENT,
    FINAL_GLYPH,
    instance_style,
)

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import Agent

#: Divider label for the receipt block.
RECEIPT_LABEL = "FINAL"


def _started_at(agent: Agent) -> datetime | None:
    summary = agent.finalizer_status
    started = summary.started_at if summary is not None else None
    parsed = parse_local(started)
    if parsed is None:
        return agent.run_start_time or agent.start_time
    return parsed.replace(tzinfo=None)


def _duration_text(started_at: float | None, finished_at: float | None) -> str | None:
    if started_at is None:
        return None
    from sase.ace.tui.models.agent import format_compact_duration

    end = finished_at if finished_at is not None else None
    if end is None:
        import time

        end = time.time()
    if end < started_at:
        return None
    return format_compact_duration(end - started_at)


def _instance_detail(
    *,
    status: str,
    op: str | None,
    step: str | None,
    attempt: int | None,
    max_attempts: int | None,
    headline: str | None,
    reason: str | None,
) -> str:
    label = step or op
    tries = ""
    if (
        attempt is not None
        and max_attempts is not None
        and max_attempts > 1
        and status in ("running", "failed", "refused", "deferred")
    ):
        tries = f"attempt {attempt}/{max_attempts}"
    if status == "running":
        return " · ".join(part for part in (label, tries) if part) or "running"
    if status in ("failed", "refused", "deferred"):
        return (
            " · ".join(part for part in (reason or headline, tries) if part) or status
        )
    if status == "success":
        return headline or "success"
    if status == "waiting":
        return label or "waiting"
    if status == "planned":
        return "planned"
    if status == "not_triggered":
        return "not triggered"
    if status == "skipped":
        return "skipped"
    if status == "not_run":
        return f"not run · blocked by {reason}" if reason else "not run"
    return status or "planned"


def finalizer_receipt_text(phase: Agent) -> Text | None:
    """Return the ⊛ FINAL receipt for one turn's phase, or None.

    No receipt for handoff-skipped turns, zero selected instances, legacy
    runs with no summary, or the ``planned`` phase (plan D8/D9).
    """
    summary = phase.finalizer_status
    if summary is None:
        return None
    if summary.phase in ("planned", "skipped"):
        return None
    instances = list(summary.instances)
    if not instances:
        return None
    from sase.ace.tui.widgets.prompt_panel._agent_display_content import (
        render_phase_divider,
    )

    receipt = Text()
    receipt.append_text(
        render_phase_divider(
            RECEIPT_LABEL,
            _started_at(phase),
            glyph=FINAL_GLYPH,
            accent=FINAL_DECK_ACCENT,
        )
    )
    trouble = False
    for instance in instances:
        status = instance.status or "planned"
        style = instance_style(status)
        detail = _instance_detail(
            status=status,
            op=instance.op,
            step=instance.step,
            attempt=instance.attempt,
            max_attempts=instance.max_attempts,
            headline=instance.headline,
            reason=instance.reason,
        )
        duration = _duration_text(instance.started_at, instance.finished_at)
        line = f"  {style.glyph} {instance.id}    {detail}"
        if duration:
            line += f"    {duration}"
        receipt.append(line + "\n", style=f"bold {style.color}")
        warnings = instance.warnings or 0
        if warnings > 0:
            receipt.append(f" ⚠{warnings}", style="dim #FFAF5F")
            receipt.append("\n")
        if status in ("failed", "refused") and instance.reason:
            receipt.append(
                f"             {style.word.upper()} {instance.reason}\n",
                style="dim",
            )
        if status not in ("success",):
            trouble = True
    if trouble:
        receipt.append("             p n  open FINAL deck\n", style="dim")
    if not receipt.plain.endswith("\n"):
        receipt.append("\n")
    return receipt


def append_finalizer_receipt(parts: list[object], phase: Agent) -> None:
    """Append the receipt to a non-hint phase renderable list (one-line site)."""
    receipt = finalizer_receipt_text(phase)
    if receipt is not None:
        parts.append(receipt)


__all__ = [
    "RECEIPT_LABEL",
    "append_finalizer_receipt",
    "finalizer_receipt_text",
]
