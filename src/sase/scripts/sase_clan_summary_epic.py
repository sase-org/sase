"""Render a launch-time-stable Rich summary for an epic agent clan."""

from __future__ import annotations

import os
import textwrap

from rich.markup import escape

from sase.bead.cli_common import get_read_view
from sase.bead.model import BeadTier, Issue, IssueType

_SUMMARY_WIDTH = 76
_UNKNOWN_EPIC_ID = "?"


def main() -> int:
    """Print the epic summary named by ``SASE_CLAN_NAME``.

    Summary lookup is intentionally best-effort: agent launch must still get a
    useful clan identity when the bead store is missing, stale, or unreadable.
    """
    epic_id = os.environ.get("SASE_CLAN_NAME", "").strip()
    try:
        epic, phases = _load_epic(epic_id)
    except Exception:
        print(_fallback_summary(epic_id))
        return 0

    print(_render_epic_summary(epic, phases))
    return 0


def _load_epic(epic_id: str) -> tuple[Issue, tuple[Issue, ...]]:
    if not epic_id:
        raise ValueError("SASE_CLAN_NAME is empty")

    with get_read_view() as project:
        epic = project.show(epic_id)
        if epic.issue_type is not IssueType.PLAN or epic.tier is not BeadTier.EPIC:
            raise ValueError(f"Bead {epic_id!r} is not an epic plan")
        phases = tuple(
            sorted(
                (
                    child
                    for child in project.get_epic_children(epic.id)
                    if child.issue_type is IssueType.PHASE
                ),
                key=lambda phase: (phase.created_at, phase.id),
            )
        )
    return epic, phases


def _render_epic_summary(epic: Issue, phases: tuple[Issue, ...]) -> str:
    header = _shorten(f"EPIC {epic.id} · {epic.title}", width=_SUMMARY_WIDTH)
    lines = [f"[bold #D75FFF]{escape(header)}[/bold #D75FFF]"]

    goal = _shorten(epic.description, width=_SUMMARY_WIDTH)
    if goal:
        lines.append(f"[dim #D7D7FF]{escape(goal)}[/dim #D7D7FF]")

    for index, phase in enumerate(phases, start=1):
        prefix = f"{index}. "
        title = _shorten(
            phase.title,
            width=max(_SUMMARY_WIDTH - len(prefix), 1),
        )
        lines.append(f"[bold #87D7FF]{index}.[/bold #87D7FF] {escape(title)}")

    return "\n".join(lines)


def _fallback_summary(epic_id: str) -> str:
    return f"[bold]EPIC {escape(epic_id or _UNKNOWN_EPIC_ID)}[/]"


def _shorten(value: str, *, width: int) -> str:
    one_line = " ".join(value.split())
    if not one_line:
        return ""
    return textwrap.shorten(one_line, width=width, placeholder="…")


if __name__ == "__main__":  # pragma: no cover - console-script convenience
    raise SystemExit(main())
