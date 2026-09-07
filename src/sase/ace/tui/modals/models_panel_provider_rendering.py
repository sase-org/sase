"""Rendering helpers for Models-panel provider routing."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from rich.text import Text

from sase.ace.tui.provider_disable_display import provider_disable_provenance_label
from sase.core.time import get_timezone
from sase.llm_provider import (
    ProviderRoutingStatus,
    TemporaryProviderDisable,
    TemporaryProviderPriority,
)
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_MODE_HARD,
    PROVIDER_DISABLE_MODE_SOFT,
)

from .models_panel_duration import (
    DurationPickerModal,
    KeepCurrentWindow,
    OverrideUntilCleared,
    RelativeOverrideDuration,
    format_duration_chosen,
    format_remaining,
)
from .models_panel_provider_state import active_disable, remaining_label
from .models_panel_time import ResolvedOverrideUntil

_PROVIDER_CELL = 14
_COUNT_CELL = 10
_DISABLED_STYLE = "bold #FFAF5F"
_SOFT_DISABLED_STYLE = "bold #FFD75F"
_AVAILABLE_STYLE = "bold #87D787"
_CLI_MISSING_STYLE = "dim #A8A8A8"
_DESCRIPTION_STYLE = "#B0B0B0"
_PRIORITY_STYLE = "bold #87D7FF"
_PRIORITY_UNAVAILABLE_STYLE = "bold #FFAF5F"
_BACKUP_STYLE = "#87AFC7"


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
    priority = _status_priority(status, now=now)
    priority_suffix = _priority_row_suffix(
        status,
        priority,
        disable=disable,
        now=now,
    )
    if disable is not None:
        provenance = provider_disable_provenance_label(disable)
        remaining = remaining_label(disable, now=now)
        if disable.is_soft:
            text.append(
                f"soft · {provenance} · {remaining}",
                style=_SOFT_DISABLED_STYLE,
            )
        else:
            text.append(
                f"disabled · {provenance} · {remaining}",
                style=_DISABLED_STYLE,
            )
        if priority_suffix is not None:
            text.append(" · ", style="dim")
            text.append(
                priority_suffix,
                style=(
                    _PRIORITY_UNAVAILABLE_STYLE
                    if _status_is_priority_provider(status, priority)
                    else _BACKUP_STYLE
                ),
            )
    else:
        if not status.cli_available:
            text.append("CLI missing", style=_CLI_MISSING_STYLE)
            if priority_suffix is not None:
                text.append(" · ", style="dim")
                text.append(priority_suffix, style=_PRIORITY_UNAVAILABLE_STYLE)
        elif priority_suffix is not None:
            text.append(
                priority_suffix,
                style=(
                    _PRIORITY_STYLE
                    if _status_is_priority_provider(status, priority)
                    else _BACKUP_STYLE
                ),
            )
        else:
            text.append("available", style=_AVAILABLE_STYLE)
    return text


def provider_title_line(
    disables: Mapping[str, TemporaryProviderDisable],
    *,
    now: float,
    priority: TemporaryProviderPriority | None = None,
) -> Text | None:
    """Return the conditional Models-title provider-routing summary."""
    priority = _active_priority(priority, now=now)
    entries: list[tuple[str, TemporaryProviderDisable]] = []
    for provider, disable in sorted(disables.items()):
        if active_disable(disable, now=now) is None:
            continue
        entries.append((provider, disable))
    if not entries and priority is None:
        return None
    text = Text()
    if priority is not None:
        text.append("priority: ", style="dim")
        text.append(
            f"{priority.provider.upper()} ★ "
            f"{_priority_remaining_label(priority, now=now, include_left=False)}",
            style=_PRIORITY_STYLE,
        )
    if entries:
        if priority is not None:
            text.append(" · ", style="dim")
        text.append("disabled providers: ", style="dim")
    for index, (provider, disable) in enumerate(entries):
        if index:
            text.append(" · ", style="dim")
        remaining = remaining_label(disable, now=now, include_left=False)
        if disable.is_soft:
            text.append(
                f"{provider.upper()} soft {remaining}",
                style=_SOFT_DISABLED_STYLE,
            )
        else:
            text.append(
                f"{provider.upper()} {remaining}",
                style=_DISABLED_STYLE,
            )
    return text


def provider_summary_text(
    statuses: tuple[ProviderRoutingStatus, ...],
    *,
    priority: TemporaryProviderPriority | None,
    now: float,
) -> Text:
    """Return the two-line Provider Routing modal summary."""
    priority = _active_priority(priority, now=now)
    if priority is None:
        return Text(
            "Applies to new launches, follow-ups, and fallback resolution.\n"
            "Press p to prefer one available provider; backups remain usable.",
            style=_DESCRIPTION_STYLE,
        )

    owner = next(
        (status for status in statuses if status.provider == priority.provider),
        None,
    )
    headline = f"★ {priority.provider.upper()} priority"
    if owner is not None:
        disable = active_disable(owner.active_disable, now=now)
        if disable is not None and disable.is_soft:
            headline += " soft-disabled"
        elif (
            disable is not None
            or not owner.cli_available
            or "cli_missing" in owner.provenance
        ):
            headline += " unavailable"
    elif statuses:
        headline += " unavailable"
    headline += f" · {_priority_remaining_label(priority, now=now)}"
    detail = (
        f"Pools prefer {priority.provider.upper()}; other providers remain backups."
    )
    return Text(f"{headline}\n{detail}", style=_PRIORITY_STYLE)


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
    priority: TemporaryProviderPriority | None = None,
) -> Text:
    """Return the fixed-height provider description strip."""
    priority = _active_priority(
        priority if priority is not None else status.priority if status else None,
        now=now,
    )
    if status is None:
        if priority is not None:
            return Text(
                f"{priority.provider.upper()} priority is active. "
                f"Press c to clear it {_priority_remaining_label(priority, now=now)}.",
                style=_PRIORITY_STYLE,
            )
        return Text("", style=_DESCRIPTION_STYLE)
    text = Text(style=_DESCRIPTION_STYLE, no_wrap=False)
    label = status.provider.upper()
    disable = active_disable(status.active_disable, now=now)
    is_priority_provider = _status_is_priority_provider(status, priority)
    is_backup = _status_is_priority_backup(status, priority)
    if disable is not None:
        provenance = provider_disable_provenance_label(disable)
        if disable.expires_at is None:
            end = "until cleared"
        else:
            end = datetime.fromtimestamp(disable.expires_at, get_timezone()).strftime(
                "%b %-d %-I:%M%p"
            )
            end = f"until {end} ({remaining_label(disable, now=now)})"
        if disable.is_soft:
            text.append(
                f"Pools spare {label} while another member can cover; "
                "|| fallbacks and explicit %model still use it.",
                style=_SOFT_DISABLED_STYLE,
            )
            text.append(
                f"\nRunning processes continue. {provenance} soft disable {end}. "
                f"{_affected_aliases_text(status)}",
                style="dim",
            )
            if is_priority_provider and priority is not None:
                text.append(
                    f" {label} priority resumes when the soft disable clears; "
                    "press c to clear priority.",
                    style=_PRIORITY_STYLE,
                )
            elif is_backup and priority is not None:
                text.append(
                    f" Also a backup because {priority.provider.upper()} has "
                    "priority; press c to clear priority.",
                    style=_BACKUP_STYLE,
                )
        else:
            if is_priority_provider and priority is not None:
                text.append(
                    f"{label} priority intent remains "
                    f"{_priority_remaining_label(priority, now=now)}; "
                    "hard disable routes around it.",
                    style=_PRIORITY_UNAVAILABLE_STYLE,
                )
                text.append(
                    f"\n{provenance} disable {end}. Press c to clear priority.",
                    style="dim",
                )
            elif is_backup and priority is not None:
                text.append(
                    f"New launches and fallbacks route around {label}; "
                    "running provider processes continue.",
                    style=_DISABLED_STYLE,
                )
                text.append(
                    f"\n{provenance} disable {end}. {_affected_aliases_text(status)}",
                    style="dim",
                )
                text.append(
                    f" Also a backup because {priority.provider.upper()} has priority.",
                    style=_BACKUP_STYLE,
                )
            else:
                text.append(
                    f"New launches and fallbacks route around {label}; "
                    "running provider processes continue.",
                    style=_DISABLED_STYLE,
                )
                text.append(
                    f"\n{provenance} disable {end}. {_affected_aliases_text(status)}",
                    style="dim",
                )
    elif not status.cli_available:
        text.append(
            f"{label} CLI is unavailable; automatic selector routing already skips it.",
            style=_CLI_MISSING_STYLE,
        )
        if is_priority_provider:
            text.append(
                "\nPriority intent remains, but routing uses backups until the CLI "
                "is available. Press c to clear priority.",
                style=_PRIORITY_UNAVAILABLE_STYLE,
            )
        else:
            text.append(
                "\nA manual disable can still record temporary routing state for later.",
                style="dim",
            )
    elif is_priority_provider:
        text.append(
            f"{label} is preferred in pools that contain a usable {label} model.",
            style=_PRIORITY_STYLE,
        )
        text.append(
            f"\nExplicit choices and || order still apply. c clears {label} priority.",
            style="dim",
        )
    elif is_backup and priority is not None:
        preferred = priority.provider.upper()
        text.append(
            f"Enabled; {preferred} has priority. Press c to clear priority.",
            style=_BACKUP_STYLE,
        )
        text.append(
            "\nExplicit choices and || order still apply; this provider remains usable.",
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


def _priority_remaining_label(
    priority: TemporaryProviderPriority,
    *,
    now: float,
    include_left: bool = True,
) -> str:
    """Return a human-readable remaining-time label for provider priority."""
    if priority.expires_at is None:
        return "until cleared"
    suffix = " left" if include_left else ""
    return f"{format_remaining(priority.expires_at - now)}{suffix}"


def _active_priority(
    priority: TemporaryProviderPriority | None,
    *,
    now: float,
) -> TemporaryProviderPriority | None:
    if priority is None:
        return None
    return priority if priority.is_active(now) else None


def _status_priority(
    status: ProviderRoutingStatus,
    *,
    now: float,
) -> TemporaryProviderPriority | None:
    return _active_priority(status.priority, now=now)


def _status_is_priority_provider(
    status: ProviderRoutingStatus,
    priority: TemporaryProviderPriority | None,
) -> bool:
    return priority is not None and priority.provider == status.provider


def _status_is_priority_backup(
    status: ProviderRoutingStatus,
    priority: TemporaryProviderPriority | None,
) -> bool:
    return (
        priority is not None
        and status.provider != priority.provider
        and "priority_backup" in status.provenance
    )


def _priority_row_suffix(
    status: ProviderRoutingStatus,
    priority: TemporaryProviderPriority | None,
    *,
    disable: TemporaryProviderDisable | None,
    now: float,
) -> str | None:
    if priority is None:
        return None
    if _status_is_priority_provider(status, priority):
        if disable is not None and disable.is_soft:
            return "★ priority soft-disabled"
        if disable is not None or not status.cli_available:
            return "★ priority unavailable"
        return f"★ priority · {_priority_remaining_label(priority, now=now)}"
    if _status_is_priority_backup(status, priority):
        return f"backup · {priority.provider.upper()} priority"
    return None


def provider_duration_modal(
    provider: str,
    *,
    mode: str = PROVIDER_DISABLE_MODE_HARD,
    keep_current: KeepCurrentWindow | None = None,
) -> DurationPickerModal:
    """Build the duration picker used to disable ``provider``."""
    label = provider.upper()
    if mode == PROVIDER_DISABLE_MODE_SOFT:
        return DurationPickerModal(
            title=f"Soft-disable {label}",
            quick_subtitle=(
                f"Spare {label} in pools that have another option; "
                "explicit %model still runs."
            ),
            short_subtitle=(
                f"Spare {label} through a short task; explicit %model still runs."
            ),
            hour_subtitle=(
                f"Spare {label} for a focused session; explicit %model still runs."
            ),
            two_hour_subtitle=f"Spare {label} for a longer implementation block.",
            four_hour_subtitle=f"Spare {label} for half a day.",
            until_cleared_subtitle=(
                f"Spare {label} until you enable it; explicit %model still runs."
            ),
            until_time_subtitle="Choose a local clock time or date.",
            custom_placeholder="e.g., 30m, 2h, 1h30m, until cleared",
            id_prefix="provider-duration",
            keep_current=keep_current,
        )
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
        keep_current=keep_current,
    )


def provider_priority_duration_modal(
    provider: str,
    *,
    current_priority: TemporaryProviderPriority | None = None,
    now: float,
) -> DurationPickerModal:
    """Build the duration picker used to prioritize ``provider``."""
    label = provider.upper()
    active = _active_priority(current_priority, now=now)
    replacing = (
        active.provider.upper()
        if active is not None and active.provider != provider
        else None
    )
    title = (
        f"Change {label} priority"
        if active and not replacing
        else f"Prioritize {label}"
    )
    replace_suffix = (
        f" Replaces {replacing} priority after you choose a duration."
        if replacing is not None
        else ""
    )
    return DurationPickerModal(
        title=title,
        quick_subtitle=f"Prefer {label} briefly; other providers remain backups."
        f"{replace_suffix}",
        short_subtitle=f"Prefer {label} through a short task.{replace_suffix}",
        hour_subtitle=f"Prefer {label} for a focused session.{replace_suffix}",
        two_hour_subtitle=f"Prefer {label} for a longer implementation block."
        f"{replace_suffix}",
        four_hour_subtitle=f"Prefer {label} for half a day.{replace_suffix}",
        until_cleared_subtitle=f"Prefer {label} until you clear priority."
        f"{replace_suffix}",
        until_time_subtitle="Choose a local clock time or date.",
        custom_placeholder="e.g., 30m, 2h, 1h30m, until cleared",
        id_prefix="provider-duration",
    )


def duration_suffix(
    result: (
        RelativeOverrideDuration
        | OverrideUntilCleared
        | ResolvedOverrideUntil
        | KeepCurrentWindow
        | None
    ),
) -> str:
    """Return the toast suffix describing a chosen disable duration."""
    if isinstance(result, KeepCurrentWindow):
        return "with its current window"
    if isinstance(result, ResolvedOverrideUntil):
        return f"until {result.notification_display}"
    if isinstance(result, OverrideUntilCleared):
        return "until cleared"
    if isinstance(result, RelativeOverrideDuration):
        return f"for {format_duration_chosen(result.seconds)}"
    return "temporarily"
