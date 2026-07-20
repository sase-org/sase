"""Automatic update-available checks and toast for the ace TUI."""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any, cast

from textual.markup import escape

from sase.config.core import load_merged_config
from sase.updates import (
    CommitSourceSpec,
    CommitSummary,
    DEFAULT_UPDATE_STATUS_TTL_SECONDS,
    IncomingCommits,
    UpdateStatus,
    allocate_commit_budget,
    component_commit_spec,
    fetch_incoming_commits,
    get_cached_update_status,
    revalidate_update_status,
    update_status_snapshot_is_fresh,
)

from ..modals.config_center_modal import (
    center_tab_accent,
)

if TYPE_CHECKING:
    from textual.timer import Timer

    from sase.updates import OutdatedComponent

log = logging.getLogger(__name__)

_UPDATE_GLYPH = "↑"
_TOAST_TITLE = f"{_UPDATE_GLYPH} Updates available"
_TOAST_TIMEOUT_SECONDS = 12.0
# Fallbacks used only when a TTL key is present but unparsable; both resolve to
# the 10-minute default so a garbage override never silently re-enables a day.
_DEFAULT_CHECK_TTL_MINUTES = DEFAULT_UPDATE_STATUS_TTL_SECONDS / 60.0
_DEFAULT_CHECK_TTL_HOURS = DEFAULT_UPDATE_STATUS_TTL_SECONDS / 3600.0
_DEFAULT_STARTUP_TOAST_MAX_COMMITS = 20
_STARTUP_TOAST_DEADLINE_SECONDS = 8.0
_AUTOMATIC_UPDATE_CHECK_INTERVAL_SECONDS = 600.0
_AUTOMATIC_UPDATE_CHECK_TIMER_NAME = "automatic-update-check"
_DEFAULT_RECOMPUTE_INTERVAL_MINUTES = 60.0
_DEFAULT_RECOMPUTE_INTERVAL_SECONDS = _DEFAULT_RECOMPUTE_INTERVAL_MINUTES * 60.0
_COMMIT_SUBJECT_WIDTH = 58

FetchIncomingCommitsFn = Callable[..., IncomingCommits]


@dataclass(frozen=True)
class _UpdateToastConfig:
    """Config values controlling automatic update checks and update toasts."""

    startup_toast: bool = True
    post_update_toast: bool = True
    post_update_toast_diffstat: bool = True
    indicator: bool = True
    check_ttl_seconds: float = DEFAULT_UPDATE_STATUS_TTL_SECONDS
    recompute_interval_seconds: float = _DEFAULT_RECOMPUTE_INTERVAL_SECONDS
    incoming_commits_enabled: bool = True
    startup_toast_max_commits: int = _DEFAULT_STARTUP_TOAST_MAX_COMMITS


@dataclass(frozen=True)
class _ToastRepoSection:
    """One repository section in the automatic update toast."""

    label: str
    installed_version: str
    latest_version: str
    commits: tuple[CommitSummary, ...] = ()
    total: int = 0


@dataclass(frozen=True)
class _AutomaticUpdateCheckResult:
    """Worker result ready to apply to ACE's update surfaces."""

    status: UpdateStatus
    config: _UpdateToastConfig
    sections: tuple[_ToastRepoSection, ...] | None = None


