"""Shared per-provider Textual markup for ACE update toasts."""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from typing import TYPE_CHECKING

from textual.markup import escape

if TYPE_CHECKING:
    from sase.ace.update_receipt import ProviderUpdateReceiptResult


def provider_result_lines(
    results: Sequence[ProviderUpdateReceiptResult],
    *,
    overflow: int = 0,
) -> str:
    """Render the ``Agent CLIs`` block for *results*, or ``""`` when empty."""
    if not results and overflow <= 0:
        return ""
    lines = ["[bold]Agent CLIs[/]"]
    for result in results:
        name = escape(result.display_name)
        if result.status == "updated":
            old = escape(result.old_version or "unknown")
            new = escape(result.new_version or "unknown")
            line = f"• {name}: [dim]{old} →[/] [green]{new}[/]"
            if result.reason:
                line += f" — [yellow]{escape(result.reason)}[/]"
            lines.append(line)
            continue
        if result.status == "already_current":
            lines.append(f"• {name}: [dim]already current[/]")
            continue
        reason = escape(result.reason or "skipped")
        if result.status == "failed":
            lines.append(f"• {name}: [red]failed[/] — {reason}")
            continue
        if result.suggested_command:
            command = escape(shlex.join(result.suggested_command))
            lines.append(f"• {name}: [yellow]manual[/] — {reason}")
            lines.append(f"  [dim]{command}[/]")
        else:
            lines.append(f"• {name}: [yellow]skipped[/] — {reason}")
    if overflow:
        lines.append(f"…and {overflow} more provider results")
    return "\n".join(lines)


__all__ = ["provider_result_lines"]
