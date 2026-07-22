"""Pure title rendering for the Models-panel runner limit."""

from __future__ import annotations

from rich.text import Text

from sase.config import EffectiveRunnerLimitSnapshot

from .models_panel_duration import format_remaining


def append_runner_limit_title(
    text: Text,
    snapshot: EffectiveRunnerLimitSnapshot,
    *,
    now: float,
) -> None:
    """Append the authoritative global-cap status line."""
    text.append("max running agents: ", style="dim #878787")
    override = snapshot.active_override(now)
    if override is None:
        text.append(str(snapshot.configured_limit), style="bold cyan")
        return

    text.append(str(override.limit), style="bold cyan")
    text.append("  ", style="dim")
    if override.expires_at is None:
        text.append("override · until cleared", style="bold #AF87FF")
    else:
        text.append(
            f"override · {format_remaining(override.expires_at - now)} left",
            style="bold #AF87FF",
        )
    text.append("  configured ", style="dim #878787")
    text.append(str(snapshot.configured_limit), style="bold cyan")


__all__ = ["append_runner_limit_title"]
