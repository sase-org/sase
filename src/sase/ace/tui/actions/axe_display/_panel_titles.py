"""Border-title stats and builders for the Services-tab side panels.

Titles follow the Agents tribe-panel grammar
(``{icon} {Label} · {count} [chip] badges``) but every number comes from
caches the render path already holds, so title building never touches disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.text import Text

from ..._service_severity import (
    proc_clean_exit,
    service_proc_severity,
    service_proc_style,
)

_PANEL_FOCUSED_CHROME_STYLE = "#FFD75F"
_PANEL_UNFOCUSED_CHROME_STYLE = "#AFAFAF"

_SERVICE_PROCS_ICON = "⚙"
_SERVICE_PROCS_STYLE = "bold #00D7AF"
_SCHEDULED_ROUTINES_ICON = "◷"
_SCHEDULED_ROUTINES_STYLE = "bold #FFD700"

ROUTINE_PANEL_LABELS: dict[str, str] = {
    "user_routines": "User Routines",
    "plugin_routines": "Plugin Routines",
    "builtin_routines": "Builtin Routines",
}

# Severity letters use the chrome style; counts use their metric style,
# exactly like ``format_agent_count_chip``.
_SERVICE_CHIP_METRICS: tuple[tuple[str, str, str], ...] = (
    ("R", "ok", "bold #00D7AF"),
    ("W", "warn", "bold #FFAF5F"),
    ("F", "fail", "bold #FF5F5F"),
    ("S", "muted", "#AFAFAF"),
)
_ROUTINE_CHIP_METRICS: tuple[tuple[str, str, str], ...] = (
    ("R", "running", "bold #00D7AF"),
    ("E", "error", "bold #FF5F5F"),
    ("I", "idle", "#AFAFAF"),
)

_ONESHOT_RUN_BADGE = ("▷", "#5FAFD7")
_ONESHOT_OK_BADGE = ("✓", "#87AF87")
_ONESHOT_FAIL_BADGE = ("✗", "#D78787")

_JOB_RUNNING_BADGE = ("●", "bold green")
_JOB_FAILED_BADGE = ("!", "bold red")
_JOB_MISSING_BADGE = ("?", "bold yellow")
_JOB_OVERRUN_BADGE = "⚠"
_JOB_OVERRUN_STYLE = "bold #FFAF5F"


@dataclass(frozen=True)
class ServiceProcsPanelStats:
    """At-a-glance counts for the Service Procs panel title."""

    items: int = 0
    running: int = 0
    warn: int = 0
    fail: int = 0
    muted: int = 0
    oneshot_running: int = 0
    oneshot_ok: int = 0
    oneshot_failed: int = 0
    hidden_oneshots: int = 0
    host_state: str | None = None
    status_unavailable: bool = False


@dataclass(frozen=True)
class ScheduledRoutinesPanelStats:
    """At-a-glance counts for one routine panel title."""

    routines: int = 0
    running: int = 0
    error: int = 0
    idle: int = 0
    jobs: int = 0
    jobs_running: int = 0
    jobs_failed: int = 0
    jobs_missing: int = 0
    overruns: int = 0
    scheduler_badge_text: str | None = None
    scheduler_badge_style: str = ""


def _chrome_style(*, focused: bool) -> str:
    return _PANEL_FOCUSED_CHROME_STYLE if focused else _PANEL_UNFOCUSED_CHROME_STYLE


def _format_title_chip(
    metrics: tuple[tuple[str, str, str], ...],
    counts: tuple[int, ...],
    *,
    focused: bool,
) -> Text:
    """Return a zero-suppressing ``[L1 L2 ...]`` chip like the agent chip."""
    chip = Text()
    chrome = _chrome_style(focused=focused)
    parts = [
        (letter, count, style)
        for (letter, _name, style), count in zip(metrics, counts, strict=True)
        if count
    ]
    if not parts:
        return chip
    chip.append("[", style=chrome)
    for idx, (letter, count, style) in enumerate(parts):
        if idx:
            chip.append(" ", style=chrome)
        chip.append(letter, style=chrome)
        chip.append(str(count), style=style)
    chip.append("]", style=chrome)
    return chip


def _oneshot_is_failed(info: Any, running: bool) -> bool:
    """Mirror the row glyph's failed definition without importing widgets."""
    if running or info is None:
        return False
    if getattr(info, "status", None) in {"error", "killed"}:
        return True
    return getattr(info, "exit_code", None) not in (None, 0)


