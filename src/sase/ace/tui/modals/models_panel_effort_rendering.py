"""Pure render helpers for the Models-panel effective default effort."""

from __future__ import annotations

from rich.text import Text

from sase.llm_provider import EffectiveDefaultEffortSnapshot

from .models_panel_duration import format_remaining


def append_default_effort_title(
    text: Text,
    snapshot: EffectiveDefaultEffortSnapshot,
    *,
    now: float,
) -> None:
    """Append the authoritative second-line launch-default status."""
    text.append("default effort: ", style="dim #878787")
    override = snapshot.active_override(now)
    if override is None:
        _append_level(text, snapshot.configured_effort)
        return

    _append_level(text, override.effort)
    text.append("  ", style="dim")
    if override.expires_at is None:
        text.append("override · until cleared", style="bold #AF87FF")
    else:
        text.append(
            f"override · {format_remaining(override.expires_at - now)} left",
            style="bold #AF87FF",
        )
    text.append("  configured ", style="dim #878787")
    _append_level(text, snapshot.configured_effort)


def _append_level(text: Text, effort: str | None) -> None:
    if effort is None:
        text.append("provider default", style="dim #878787")
        return
    text.append("@ ", style="#878787")
    text.append(effort, style="bold #AF87FF")


__all__ = ["append_default_effort_title"]
