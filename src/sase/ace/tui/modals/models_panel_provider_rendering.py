"""Rendering helpers for Models-panel provider routing."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from rich.text import Text

from sase.ace.tui.provider_disable_display import provider_disable_provenance_label
from sase.core.time import get_timezone
from sase.llm_provider import ProviderRoutingStatus, TemporaryProviderDisable

from .models_panel_duration import (
    DurationPickerModal,
    OverrideUntilCleared,
    RelativeOverrideDuration,
    format_duration_chosen,
)
from .models_panel_provider_state import active_disable, remaining_label
from .models_panel_time import ResolvedOverrideUntil

_PROVIDER_CELL = 14
_COUNT_CELL = 10
_DISABLED_STYLE = "bold #FFAF5F"
_AVAILABLE_STYLE = "bold #87D787"
_CLI_MISSING_STYLE = "dim #A8A8A8"
_DESCRIPTION_STYLE = "#B0B0B0"


def _pad(value: str, width: int) -> str:
    if len(value) > width:
        return value[: max(0, width - 1)] + "…"
    return value.ljust(width)


def _provider_label(provider: str, colors: Mapping[str, str]) -> Text:
    label = Text(no_wrap=True, overflow="ellipsis")
    color = colors.get(provider, "#87D7FF")
    label.append(_pad(provider.upper(), _PROVIDER_CELL), style=f"bold {color}")
    return label


def render_provider_row(
    status: ProviderRoutingStatus,
    *,
    colors: Mapping[str, str],
    now: float,
) -> Text:
    """Render one provider-routing row."""
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append_text(_provider_label(status.provider, colors))
    text.append(" ")
    count = f"{status.model_count} model"
    if status.model_count != 1:
        count += "s"
    text.append(_pad(count, _COUNT_CELL), style="dim")
    text.append("   ")
    disable = active_disable(status.active_disable, now=now)
    if disable is not None:
        provenance = provider_disable_provenance_label(disable)
        text.append(
            f"disabled · {provenance} · {remaining_label(disable, now=now)}",
            style=_DISABLED_STYLE,
        )
    elif status.cli_available:
        text.append("available", style=_AVAILABLE_STYLE)
    else:
        text.append("CLI missing", style=_CLI_MISSING_STYLE)
    return text


def provider_title_line(
    disables: Mapping[str, TemporaryProviderDisable],
    *,
    now: float,
) -> Text | None:
    """Return the conditional Models-title provider-disable summary."""
    entries: list[str] = []
    for provider, disable in sorted(disables.items()):
        if active_disable(disable, now=now) is None:
            continue
        entries.append(
            f"{provider.upper()} {remaining_label(disable, now=now, include_left=False)}"
        )
    if not entries:
        return None
    text = Text("disabled providers: ", style="dim")
    text.append(" · ".join(entries), style=_DISABLED_STYLE)
    return text


def _affected_aliases_text(status: ProviderRoutingStatus) -> str:
    aliases = tuple(f"@{name}" for name in status.affected_aliases)
    if not aliases:
        return "No configured aliases currently mention it."
    joined = ", ".join(aliases[:5])
    if len(aliases) > 5:
        joined = f"{joined}, +{len(aliases) - 5}"
    return f"Affected aliases: {joined}."


def provider_description_text(
    status: ProviderRoutingStatus | None,
    *,
    now: float,
) -> Text:
    """Return the fixed-height provider description strip."""
    if status is None:
        return Text("", style=_DESCRIPTION_STYLE)
    text = Text(style=_DESCRIPTION_STYLE, no_wrap=False)
    label = status.provider.upper()
    disable = active_disable(status.active_disable, now=now)
    if disable is not None:
        provenance = provider_disable_provenance_label(disable)
        text.append(
            f"New launches and fallbacks route around {label}; "
            "running provider processes continue.",
            style=_DISABLED_STYLE,
        )
        if disable.expires_at is None:
            end = "until cleared"
        else:
            end = datetime.fromtimestamp(disable.expires_at, get_timezone()).strftime(
                "%b %-d %-I:%M%p"
            )
            end = f"until {end} ({remaining_label(disable, now=now)})"
        text.append(
            f"\n{provenance} disable {end}. {_affected_aliases_text(status)}",
            style="dim",
        )
    elif not status.cli_available:
        text.append(
            f"{label} CLI is unavailable; automatic selector routing already skips it.",
            style=_CLI_MISSING_STYLE,
        )
        text.append(
            "\nA manual disable can still record temporary routing state for later.",
            style="dim",
        )
    else:
        text.append(
            f"{label} is available for new launches.",
            style=_AVAILABLE_STYLE,
        )
        text.append(
            "\nDisable it to route future launches and fallbacks around it; "
            "running processes continue.",
            style="dim",
        )
    return text


def provider_duration_modal(provider: str) -> DurationPickerModal:
    """Build the duration picker used to disable ``provider``."""
    label = provider.upper()
    return DurationPickerModal(
        title=f"Disable {label}",
        quick_subtitle=f"Route new launches around {label} briefly.",
        short_subtitle=f"Keep {label} out of routing through a short task.",
        hour_subtitle=f"Route new launches around {label} for a focused session.",
        two_hour_subtitle=f"Keep {label} disabled for a longer implementation block.",
        four_hour_subtitle=f"Keep {label} disabled for half a day.",
        until_cleared_subtitle=f"Keep {label} disabled until you enable it.",
        until_time_subtitle="Choose a local clock time or date.",
        custom_placeholder="e.g., 30m, 2h, 1h30m, until cleared",
        id_prefix="provider-duration",
    )


def duration_suffix(
    result: (
        RelativeOverrideDuration | OverrideUntilCleared | ResolvedOverrideUntil | None
    ),
) -> str:
    """Return the toast suffix describing a chosen disable duration."""
    if isinstance(result, ResolvedOverrideUntil):
        return f"until {result.notification_display}"
    if isinstance(result, OverrideUntilCleared):
        return "until cleared"
    if isinstance(result, RelativeOverrideDuration):
        return f"for {format_duration_chosen(result.seconds)}"
    return "temporarily"