class UpdateToastMixin:
    """Mixin that schedules and renders automatic update availability."""

    _update_toast_shown: bool
    _automatic_update_check_in_flight: bool
    _automatic_update_check_interval_seconds: float
    _automatic_update_check_timer: Timer | None
    _automatic_update_provider_names: tuple[str, ...] | None

    def _schedule_startup_update_toast_check(self) -> None:
        """Start periodic checks and schedule the first one after first paint."""
        self._start_periodic_update_checks()
        self._schedule_automatic_update_check(periodic=False)

    def _start_periodic_update_checks(self) -> None:
        """Register the configured session timer once."""
        if getattr(self, "_automatic_update_check_timer", None) is not None:
            return
        try:
            self._automatic_update_check_timer = self.set_interval(  # type: ignore[attr-defined]
                getattr(
                    self,
                    "_automatic_update_check_interval_seconds",
                    _AUTOMATIC_UPDATE_CHECK_INTERVAL_SECONDS,
                ),
                self._on_periodic_update_check,
                name=_AUTOMATIC_UPDATE_CHECK_TIMER_NAME,
            )
        except Exception:
            log.debug("Failed to start periodic update checks", exc_info=True)

    def _on_periodic_update_check(self) -> None:
        """Handle a timer tick using only mounted UI and in-memory state."""
        self._schedule_automatic_update_check(periodic=True)

    def _schedule_automatic_update_check(self, *, periodic: bool) -> None:
        """Schedule one guarded automatic update worker."""
        if getattr(self, "_automatic_update_check_in_flight", False):
            return

        self._automatic_update_check_in_flight = True
        worker_fn: Any = self._run_startup_update_toast_check
        if periodic:
            worker_fn = partial(self._run_startup_update_toast_check, periodic=True)
        try:
            self.run_worker(  # type: ignore[attr-defined]
                cast(Any, worker_fn),
                name="automatic-update-check",
                thread=True,
                exclusive=False,
                group="startup-loads",
            )
        except Exception:
            self._automatic_update_check_in_flight = False
            log.debug("Failed to schedule automatic update-status check", exc_info=True)

    def _run_startup_update_toast_check(self, *, periodic: bool = False) -> None:
        """Run an automatic cached update-status check in a worker thread."""
        scheduled = getattr(self, "_automatic_update_check_in_flight", False)
        result: _AutomaticUpdateCheckResult | None = None
        try:
            result = self._compute_automatic_update_check(periodic=periodic)
        except Exception:
            log.debug("Automatic update-status check failed", exc_info=True)
        finally:
            if scheduled:
                self._finish_automatic_update_check_from_worker(result)

        # Preserve direct mixin-harness usage: an unscheduled worker invocation
        # still applies a successful result, but has no overlap guard to clear.
        if not scheduled and result is not None:
            self.call_from_thread(  # type: ignore[attr-defined]
                self._apply_startup_update_status,
                result.status,
                result.config,
                result.sections,
            )

    def _compute_automatic_update_check(
        self,
        *,
        periodic: bool,
    ) -> _AutomaticUpdateCheckResult | None:
        """Compute one automatic update result without touching mounted widgets."""
        config = _load_update_toast_config()
        if periodic and not config.indicator:
            return None
        if not config.startup_toast and not config.indicator:
            return None
        status = _get_automatic_update_status(config, periodic=periodic)
        if status is None:
            return None

        sections = None
        should_build_toast = (
            config.startup_toast
            and status.has_component_updates
            and not getattr(self, "_update_toast_shown", False)
        )
        if should_build_toast:
            try:
                sections = _build_startup_toast_sections(status, config)
            except Exception:
                log.debug(
                    "Failed to build automatic update toast sections",
                    exc_info=True,
                )
        return _AutomaticUpdateCheckResult(status, config, sections)

    def _finish_automatic_update_check_from_worker(
        self,
        result: _AutomaticUpdateCheckResult | None,
    ) -> None:
        """Marshal worker completion and guard release to the UI thread."""
        try:
            self.call_from_thread(  # type: ignore[attr-defined]
                self._complete_automatic_update_check,
                result,
            )
        except Exception:
            # Textual may reject callbacks while shutting down. No timer can
            # fire after teardown, but still leave direct state retryable.
            self._automatic_update_check_in_flight = False
            log.debug("Failed to finish automatic update-status check", exc_info=True)

    def _complete_automatic_update_check(
        self,
        result: _AutomaticUpdateCheckResult | None,
    ) -> None:
        """Apply a worker result and release its overlap guard on the UI thread."""
        try:
            if result is not None:
                self._apply_startup_update_status(
                    result.status,
                    result.config,
                    result.sections,
                )
        finally:
            self._automatic_update_check_in_flight = False

    def _apply_startup_update_status(
        self,
        status: UpdateStatus,
        config: _UpdateToastConfig,
        sections: Sequence[_ToastRepoSection] | None = None,
    ) -> None:
        """Apply automatic update status to all UI surfaces."""
        # This UI-thread assignment is the only authority used by the global
        # comprehensive-update shortcut.  Failed/in-flight checks never reach
        # this method, and a successful empty result intentionally replaces a
        # prior non-empty projection.
        self._automatic_update_provider_names = tuple(
            candidate.provider for candidate in status.provider_candidates
        )
        if config.indicator:
            self._refresh_updates_indicator(status)
        if config.startup_toast:
            self._show_startup_update_toast(status, sections)

    def _show_startup_update_toast(
        self,
        status: UpdateStatus,
        sections: Sequence[_ToastRepoSection] | None = None,
    ) -> None:
        """Show the automatic update toast once per TUI session."""
        if getattr(self, "_update_toast_shown", False):
            return
        if not status.has_component_updates:
            return
        self._update_toast_shown = True
        self.notify(  # type: ignore[attr-defined]
            _format_update_toast_message(status, sections),
            title=_TOAST_TITLE,
            severity="information",
            timeout=_TOAST_TIMEOUT_SECONDS,
            markup=True,
        )

    def _schedule_updates_indicator_revalidation(
        self,
        status: UpdateStatus | None = None,
    ) -> None:
        """Refresh the updates badge from the cached snapshot off-thread."""
        worker_fn: Any = self._run_updates_indicator_revalidation
        if status is not None:
            worker_fn = partial(self._run_updates_indicator_revalidation, status)
        try:
            self.run_worker(  # type: ignore[attr-defined]
                cast(Any, worker_fn),
                thread=True,
                exclusive=False,
                group="startup-loads",
            )
        except Exception:
            log.debug("Failed to schedule updates-indicator refresh", exc_info=True)

    def _run_updates_indicator_revalidation(
        self,
        status: UpdateStatus | None = None,
    ) -> None:
        """Revalidate the cached update snapshot without network or git fetches."""
        try:
            config = _load_update_toast_config()
            if not config.indicator:
                self.call_from_thread(  # type: ignore[attr-defined]
                    self._set_updates_indicator_state,
                    0,
                    False,
                )
                return
            if status is None:
                status = get_cached_update_status(revalidate_only=True)
            else:
                status = revalidate_update_status(status)
            self.call_from_thread(  # type: ignore[attr-defined]
                self._set_updates_indicator_state,
                0 if status is None else status.count,
                False if status is None else status.has_core_update,
            )
        except Exception:
            log.debug("Updates-indicator refresh failed", exc_info=True)

    def _refresh_updates_indicator(self, status: UpdateStatus) -> None:
        """Set the top-bar updates badge from a status object."""
        self._set_updates_indicator_state(status.count, status.has_core_update)

    def _set_updates_indicator_state(self, count: int, core: bool = False) -> None:
        """Set the top-bar updates badge state if the widget is mounted."""
        from ..widgets import UpdatesAvailableIndicator

        try:
            indicator = self.query_one(  # type: ignore[attr-defined]
                "#updates-indicator",
                UpdatesAvailableIndicator,
            )
        except Exception:
            return
        indicator.set_available(count, core=core)


