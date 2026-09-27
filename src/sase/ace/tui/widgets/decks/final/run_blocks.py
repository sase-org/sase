"""One card block per run for the ⊛ FINAL deck (epic sase-1b2, ``final-run-blocks``).

On session containers every FINAL card holds one :class:`CardBlock` per
run whose disposition is ``active``, ``ran`` or ``interrupted``. Block ids
are the run ids (``card_block_id(identity)``, the same ids Reply uses, so
rail numbers match Reply's rail by construction), and :class:`BlockMeta`
carries the roster number, label, monitor glyph and a status bucket from
the run aggregate. Skipped and not-triggered runs appear only in the
ledger. The rail, ``[``/``]`` and newest landing work through the
generalized block host; FINAL's block mode is always automatic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.text import Text

from ..card_block import BlockMeta

#: Run dispositions that earn a card block. Every other disposition
#: (``skipped``, ``not_reached``, ``unavailable``) appears only in the
#: runs ledger (plan §4.17).
FINAL_BLOCK_DISPOSITIONS = ("active", "ran", "interrupted")

#: Per-instance statuses that mean the instance never ran in that run, so
#: the run earns no block on that instance's card.
FINAL_NON_RUN_INSTANCE_STATUSES = frozenset(
    {"not_run", "not_triggered", "waiting", "planned", "skipped"}
)

#: Result statuses that paint a settled run's rail entry as failed.
FINAL_FAILED_RESULT_STATUSES = frozenset({"failed", "refused"})


def is_final_block_run(run: Any) -> bool:
    """Return whether ``run`` earns a card block on the Overview card."""
    disposition = str(getattr(run, "disposition", "") or "").strip().lower()
    return disposition in FINAL_BLOCK_DISPOSITIONS


def final_block_runs(runs: Any) -> list[Any]:
    """Return the runs that earn card blocks, in ledger order."""
    return [run for run in (runs or ()) if is_final_block_run(run)]


def run_instance_ran(item: Any) -> bool:
    """Return whether a per-run instance item counts as ran in its run."""
    status = str(getattr(item, "status", "") or "").strip().lower()
    return status not in FINAL_NON_RUN_INSTANCE_STATUSES


def run_status_bucket(run: Any) -> str:
    """Return the roster status bucket for one run's rail entry."""
    disposition = str(getattr(run, "disposition", "") or "").strip().lower()
    if disposition == "active":
        return "Running"
    if disposition == "interrupted":
        return "Stopped"
    result = str(getattr(run, "result_status", "") or "").strip().lower()
    if result in FINAL_FAILED_RESULT_STATUSES:
        return "Failed"
    return "Done"


def run_block_meta(run: Any) -> BlockMeta:
    """Return roster-matched :class:`BlockMeta` for one run.

    ``number`` is the run's roster index (the same index Reply numbers by,
    so gaps stay informative), ``label``/``kind``/glyph mirror the session
    turn facts, and the status bucket comes from the run aggregate.
    """
    from sase.monitor_state import MONITOR_GLYPH, MONITOR_GLYPH_COLOR

    from ...prompt_panel._agent_display_content import PHASE_DIVIDER_ACCENT

    kind = str(getattr(run, "kind", "") or "agent").strip().lower()
    is_monitor = kind == "monitor"
    return BlockMeta(
        number=str(getattr(run, "number", 0)),
        label=str(getattr(run, "label", "") or getattr(run, "run_id", "") or "run"),
        glyph=MONITOR_GLYPH if is_monitor else "",
        accent=MONITOR_GLYPH_COLOR if is_monitor else PHASE_DIVIDER_ACCENT,
        status_bucket=run_status_bucket(run),
        kind="monitor" if is_monitor else "agent",
    )


def run_start_time(run: Any) -> datetime | None:
    """Return the run's start as a naive local datetime, if declarable."""
    for entry in getattr(run, "declarations", ()) or ():
        moment = getattr(entry, "t", None)
        if isinstance(moment, bool):
            continue
        if isinstance(moment, (int, float)):
            try:
                return datetime.fromtimestamp(moment)
            except (OverflowError, OSError, ValueError):
                return None
    return None


def run_duration_seconds(run: Any) -> float:
    """Return the total attempt seconds across one run's instances."""
    total = 0.0
    for item in getattr(run, "instances", ()) or ():
        for attempt in getattr(item, "attempts", ()) or ():
            seconds = getattr(attempt, "duration_seconds", None)
            if seconds is None or isinstance(seconds, bool):
                continue
            try:
                total += float(seconds)
            except (TypeError, ValueError):
                continue
    return total


def format_run_duration(seconds: float) -> str | None:
    """Format one run's duration the way the Overview mockup does."""
    if seconds <= 0:
        return None
    if seconds >= 60:
        return f"{int(seconds // 60)}m{int(seconds % 60):02d}s"
    return f"{seconds:.1f}s"


def run_block_header(run: Any) -> Text:
    """Return the block header divider for one run.

    The header is ``render_phase_divider(label, start, glyph, block_id)``
    with the run duration appended, so the block anchor meta still marks
    the row for the generalized block host.
    """
    from rich.style import Style

    from ...prompt_panel._agent_display_content import render_phase_divider
    from ...prompt_panel._section_navigation import DECK_BLOCK_META_KEY

    meta = run_block_meta(run)
    run_id = str(getattr(run, "run_id", "") or "")
    divider = render_phase_divider(
        meta.label,
        run_start_time(run),
        glyph=meta.glyph or None,
        block_id=run_id or None,
    )
    duration = format_run_duration(run_duration_seconds(run))
    if duration is None:
        return divider
    plain = divider.plain
    if plain.endswith("\n"):
        plain = plain[:-1]
    header = Text(plain)
    header.append(f" · {duration}", style="dim")
    header.append("\n")
    if run_id:
        header.stylize(
            Style(meta={DECK_BLOCK_META_KEY: run_id}),
            0,
            len(header.plain),
        )
    return header


__all__ = [
    "FINAL_BLOCK_DISPOSITIONS",
    "FINAL_FAILED_RESULT_STATUSES",
    "FINAL_NON_RUN_INSTANCE_STATUSES",
    "final_block_runs",
    "format_run_duration",
    "is_final_block_run",
    "run_block_header",
    "run_block_meta",
    "run_duration_seconds",
    "run_instance_ran",
    "run_start_time",
    "run_status_bucket",
]