def service_procs_panel_stats(
    *,
    procs: Any,
    oneshots: list[tuple[Any, bool]],
    hidden_oneshots: int = 0,
    host_state: str | None = None,
    status_unavailable: bool = False,
) -> ServiceProcsPanelStats:
    """Build Service Procs title stats from cached render state.

    Args:
        procs: Cached daemon proc rows (each with ``state``/``desired``/
            ``available``/``enablement``), or ``None`` when unknown.
        oneshots: Visible oneshot ``(info, running)`` pairs.
        hidden_oneshots: Oneshots hidden by the ``.`` toggle.
        host_state: Snapshot host state; only non-``running`` states badge.
        status_unavailable: True when ``_service_status is None``.
    """
    running = warn = fail = muted = 0
    if procs is not None:
        for proc in procs:
            enablement = getattr(proc, "enablement", None)
            severity = service_proc_severity(
                getattr(proc, "state", ""),
                getattr(proc, "desired", ""),
                available=getattr(proc, "available", True),
                enabled=True
                if enablement is None
                else getattr(enablement, "enabled", True),
                clean_exit=proc_clean_exit(proc),
            )
            if severity == "ok":
                running += 1
            elif severity == "warn":
                warn += 1
            elif severity == "fail":
                fail += 1
            else:
                muted += 1
    daemon_rows = 0 if procs is None else len(list(procs))
    oneshot_running = oneshot_ok = oneshot_failed = 0
    for info, is_running in oneshots:
        if is_running:
            oneshot_running += 1
        elif _oneshot_is_failed(info, is_running):
            oneshot_failed += 1
        else:
            oneshot_ok += 1
    return ServiceProcsPanelStats(
        items=daemon_rows + len(oneshots),
        running=running,
        warn=warn,
        fail=fail,
        muted=muted,
        oneshot_running=oneshot_running,
        oneshot_ok=oneshot_ok,
        oneshot_failed=oneshot_failed,
        hidden_oneshots=hidden_oneshots,
        host_state=host_state,
        status_unavailable=status_unavailable,
    )


def scheduled_routines_panel_stats(
    *,
    routine_names: list[str],
    statuses: dict[str, Any],
    chop_names: dict[str, list[str]],
    chop_snapshots: dict[tuple[str, str], Any],
    overrun_counts: dict[str, int],
    service_procs: Any = None,
) -> ScheduledRoutinesPanelStats:
    """Build one routine panel's title stats from cached render state.

    Call once per visible source group with that group's routine names;
    pass ``service_procs`` only for the first visible routine panel so
    the scheduler badge renders once.
    """
    running = error = idle = 0
    for name in routine_names:
        status = statuses.get(name)
        value = getattr(status, "status", None) if status is not None else None
        if value == "running":
            running += 1
        elif value == "error":
            error += 1
        else:
            idle += 1
    jobs = jobs_running = jobs_failed = jobs_missing = 0
    for routine in routine_names:
        for chop in chop_names.get(routine, []):
            jobs += 1
            snap = chop_snapshots.get((routine, chop))
            runs = getattr(snap, "runs", ()) if snap is not None else ()
            if not runs:
                continue
            latest = getattr(runs[0].entry, "status", "")
            if latest == "running":
                jobs_running += 1
            elif latest in ("failure", "timeout"):
                jobs_failed += 1
            elif latest == "missing_script":
                jobs_missing += 1
    overruns = sum(overrun_counts.get(name, 0) for name in routine_names)
    scheduler_badge_text: str | None = None
    scheduler_badge_style = ""
    scheduler_proc = None
    if service_procs is not None:
        if isinstance(service_procs, dict):
            scheduler_proc = service_procs.get("scheduler")
        else:
            scheduler_proc = next(
                (p for p in service_procs if getattr(p, "name", "") == "scheduler"),
                None,
            )
    if scheduler_proc is not None and getattr(scheduler_proc, "state", "") != "running":
        enablement = getattr(scheduler_proc, "enablement", None)
        enabled = True if enablement is None else getattr(enablement, "enabled", True)
        if not enabled:
            scheduler_badge_text = "scheduler disabled"
        elif not getattr(scheduler_proc, "available", True):
            scheduler_badge_text = "scheduler unavailable"
        else:
            scheduler_badge_text = (
                f"scheduler {getattr(scheduler_proc, 'state', '') or 'unknown'}"
            )
        scheduler_badge_style = service_proc_style(
            getattr(scheduler_proc, "state", ""),
            getattr(scheduler_proc, "desired", ""),
            available=getattr(scheduler_proc, "available", True),
            enabled=enabled,
            clean_exit=proc_clean_exit(scheduler_proc),
        )
    return ScheduledRoutinesPanelStats(
        routines=len(routine_names),
        running=running,
        error=error,
        idle=idle,
        jobs=jobs,
        jobs_running=jobs_running,
        jobs_failed=jobs_failed,
        jobs_missing=jobs_missing,
        overruns=overruns,
        scheduler_badge_text=scheduler_badge_text,
        scheduler_badge_style=scheduler_badge_style,
    )