def _load_update_toast_config() -> _UpdateToastConfig:
    """Load automatic update-check config from merged SASE config."""
    data = load_merged_config()
    ace = data.get("ace")
    if not isinstance(ace, dict):
        return _UpdateToastConfig()
    updates = ace.get("updates")
    if not isinstance(updates, dict):
        return _UpdateToastConfig()
    return _UpdateToastConfig(
        startup_toast=_coerce_bool(updates.get("startup_toast"), default=True),
        post_update_toast=_coerce_bool(updates.get("post_update_toast"), default=True),
        post_update_toast_diffstat=_coerce_bool(
            updates.get("post_update_toast_diffstat"),
            default=True,
        ),
        indicator=_coerce_bool(updates.get("indicator"), default=True),
        check_ttl_seconds=_resolve_check_ttl_seconds(updates),
        recompute_interval_seconds=_resolve_recompute_interval_seconds(updates),
        incoming_commits_enabled=_incoming_commits_enabled(updates),
        startup_toast_max_commits=_coerce_nonnegative_int(
            updates.get("startup_toast_max_commits"),
            default=_DEFAULT_STARTUP_TOAST_MAX_COMMITS,
        ),
    )


def _resolve_check_ttl_seconds(updates: dict[str, Any]) -> float:
    """Resolve the automatic-check cache TTL from the updates config.

    ``check_ttl_minutes`` is the primary knob; ``check_ttl_hours`` is retained
    only for backward compatibility and consulted when minutes is absent. The
    value is carried internally as seconds so the worker never re-derives units.
    """
    minutes = updates.get("check_ttl_minutes")
    if minutes is not None:
        return (
            _coerce_positive_float(minutes, default=_DEFAULT_CHECK_TTL_MINUTES) * 60.0
        )
    hours = updates.get("check_ttl_hours")
    if hours is not None:
        return _coerce_positive_float(hours, default=_DEFAULT_CHECK_TTL_HOURS) * 3600.0
    return DEFAULT_UPDATE_STATUS_TTL_SECONDS


