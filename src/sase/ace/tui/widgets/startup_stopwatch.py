"""Startup-stopwatch widget for the sase ace splash screen.

Reads the process-start timestamp from :mod:`sase.main.startup_timing` and
paints elapsed seconds at 10 Hz using the big-digit block renderer. Once the
splash signals completion the widget freezes on its final reading.
"""

from __future__ import annotations

import time
from typing import Final

from textual.timer import Timer
from textual.widgets import Static

from sase.main.startup_timing import get_process_start

from ._big_digits import render_big_digits

# If elapsed seconds exceed this threshold we switch to MM:SS.T format.
_SS_T_THRESHOLD: Final[float] = 99.9
# Tick interval for the stopwatch (10 Hz).
_TICK_INTERVAL_SECONDS: Final[float] = 0.1


def format_elapsed(seconds: float) -> str:
    """Format ``seconds`` as the big-digit stopwatch readout.

    ``SS.T`` below 100 seconds, ``MM:SS.T`` beyond. Negative values clamp to
    zero so a clock skew or very-early tick cannot produce ``-0.1``.
    Tenths are truncated toward zero (with a tiny epsilon so exact decimals
    like ``3.4`` do not fall to ``3.3`` due to float representation).
    """
    if seconds < 0:
        seconds = 0.0
    # Epsilon guards against 3.4 -> 3.39999... truncation surprises.
    total_tenths = int(seconds * 10 + 1e-9)
    if seconds <= _SS_T_THRESHOLD:
        secs = total_tenths // 10
        tenths = total_tenths % 10
        return f"{secs:02d}.{tenths}"
    minutes = total_tenths // 600
    remainder = total_tenths - minutes * 600
    secs = remainder // 10
    tenths = remainder % 10
    return f"{minutes:02d}:{secs:02d}.{tenths}"


class StartupStopwatch(Static):
    """Renders the elapsed-since-process-start time as big-digit blocks."""

    DEFAULT_CSS = ""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._update_timer: Timer | None = None
        self._frozen: bool = False
        self._frozen_value: str | None = None

    def on_mount(self) -> None:
        """Begin ticking at 10 Hz and paint the first frame immediately."""
        self._tick()
        self._update_timer = self.set_interval(
            _TICK_INTERVAL_SECONDS, self._tick, name="startup-stopwatch-tick"
        )

    def _current_elapsed(self) -> float:
        return time.perf_counter() - get_process_start()

    def _tick(self) -> None:
        if self._frozen:
            return
        elapsed = self._current_elapsed()
        rendered = render_big_digits(format_elapsed(elapsed))
        self.update(rendered)

    def freeze(self, elapsed: float | None = None) -> str:
        """Stop ticking and paint a final frame. Returns the final readout.

        If ``elapsed`` is ``None`` the current elapsed value is used.
        """
        if elapsed is None:
            elapsed = self._current_elapsed()
        readout = format_elapsed(elapsed)
        self._frozen = True
        self._frozen_value = readout
        if self._update_timer is not None:
            self._update_timer.stop()
            self._update_timer = None
        self.update(render_big_digits(readout))
        return readout

    @property
    def frozen_value(self) -> str | None:
        """The final readout after :meth:`freeze`, else ``None``."""
        return self._frozen_value