def service_procs_panel_title(stats: ServiceProcsPanelStats, *, focused: bool) -> Text:
    """Build the Service Procs border title from ``stats``."""
    from ..._service_severity import service_host_style

    title = Text()
    title.append(f"{_SERVICE_PROCS_ICON} ", style=_SERVICE_PROCS_STYLE)
    title.append("Service Procs", style=_SERVICE_PROCS_STYLE)
    title.append(" · ", style=_PANEL_UNFOCUSED_CHROME_STYLE)
    title.append(str(stats.items), style=_chrome_style(focused=focused))
    chip = _format_title_chip(
        _SERVICE_CHIP_METRICS,
        (stats.running, stats.warn, stats.fail, stats.muted),
        focused=focused,
    )
    if chip:
        title.append(" ", style=_PANEL_UNFOCUSED_CHROME_STYLE)
        title.append_text(chip)
    for count, (glyph, style) in (
        (stats.oneshot_running, _ONESHOT_RUN_BADGE),
        (stats.oneshot_ok, _ONESHOT_OK_BADGE),
        (stats.oneshot_failed, _ONESHOT_FAIL_BADGE),
    ):
        if count:
            title.append(" ", style=_PANEL_UNFOCUSED_CHROME_STYLE)
            title.append(f"{glyph}{count}", style=style)
    if stats.hidden_oneshots:
        title.append(" · ", style=_PANEL_UNFOCUSED_CHROME_STYLE)
        title.append(f"+{stats.hidden_oneshots} hidden", style="dim")
    if stats.host_state is not None and stats.host_state != "running":
        title.append(" · ", style=_PANEL_UNFOCUSED_CHROME_STYLE)
        title.append(
            f"host {stats.host_state}",
            style=service_host_style(stats.host_state),
        )
    if stats.status_unavailable:
        title.append(" · ", style=_PANEL_UNFOCUSED_CHROME_STYLE)
        title.append("status unavailable", style="bold #FFAF5F")
    return title


def _jobs_label(count: int) -> str:
    """Return ``1 job`` or ``N jobs`` for panel titles."""
    return f"{count} job" if count == 1 else f"{count} jobs"


def source_routine_panel_title(
    stats: ScheduledRoutinesPanelStats,
    *,
    focused: bool,
    label: str,
) -> Text:
    """Build one source-panel border title from ``stats``."""
    title = Text(no_wrap=True, overflow="ellipsis")
    title.append(f"{_SCHEDULED_ROUTINES_ICON} ", style=_SCHEDULED_ROUTINES_STYLE)
    title.append(label, style=_SCHEDULED_ROUTINES_STYLE)
    title.append(" · ", style=_PANEL_UNFOCUSED_CHROME_STYLE)
    title.append(str(stats.routines), style=_chrome_style(focused=focused))
    chip = _format_title_chip(
        _ROUTINE_CHIP_METRICS,
        (stats.running, stats.error, stats.idle),
        focused=focused,
    )
    if chip:
        title.append(" ", style=_PANEL_UNFOCUSED_CHROME_STYLE)
        title.append_text(chip)
    title.append(" · ", style=_PANEL_UNFOCUSED_CHROME_STYLE)
    title.append(_jobs_label(stats.jobs), style=_chrome_style(focused=focused))
    for count, (glyph, style) in (
        (stats.jobs_running, _JOB_RUNNING_BADGE),
        (stats.jobs_failed, _JOB_FAILED_BADGE),
        (stats.jobs_missing, _JOB_MISSING_BADGE),
    ):
        if count:
            title.append(" ", style=_PANEL_UNFOCUSED_CHROME_STYLE)
            title.append(f"{glyph}{count}", style=style)
    if stats.overruns:
        title.append(" ", style=_PANEL_UNFOCUSED_CHROME_STYLE)
        title.append(f"{_JOB_OVERRUN_BADGE}{stats.overruns}", style=_JOB_OVERRUN_STYLE)
    if stats.scheduler_badge_text:
        title.append(" · ", style=_PANEL_UNFOCUSED_CHROME_STYLE)
        title.append(stats.scheduler_badge_text, style=stats.scheduler_badge_style)
    return title


def scheduled_routines_panel_title(
    stats: ScheduledRoutinesPanelStats, *, focused: bool
) -> Text:
    """Build the legacy Scheduled Routines border title from ``stats``.

    Kept for existing callers/tests; new panels use
    :func:`source_routine_panel_title` with a source label.
    """
    return source_routine_panel_title(
        stats, focused=focused, label="Scheduled Routines"
    )


# Source-panel aliases: the per-panel stats shape is identical, only the
# routine-name subset and the scheduler-badge owner change.
SourceRoutinesPanelStats = ScheduledRoutinesPanelStats
source_routine_panel_stats = scheduled_routines_panel_stats