def resolve_check_interval_seconds(updates: dict[str, Any]) -> float:
    """Resolve the positive, finite ACE session check interval in seconds."""
    default_minutes = _AUTOMATIC_UPDATE_CHECK_INTERVAL_SECONDS / 60.0
    minutes = _coerce_strict_positive_finite_float(
        updates.get("check_interval_minutes"),
        default=default_minutes,
    )
    seconds = minutes * 60.0
    if not math.isfinite(seconds) or seconds <= 0:
        return _AUTOMATIC_UPDATE_CHECK_INTERVAL_SECONDS
    return seconds


def _resolve_recompute_interval_seconds(updates: dict[str, Any]) -> float:
    """Resolve the cadence for periodic full network recomputes."""
    minutes = _coerce_strict_positive_finite_float(
        updates.get("recompute_interval_minutes"),
        default=_DEFAULT_RECOMPUTE_INTERVAL_MINUTES,
    )
    seconds = minutes * 60.0
    if not math.isfinite(seconds) or seconds <= 0:
        return _DEFAULT_RECOMPUTE_INTERVAL_SECONDS
    return seconds


def _get_automatic_update_status(
    config: _UpdateToastConfig,
    *,
    periodic: bool,
    now: float | None = None,
) -> UpdateStatus | None:
    """Load automatic status with separate startup and periodic cadences."""
    if not periodic:
        return get_cached_update_status(ttl_seconds=config.check_ttl_seconds)

    status = get_cached_update_status(revalidate_only=True)
    if status is not None and update_status_snapshot_is_fresh(
        status,
        now=now,
        ttl_seconds=config.recompute_interval_seconds,
    ):
        return status

    # A zero TTL forces the existing network recompute path without forwarding
    # ``refresh=True`` into lower caches. Missing snapshots are also initialized
    # here so a failed startup check can recover during a long-running session.
    return get_cached_update_status(ttl_seconds=0.0)


def _incoming_commits_enabled(updates: dict[str, Any]) -> bool:
    incoming = updates.get("incoming_commits")
    if not isinstance(incoming, dict):
        return True
    return _coerce_bool(incoming.get("enabled"), default=True)


def _build_startup_toast_sections(
    status: UpdateStatus,
    config: _UpdateToastConfig,
) -> tuple[_ToastRepoSection, ...]:
    if not config.incoming_commits_enabled or config.startup_toast_max_commits <= 0:
        return _header_only_sections(status.components)
    return _build_toast_commit_sections(
        status.components,
        fetch_fn=_fetch_incoming_commits,
        max_total=config.startup_toast_max_commits,
        offline=False,
        deadline=time.monotonic() + _STARTUP_TOAST_DEADLINE_SECONDS,
    )


