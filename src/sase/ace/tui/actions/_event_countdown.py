"""Countdown timer handlers for the ACE TUI."""

from __future__ import annotations

import time

from ._event_base import EventHandlersBase


class EventCountdownMixin(EventHandlersBase):
    """Mixin providing countdown timer callbacks."""

    def _on_countdown_tick(self) -> None:
        """Countdown tick handler called every second."""
        now_mono = time.monotonic()
        # Deferred Tier 2 reconcile: scheduled lazily once input is quiet
        # to keep the ~2.7 s full-history scan out of the startup path
        # (see _maybe_trigger_input_quiet_tier2_reconcile).
        try:
            self._maybe_trigger_input_quiet_tier2_reconcile(  # type: ignore[attr-defined]
                now_mono=now_mono
            )
        except AttributeError:
            pass
        self._countdown_remaining -= 1
        if self._countdown_remaining < 0:
            self._countdown_remaining = self.refresh_interval
        if self.current_tab == "artifacts":
            self._update_info_panel()  # type: ignore[attr-defined]
        elif self.current_tab == "agents":
            # The cosmetic countdown/runtime repaint and STARTING-marker poll
            # are not urgent enough to contend with a j/k burst. In
            # particular, patching every live row on the one-second boundary
            # produces a periodic key-to-paint outlier on populated lists.
            # The next tick catches all three surfaces up once navigation is
            # quiet; the logical countdown still advances above.
            if not self._nav_gate.is_navigating(now_mono=now_mono):
                self._update_agents_info_panel()  # type: ignore[attr-defined]
                self._patch_agent_runtime_rows()  # type: ignore[attr-defined]
                self._poll_starting_agent_transitions()  # type: ignore[attr-defined]
        else:  # axe
            self._update_axe_info_panel()  # type: ignore[attr-defined]
            # Stream live output for an active chop run without waiting for
            # the slower full-fleet refresh interval.
            self._axe_live_tick()  # type: ignore[attr-defined]

    def _record_input_event(self) -> None:
        """Record input for delayed background work.

        Called from on_key() for normal bindings and directly from
        priority-binding actions (e.g. tab switching) that bypass on_key().
        """
        self._last_input_mono = time.monotonic()
