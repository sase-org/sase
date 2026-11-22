"""Probe and revalidate machine-capacity inputs off Textual's pump."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ._auto_refresh_capacity_signatures import (
    CAPACITY_REPORT_POLL_SECONDS,
    capacity_override_fingerprint,
    freeze_capacity_value,
)

log = logging.getLogger(__name__)


class EventAutoRefreshCapacityProbeMixin:
    """Mixin for polling capacity tokens and cheap 10s revalidation."""

    def _probe_machine_capacity_surface_token(self) -> object:
        """Stat only the admission token and runner-limit override file."""
        probe = getattr(self, "_machine_capacity_token_probe", None)
        if callable(probe):
            return probe()
        from sase.config.runner_limit_override import runner_limit_override_path
        from sase.core.agent_hold_facade import agent_hold_store_path
        from sase.core.paths import sase_home

        from ._surface_tokens import probe_runner_capacity_token

        return probe_runner_capacity_token(
            sase_home() / "runner_slots.token",
            runner_limit_override_path(),
            agent_hold_store_path(),
        )

    def _current_capacity_hold_snapshot(self, now_wall: float) -> Any:
        """Return frozen holds for revalidation; tests may inject a source."""
        source = getattr(self, "_machine_capacity_hold_source", None)
        if callable(source):
            return freeze_capacity_value(source(now_wall))
        from sase.core.agent_hold_store import peek_active_agent_holds

        return freeze_capacity_value(peek_active_agent_holds(now=now_wall))

    def _current_capacity_override_snapshot(self, now_wall: float) -> Any:
        """Return override fingerprint without timestamps; tests may inject."""
        source = getattr(self, "_machine_capacity_override_source", None)
        if callable(source):
            configured, override = source(now_wall)
            return capacity_override_fingerprint(configured, override)
        from sase.config.core import get_configured_max_running_agents
        from sase.config.runner_limit_override import get_active_runner_limit_override

        configured_limit = get_configured_max_running_agents()
        try:
            override = get_active_runner_limit_override(now_wall)
        except Exception:
            log.debug("Capacity override probe failed", exc_info=True)
            return None
        return capacity_override_fingerprint(configured_limit, override)

    def _current_capacity_liveness_snapshot(self) -> Any | None:
        """Return frozen PID liveness; None means unknown (fail open)."""
        source = getattr(self, "_machine_capacity_liveness_source", None)
        if callable(source):
            return freeze_capacity_value(source())
        try:
            from sase.core.runner_slots._scan_cache import read_runner_slot_scan_cache
            from sase.core.runner_slots._scan import record_liveness_probe
        except Exception:
            log.debug("Capacity liveness probe unavailable", exc_info=True)
            return None
        try:
            cached = read_runner_slot_scan_cache()
        except Exception:
            log.debug("Capacity scan cache read failed", exc_info=True)
            return None
        if cached is None:
            return None
        try:
            is_live = record_liveness_probe()
            aliveness = {
                str(getattr(record, "artifact_dir", "")): bool(is_live(record))
                for record in cached.records
            }
        except Exception:
            log.debug("Capacity liveness probe failed", exc_info=True)
            return None
        return freeze_capacity_value(aliveness)

    async def _fetch_capacity_revalidation_snapshot(
        self, now_wall: float
    ) -> tuple[Any, Any, Any | None]:
        """Fetch holds/override/liveness off-thread for the 10s revalidation."""
        holds, override_fp, liveness = await asyncio.to_thread(
            lambda: (
                self._current_capacity_hold_snapshot(now_wall),
                self._current_capacity_override_snapshot(now_wall),
                self._current_capacity_liveness_snapshot(),
            )
        )
        return holds, override_fp, liveness

    def _capacity_time_inputs_unchanged(
        self,
        holds: Any,
        override_fp: Any,
        liveness: Any | None,
    ) -> bool:
        """Return True when time-dependent inputs match the last build."""
        if holds is None or override_fp is None or liveness is None:
            return False
        if getattr(self, "_machine_capacity_last_holds_signature", None) is None:
            return False
        if getattr(self, "_machine_capacity_last_override_signature", None) is None:
            return False
        if getattr(self, "_machine_capacity_last_liveness_signature", None) is None:
            return False
        return (
            holds == getattr(self, "_machine_capacity_last_holds_signature", None)
            and override_fp
            == getattr(self, "_machine_capacity_last_override_signature", None)
            and liveness
            == getattr(self, "_machine_capacity_last_liveness_signature", None)
        )

    def _capacity_needs_time_authoritative_check(self) -> bool:
        """Return True when time alone could change visible output.

        Waiters with deference enabled can reorder with time even when files,
        holds, override and liveness are unchanged. Retain the bounded
        authoritative check for that case while still skipping unchanged
        publication when the rebuild proves identical.
        """
        try:
            report = getattr(self, "_machine_capacity_report", None)
            waiters = getattr(report, "waiters", ()) if report is not None else ()
            if not waiters:
                return False
            from sase.config.core import get_runner_slot_deference_max_seconds

            return int(get_runner_slot_deference_max_seconds()) > 0
        except Exception:
            return True

    async def _probe_machine_capacity_refresh_due(
        self,
        *,
        telemetry: dict[str, object] | None = None,
    ) -> bool:
        """Probe the capacity token off the UI thread; True when due.

        Keeps the ten-second revalidation opportunity but no longer equates
        poll cadence with an unconditional expensive rebuild. When the token
        is unchanged, revalidates holds/override expiry and process liveness
        cheaply; only a detected input change or a time-dependent waiter
        case triggers the authoritative rebuild.
        """
        if telemetry is not None:
            telemetry["token_probe_count"] = 1
            telemetry["revalidation_probe_count"] = 0

        def finish(due: bool, outcome: str) -> bool:
            if telemetry is not None:
                telemetry["probe_outcome"] = outcome
            return due

        # Clear any stale snapshot so _run never reuses a previous tick's
        # inputs for caching after a token-change rebuild.
        try:
            if hasattr(self, "_machine_capacity_probe_snapshot"):
                delattr(self, "_machine_capacity_probe_snapshot")
        except Exception:
            pass
        try:
            token = await asyncio.to_thread(self._probe_machine_capacity_surface_token)
        except Exception:
            log.debug("Capacity token probe failed", exc_info=True)
            token = None
        previous = getattr(self, "_machine_capacity_observed_token", None)
        self._machine_capacity_observed_token = token
        if previous is None:
            return finish(True, "initial_token")
        try:
            token_changed = bool(token != previous)
        except Exception:
            return finish(True, "token_compare_failed")
        if token_changed:
            return finish(True, "token_changed")
        # Fail open on indeterminate tokens: a token that cannot be proven
        # unchanged must not skip the authoritative check.
        try:
            indeterminate = bool(getattr(token, "indeterminate", False))
        except Exception:
            indeterminate = True
        if token is None or indeterminate:
            return finish(True, "token_unknown")
        now_mono = time.monotonic()
        last_report = float(getattr(self, "_machine_capacity_report_mono", 0.0))
        if now_mono - last_report < CAPACITY_REPORT_POLL_SECONDS:
            return finish(False, "within_revalidation_interval")
        # Ten-second boundary with unchanged token: cheap revalidation.
        try:
            if telemetry is not None:
                telemetry["revalidation_probe_count"] = 1
            now_wall = time.time()
            (
                holds,
                override_fp,
                liveness,
            ) = await self._fetch_capacity_revalidation_snapshot(now_wall)
        except Exception:
            log.debug("Capacity revalidation snapshot failed", exc_info=True)
            return finish(True, "revalidation_failed")
        # Stash for post-build caching without a second fetch.
        self._machine_capacity_probe_snapshot = (holds, override_fp, liveness)
        if not self._capacity_time_inputs_unchanged(holds, override_fp, liveness):
            return finish(True, "time_inputs_changed")
        if self._capacity_needs_time_authoritative_check():
            return finish(True, "time_authoritative_check")
        return finish(False, "unchanged")