def _build_toast_commit_sections(
    components: Sequence[OutdatedComponent],
    *,
    fetch_fn: FetchIncomingCommitsFn,
    max_total: int,
    offline: bool,
    deadline: float,
) -> tuple[_ToastRepoSection, ...]:
    """Fetch, fairly truncate, and align incoming commits to update components."""
    if max_total <= 0:
        return _header_only_sections(components)
    incoming_by_index: dict[int, IncomingCommits] = {}
    targets: list[tuple[int, CommitSourceSpec]] = []
    for index, component in enumerate(components):
        spec = component_commit_spec(component)
        if spec is not None:
            targets.append((index, spec))
    targets.sort(key=lambda item: (1 if item[1].source == "github" else 0, item[0]))
    for index, spec in targets:
        if time.monotonic() >= deadline:
            break
        try:
            incoming_by_index[index] = fetch_fn(
                spec,
                limit=max_total,
                offline=offline,
            )
        except Exception:  # noqa: BLE001 - update hints must never break ACE.
            log.debug(
                "Failed to fetch incoming commits for automatic update toast",
                exc_info=True,
            )
    totals = [
        _fetchable_total(incoming_by_index.get(index))
        for index, _component in enumerate(components)
    ]
    allocations = allocate_commit_budget(totals, max_total)
    sections: list[_ToastRepoSection] = []
    for index, component in enumerate(components):
        incoming = incoming_by_index.get(index)
        total = totals[index]
        allocated = allocations[index]
        commits = incoming.commits[:allocated] if incoming is not None else ()
        sections.append(
            _ToastRepoSection(
                label=component.display_name,
                installed_version=component.installed_version or "unknown",
                latest_version=component.latest_version or "unknown",
                commits=tuple(commits),
                total=total,
            )
        )
    return tuple(sections)


def _fetchable_total(incoming: IncomingCommits | None) -> int:
    if incoming is None or incoming.source == "unavailable":
        return 0
    return max(0, incoming.total)


def _header_only_sections(
    components: Sequence[OutdatedComponent],
) -> tuple[_ToastRepoSection, ...]:
    return tuple(
        _ToastRepoSection(
            label=component.display_name,
            installed_version=component.installed_version or "unknown",
            latest_version=component.latest_version or "unknown",
        )
        for component in components
    )


def _format_update_toast_message(
    status: UpdateStatus,
    sections: Sequence[_ToastRepoSection] | None = None,
) -> str:
    """Build the Rich/Textual markup body for the update toast."""
    accent = center_tab_accent("updates") or "#AF87FF"
    count = status.component_count
    noun = "update" if count == 1 else "updates"
    repo_sections = (
        tuple(sections)
        if sections is not None
        else _header_only_sections(status.components)
    )
    lines = [f"[bold {accent}]{count} {noun}[/] available"]
    if repo_sections:
        lines.append("")
    for index, section in enumerate(repo_sections):
        if index:
            lines.append("")
        lines.extend(_repo_section_lines(section, accent))
    if repo_sections:
        lines.append("")
    lines.append(_shortcut_line(accent))
    return "\n".join(lines)


def _repo_section_lines(section: _ToastRepoSection, accent: str) -> list[str]:
    lines = [
        (
            f"[bold {accent}]{_UPDATE_GLYPH} {escape(section.label)}[/]  "
            f"[dim]{escape(section.installed_version)} → "
            f"{escape(section.latest_version)}[/]"
        )
    ]
    for commit in section.commits:
        lines.append(_commit_line(commit))
    extra = max(0, section.total - len(section.commits))
    if extra > 0:
        lines.append(f"  [dim]+{extra} more…[/]")
    return lines


def _commit_line(commit: CommitSummary) -> str:
    subject = _ellipsize(commit.subject.strip(), _COMMIT_SUBJECT_WIDTH)
    sha = escape(commit.short_sha.strip())
    if not subject:
        return f"  [dim]{sha}[/]"
    return f"  [dim]{sha}[/]  {escape(subject)}"


def _shortcut_line(accent: str) -> str:
    return f"Press [bold {accent}],U[/] to update sase, core & plugins"


def _coerce_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", "none", "disabled"}:
            return False
    return default


def _coerce_nonnegative_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value if value >= 0 else default
    if isinstance(value, float) and value.is_integer():
        parsed = int(value)
        return parsed if parsed >= 0 else default
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return default
        return parsed if parsed >= 0 else default
    return default


def _coerce_positive_float(value: object, *, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value) if value >= 0 else default
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return default
        return parsed if parsed >= 0 else default
    return default


def _coerce_strict_positive_finite_float(value: object, *, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    try:
        parsed = float(value)
    except OverflowError:
        return default
    return parsed if math.isfinite(parsed) and parsed > 0 else default


def _ellipsize(value: str, width: int) -> str:
    if width <= 0 or len(value) <= width:
        return value
    if width == 1:
        return "…"
    return f"{value[: width - 1]}…"


_fetch_incoming_commits = fetch_incoming_commits


__all__ = [
    "UpdateToastMixin",
    "resolve_check_interval_seconds",
]
