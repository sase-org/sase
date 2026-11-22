"""Idle gate for the full-GC policy: duty bound, thresholds, and due checks."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sase.ace.tui.util.gc_telemetry import latest_rss_bytes

from ._gc_policy_common import safe_probe
from ._gc_policy_config import (
    BACKSTOP_QUIET_S,
    COST_DUE_MIN_INTERVAL_S,
    DUTY_FACTOR,
    FULL_BACKSTOP_S,
    FULL_GENERATION,
    GEN1_DUE_COUNT,
    IDLE_QUIET_S,
    MAX_DUTY_DELAY_S,
    MIN_FULL_INTERVAL_S,
    NONCLASSIC_DUE_S,
    RAISED_THRESHOLD2,
    RSS_GROWTH_BACKSTOP_BYTES,
    THRESHOLD_RAISED,
    THRESHOLD_UNSUPPORTED,
)
from ._gc_policy_cost import PolicyCostMixin


def _classic_thresholds(collector: Any) -> tuple[int, int, int] | None:
    """Return the ``(t0, t1, t2)`` thresholds, or ``None`` elsewhere.

    Only the classic three-generation shape qualifies: a three-tuple of
    non-negative ints. Any other collector shape leaves thresholds alone
    and the idle collector still runs with a time-based due check.
    """
    try:
        raw = tuple(collector.get_threshold())
    except Exception:
        return None
    if len(raw) != 3:
        return None
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in raw):
        return None
    return (int(raw[0]), int(raw[1]), int(raw[2]))


class PolicyGateMixin(PolicyCostMixin):
    """Eligibility half of :class:`GCPolicy`: duty, thresholds, and idle gate."""

    _monotonic: Callable[[], float]
    _installed_mono: float
    _last_input_mono: Callable[[], float]
    _prompt_active: Callable[[], bool]
    _navigating: Callable[[], bool]
    _modal_input_active: Callable[[], bool]
    _loads_done: Callable[[], bool]
    _startup_freeze_mono: float | None
    _own_last_full_mono: float | None
    _rss_at_last_full: int | None
    _last_full_pause_s: float | None
    threshold_policy: str
    _original_threshold: tuple[int, int, int] | None

    def duty_floor_s(self, *, cost_due: bool = False) -> float:
        """Minimum gap after the last full collection (duty-cycle bound).

        The next full collection runs no sooner than ``last_pause *
        DUTY_FACTOR`` after the last one, clamped to ``MAX_DUTY_DELAY_S``
        and floored at ``MIN_FULL_INTERVAL_S``. Unknown pause (no own
        collection yet) degrades to the floor. A cost-due sweep (the
        estimate nears the pause budget) keeps the duty factor but relaxes
        the floor to ``COST_DUE_MIN_INTERVAL_S``: waiting would only grow
        the pause.
        """
        floor = COST_DUE_MIN_INTERVAL_S if cost_due else MIN_FULL_INTERVAL_S
        pause = self._last_full_pause_s
        if pause is None:
            return floor
        try:
            pause_f = float(pause)
        except Exception:
            return floor
        if pause_f < 0.0:
            pause_f = 0.0
        return max(floor, min(pause_f * DUTY_FACTOR, MAX_DUTY_DELAY_S))

    def next_full_due_in_s(self, now_mono: float | None = None) -> float:
        """Seconds until the duty floor lets the next full collection run."""
        now = self._monotonic() if now_mono is None else now_mono
        last_full = self.combined_last_full_mono()
        if last_full is None:
            return 0.0
        try:
            remaining = (float(last_full) + self.duty_floor_s()) - float(now)
        except Exception:
            return 0.0
        return max(0.0, remaining)

    def heartbeat_fields(self) -> dict[str, Any]:
        """Extra heartbeat fields published via ``register_heartbeat_provider``."""
        fields: dict[str, Any] = {"threshold_policy": self.threshold_policy}
        try:
            fields["next_full_due_in_s"] = round(self.next_full_due_in_s(), 3)
            if self._last_full_pause_s is not None:
                fields["last_full_pause_s"] = round(float(self._last_full_pause_s), 6)
        except Exception:
            pass
        return fields

    def apply_thresholds(self) -> str:
        """Raise ``threshold2`` on the classic collector; report the policy."""
        classic = _classic_thresholds(self._collector)
        if classic is None:
            self.threshold_policy = THRESHOLD_UNSUPPORTED
            return self.threshold_policy
        t0, t1, _t2 = classic
        self._original_threshold = classic
        try:
            self._collector.set_threshold(t0, t1, RAISED_THRESHOLD2)
        except Exception:
            self._original_threshold = None
            self.threshold_policy = THRESHOLD_UNSUPPORTED
            return self.threshold_policy
        self.threshold_policy = THRESHOLD_RAISED
        return self.threshold_policy

    def restore_thresholds(self) -> None:
        """Restore the thresholds saved by :meth:`apply_thresholds`."""
        original, self._original_threshold = self._original_threshold, None
        if original is None:
            return
        try:
            self._collector.set_threshold(*original)
        except Exception:
            pass

    def combined_last_full_mono(self) -> float | None:
        """End time of the latest full collection from any trigger."""
        candidates = [self._own_last_full_mono]
        try:
            candidates.append(self._recorder.last_full_collection_mono())
        except Exception:
            pass
        known = [
            value
            for value in candidates
            if isinstance(value, (int, float)) and value >= 0
        ]
        return max(known) if known else None

    def collection_due(self, now_mono: float, last_full_mono: float | None) -> bool:
        """Return True when enough gen-1 work has piled up for a full sweep."""
        try:
            if int(self._recorder.gen1_since_last_full()) >= GEN1_DUE_COUNT:
                return True
        except Exception:
            pass
        classic = _classic_thresholds(self._collector)
        if classic is not None:
            try:
                counts = tuple(self._collector.get_count())
                if int(counts[FULL_GENERATION]) >= GEN1_DUE_COUNT:
                    return True
            except Exception:
                pass
        if last_full_mono is None:
            if classic is not None:
                return False
            started = self._startup_freeze_mono
            return started is None or now_mono - started >= NONCLASSIC_DUE_S
        return classic is None and now_mono - last_full_mono >= NONCLASSIC_DUE_S

    def idle_gate(self, now_mono: float) -> tuple[bool, str]:
        """Check the idle gate, returning ``(passes, tag)``.

        The tag names the trigger a passing collection would run under:
        ``"idle"``, or a relaxed ``"backstop"`` / ``"rss_backstop"`` once
        the 5-minute or RSS-growth backstop is tripped. A sweep whose
        estimate nears the pause budget is due without the gen-1 count and
        under the relaxed cost-due duty floor.
        """
        if not safe_probe(self._loads_done, False):
            return (False, "idle")
        last_full = self.combined_last_full_mono()
        relaxed = False
        tag = "idle"
        if last_full is not None and now_mono - last_full >= FULL_BACKSTOP_S:
            relaxed = True
            tag = "backstop"
        else:
            rss_now = latest_rss_bytes()
            baseline = self._rss_at_last_full
            if (
                rss_now is not None
                and baseline is not None
                and rss_now - baseline > RSS_GROWTH_BACKSTOP_BYTES
            ):
                relaxed = True
                tag = "rss_backstop"
        quiet = BACKSTOP_QUIET_S if relaxed else IDLE_QUIET_S
        if self._input_idle_s(now_mono) < quiet:
            return (False, tag)
        if safe_probe(self._prompt_active, False):
            return (False, tag)
        if safe_probe(self._navigating, False):
            return (False, tag)
        if safe_probe(self._modal_input_active, False):
            return (False, tag)
        cost_due = self._cost_due(now_mono)
        floor = self.duty_floor_s(cost_due=cost_due)
        if last_full is not None and now_mono - last_full < floor:
            return (False, tag)
        if not cost_due and not self.collection_due(now_mono, last_full):
            return (False, tag)
        return (True, tag)

    def _input_idle_s(self, now_mono: float) -> float:
        """Measure quiet time from the later of last input and policy startup."""
        raw = safe_probe(self._last_input_mono, 0.0)
        try:
            last_input = float(raw)
        except Exception:
            last_input = 0.0
        reference = last_input if last_input > 0.0 else self._installed_mono
        if self._startup_freeze_mono is not None:
            reference = max(reference, self._startup_freeze_mono)
        return max(0.0, now_mono - reference)

    def _startup_freeze_gate(self, now_mono: float) -> bool:
        """Freeze the settled startup heap on an ordinary idle window."""
        if not safe_probe(self._loads_done, False):
            return False
        if self._input_idle_s(now_mono) < IDLE_QUIET_S:
            return False
        return not (
            safe_probe(self._prompt_active, False)
            or safe_probe(self._navigating, False)
            or safe_probe(self._modal_input_active, False)
        )
