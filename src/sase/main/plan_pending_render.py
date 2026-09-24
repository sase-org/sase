"""Shared renderer for name-first plan selector output.

Errors print to stderr; success prints to stdout. Color follows the shared
contract (:func:`sase.core.term_color.should_colorize`), so ``NO_COLOR``
and ``FORCE_COLOR`` behave.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from sase.core.term_color import should_colorize
from sase.main.plan_inventory_paths import display_path
from sase.main.plan_pending import (
    PendingPlan,
    PendingPlanAmbiguity,
    PendingPlanMiss,
)

if TYPE_CHECKING:
    from rich.console import Console
    from rich.text import Text as RichText

_TIER_STYLES = {"tale": "green", "epic": "magenta"}


def stderr_console() -> Console:
    """Return a stderr rich console honoring the shared color contract."""
    from rich.console import Console

    color = should_colorize(sys.stderr)
    return Console(
        stderr=True, highlight=False, force_terminal=color, no_color=not color
    )


def stdout_console() -> Console:
    """Return a stdout rich console honoring the shared color contract."""
    from rich.console import Console

    color = should_colorize(sys.stdout)
    return Console(highlight=False, force_terminal=color, no_color=not color)


def render_miss(
    miss: PendingPlanMiss,
    plans: tuple[PendingPlan, ...],
    console: Console | None = None,
) -> None:
    """Render a selector miss (or omitted-PLAN miss) to stderr."""
    from rich.text import Text

    out = console or stderr_console()
    header = miss.header if miss.selector is None else f"✗ {miss.header}"
    out.print(Text(header, style="red"))
    for line in miss.detail_lines:
        out.print(Text(f"  {line}"))
    out.print(Text(""))
    _render_awaiting_list(plans, out)


def render_ambiguity(
    ambiguity: PendingPlanAmbiguity,
    plans: tuple[PendingPlan, ...],
    console: Console | None = None,
) -> None:
    """Render an ambiguous selector to stderr with per-row matched-by notes."""
    from rich.text import Text

    out = console or stderr_console()
    out.print(
        Text(f"✗ `{ambiguity.selector}` matches multiple pending plans", style="red")
    )
    for plan in ambiguity.candidates:
        out.print(_candidate_line(plan, show_matched_by=True))
    _ = plans
    out.print(Text(""))
    out.print(Text("Pass one plan name from the list above.", style="dim"))


def render_awaiting_list(
    plans: tuple[PendingPlan, ...],
    console: Console | None = None,
) -> None:
    """Render the trailing Awaiting-approval list (public for handlers)."""
    out = console or stderr_console()
    _render_awaiting_list(plans, out)


def render_approve_success(
    plan: PendingPlan,
    message: str,
    notification_id: str,
    response_path: Path | str,
    console: Console | None = None,
) -> None:
    """Render an approval success leading with the plan name."""
    from rich.text import Text

    out = console or stdout_console()
    head = Text("✓ ", style="green")
    head.append(message, style="green")
    head.append(f" · {plan.display_name}", style="bold cyan")
    out.print(head)
    if plan.title:
        out.print(Text(f"  {plan.title}"))
    out.print(Text(f"  {notification_id[:8]} → {response_path}", style="dim"))


def render_reject_success(
    plan: PendingPlan,
    message: str,
    notification_id: str,
    response_path: Path | str,
    console: Console | None = None,
) -> None:
    """Render a rejection success leading with the plan name."""
    render_approve_success(plan, message, notification_id, response_path, console)


def _render_awaiting_list(plans: tuple[PendingPlan, ...], out: Console) -> None:
    from rich.text import Text

    if not plans:
        out.print(Text("Nothing is awaiting approval.", style="dim"))
        return
    out.print(Text(f"Awaiting approval ({len(plans)})", style="dim"))
    width = max(len(plan.display_name) for plan in plans)
    for plan in plans:
        out.print(_candidate_line(plan, name_width=width))


def _candidate_line(
    plan: PendingPlan, *, name_width: int = 0, show_matched_by: bool = False
) -> RichText:
    from rich.text import Text

    width = name_width or len(plan.display_name)
    line = Text("  ")
    line.append(plan.display_name.ljust(width), style="bold cyan")
    line.append("  ")
    line.append(plan.tier.ljust(4), style=_TIER_STYLES.get(plan.tier, ""))
    line.append("  ")
    line.append(plan.title or "-", style="")
    line.append("  ")
    agent = f"@{plan.agent}" if plan.agent != "-" else "-"
    line.append(agent, style="dim")
    line.append("  ")
    line.append(plan.age, style="dim")
    if show_matched_by and plan.matched_by:
        line.append(f"  (matched by {plan.matched_by})", style="dim")
    return line


def short_plan_path(path: str | None) -> str:
    """Shorten *path* for display, falling back to ``-``."""
    return display_path(path) if path else "-"


__all__ = [
    "render_ambiguity",
    "render_approve_success",
    "render_awaiting_list",
    "render_miss",
    "render_reject_success",
    "short_plan_path",
    "stderr_console",
    "stdout_console",
]
