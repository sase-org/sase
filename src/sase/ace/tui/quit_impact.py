"""In-memory TUI exit impact for quit/restart confirmations.

Synchronous with no I/O: session workers and durable submit workers live in
this TUI process and die at ``os._exit`` / ``os.execv``. Durable procs, ``!``
background commands, monitor turns, and service procs are deliberately
excluded because they outlive the TUI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TuiExitImpact:
    """What a TUI exit would interrupt in this process."""

    session_labels: tuple[str, ...] = ()
    pending_durable_submits: int = 0
    pending_launches: int = 0

    @property
    def is_empty(self) -> bool:
        """Return whether nothing would be lost (pending launches never count)."""
        return not self.session_labels and self.pending_durable_submits <= 0

    @property
    def task_count(self) -> int:
        """Return the count that drives the quit-menu warning."""
        return len(self.session_labels) + max(0, self.pending_durable_submits)

    def warning_text(self) -> str:
        """Render the quit-menu warning line."""
        count = self.task_count
        noun = "TUI task" if count == 1 else "TUI tasks"
        return f"  {count} {noun} will be interrupted."

    def summary_lines(self, limit: int = 5) -> list[str]:
        """Render at most ``limit`` lines, then an ``…and N more`` overflow."""
        lines: list[str] = []
        for label in self.session_labels:
            lines.append(f"TUI task: {label}")
        if self.pending_durable_submits > 0:
            noun = "submission" if self.pending_durable_submits == 1 else "submissions"
            lines.append(
                f"{self.pending_durable_submits} durable {noun} "
                "still submitting \u2014 quitting discards the submit"
            )
        if self.pending_launches > 0:
            lines.append(
                f"{self.pending_launches} pending "
                f"{'launch' if self.pending_launches == 1 else 'launches'} "
                "will be stashed for @"
            )
        if limit <= 0:
            return []
        if len(lines) <= limit:
            return lines
        kept = lines[:limit]
        kept.append(f"\u2026and {len(lines) - limit} more")
        return kept


def _session_labels(app: Any) -> tuple[str, ...]:
    overlay = getattr(app, "_session_overlay_rows", None)
    if not callable(overlay):
        return ()
    try:
        rows = overlay()
    except Exception:
        return ()
    try:
        from sase.ace.tui._proc_observer_models import proc_status_is_active
    except Exception:
        return ()
    labels: list[str] = []
    for row in rows or ():
        try:
            if not proc_status_is_active(getattr(row, "status", "")):
                continue
            label = getattr(row, "label", None)
            if callable(label):
                label = label()
            text = str(label or getattr(row, "display_name", None) or row.proc_type)
            if text:
                labels.append(text)
        except Exception:
            continue
    return tuple(labels)


def _pending_durable_submit_count(app: Any) -> int:
    workers = getattr(app, "_durable_submit_workers", None)
    if not isinstance(workers, dict) or not workers:
        return 0
    count = 0
    for worker in workers.values():
        try:
            if bool(getattr(worker, "is_finished", False)):
                continue
            count += 1
        except Exception:
            count += 1
    return count


def _pending_launch_count(app: Any) -> int:
    registry = getattr(app, "_pending_launches", None)
    if not isinstance(registry, dict) or not registry:
        return 0
    count = 0
    for launch in registry.values():
        try:
            if bool(getattr(launch, "cancelled", False)):
                continue
            if bool(getattr(launch, "submitted", False)):
                continue
            count += 1
        except Exception:
            continue
    return count


def collect_tui_exit_impact(app: Any) -> TuiExitImpact:
    """Collect the in-memory exit impact for *app* without doing I/O."""
    try:
        labels = _session_labels(app)
    except Exception:
        labels = ()
    try:
        submits = _pending_durable_submit_count(app)
    except Exception:
        submits = 0
    try:
        launches = _pending_launch_count(app)
    except Exception:
        launches = 0
    return TuiExitImpact(
        session_labels=labels,
        pending_durable_submits=max(0, submits),
        pending_launches=max(0, launches),
    )


__all__ = ["TuiExitImpact", "collect_tui_exit_impact"]
