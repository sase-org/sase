"""Automatic update-available checks and toast for the ace TUI."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any, cast

from sase.config.core import load_merged_config
from sase.dev_update.prebuild import schedule_rust_prebuild
from sase.updates import (
    UpdateStatus,
    fetch_incoming_commits,
    get_cached_update_status,
    revalidate_update_status,
    update_status_snapshot_is_fresh,
)

from ._update_toast_config import (
    _AUTOMATIC_UPDATE_CHECK_INTERVAL_SECONDS as _AUTOMATIC_UPDATE_CHECK_INTERVAL_SECONDS,
    UpdateToastConfig as _UpdateToastConfig,
    parse_update_toast_config,
    resolve_check_interval_seconds as resolve_check_interval_seconds,
)
from ._update_toast_message import (
    _UPDATE_GLYPH as _UPDATE_GLYPH,
    format_update_toast_message as _format_update_toast_message,
)
from ._update_toast_sections import (
    ToastRepoSection as _ToastRepoSection,
    build_startup_toast_sections as _build_startup_toast_sections_impl,
    build_toast_commit_sections as _build_toast_commit_sections,
    header_only_sections as _header_only_sections,
)

if TYPE_CHECKING:
    from textual.timer import Timer

log = logging.getLogger(__name__)

_TOAST_TITLE = f"{_UPDATE_GLYPH} Updates available"
_TOAST_TIMEOUT_SECONDS = 12.0
_AUTOMATIC_UPDATE_CHECK_TIMER_NAME = "automatic-update-check"


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
    _automatic_update_status: UpdateStatus | None

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
        status_required = (
            config.prebuild_rust
            or config.indicator
            or (config.startup_toast and not periodic)
        )
        if not status_required:
            return None
        status = _get_automatic_update_status(config, periodic=periodic)
        if status is None:
            return None

        if config.prebuild_rust:
            try:
                _schedule_rust_prebuild(status, config)
            except Exception:
                log.debug("Failed to schedule Rust prebuild", exc_info=True)

        ui_enabled = config.indicator or config.startup_toast
        if periodic and not config.indicator:
            ui_enabled = False
        if not ui_enabled:
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
        _maybe_refresh_open_update_panel(self)

    def _apply_startup_update_status(
        self,
        status: UpdateStatus,
        config: _UpdateToastConfig,
        sections: Sequence[_ToastRepoSection] | None = None,
    ) -> None:
        """Apply automatic update status to all UI surfaces."""
        # This UI-thread assignment is the only authority used by the global
        # comprehensive-update shortcut. Failed/in-flight checks never reach
        # this method, and a successful empty result intentionally replaces a
        # prior non-empty projection.
        self._automatic_update_status = status
        self._automatic_update_provider_names = tuple(
            candidate.provider for candidate in status.provider_candidates
        )
        if config.indicator:
            self._refresh_updates_indicator(status)
        if config.startup_toast:
            self._show_startup_update_toast(status, sections)
        _maybe_refresh_open_update_panel(self)

    def _show_startup_update_toast(
        self,
        status: UpdateStatus,
        sections: Sequence[_ToastRepoSection] | None = None,
    ) -> None:
        """Show the automatic update toast once per TUI session."""
        if getattr(self, "_update_toast_shown", False):
            return
        if not status.has_updates:
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
                    0,
                    0,
                )
                return
            if status is None:
                status = get_cached_update_status(revalidate_only=True)
            else:
                status = revalidate_update_status(status)
            self.call_from_thread(  # type: ignore[attr-defined]
                self._set_updates_indicator_state,
                0 if status is None else status.component_count,
                False if status is None else status.has_core_update,
                0 if status is None else status.agent_cli_count,
                0 if status is None else status.manual_agent_cli_count,
            )
        except Exception:
            log.debug("Updates-indicator refresh failed", exc_info=True)

    def _refresh_updates_indicator(self, status: UpdateStatus) -> None:
        """Set the top-bar updates badge from a status object."""
        self._set_updates_indicator_state(
            status.component_count,
            status.has_core_update,
            status.agent_cli_count,
            status.manual_agent_cli_count,
        )

    def _set_updates_indicator_state(
        self,
        count: int,
        core: bool = False,
        agent_cli_count: int = 0,
        manual_agent_cli_count: int = 0,
    ) -> None:
        """Set the top-bar updates badge state if the widget is mounted."""
        from ..widgets import UpdatesAvailableIndicator

        try:
            indicator = self.query_one(  # type: ignore[attr-defined]
                "#updates-indicator",
                UpdatesAvailableIndicator,
            )
        except Exception:
            return
        indicator.set_available(
            count,
            core=core,
            agent_cli_count=agent_cli_count,
            manual_agent_cli_count=manual_agent_cli_count,
        )


def _load_update_toast_config() -> _UpdateToastConfig:
    """Load automatic update-check config from merged SASE config."""
    return parse_update_toast_config(load_merged_config())


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


def _build_startup_toast_sections(
    status: UpdateStatus,
    config: _UpdateToastConfig,
) -> tuple[_ToastRepoSection, ...]:
    """Build commit-preview sections using the facade's patchable fetch hook."""
    return _build_startup_toast_sections_impl(
        status,
        config,
        fetch_fn=_fetch_incoming_commits,
    )


_fetch_incoming_commits = fetch_incoming_commits
_schedule_rust_prebuild = schedule_rust_prebuild


def _maybe_refresh_open_update_panel(host: object) -> None:
    """Push a fresh projection into the Update panel when it is the active screen."""
    refresh = getattr(host, "_refresh_open_update_panel", None)
    if callable(refresh):
        refresh()


__all__ = [
    "UpdateToastMixin",
    "resolve_check_interval_seconds",
]
