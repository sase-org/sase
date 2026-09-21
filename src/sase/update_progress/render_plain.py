"""Append-only plain timeline renderer for piped output."""

from __future__ import annotations

import threading
import time

from collections.abc import Callable

from rich.console import Console
from rich.text import Text

from .events import TERMINAL_STATUSES
from .styles import FINAL_GLYPH, STATUS_STYLE, format_duration, format_stamp
from .timeline import StepSnapshot, TimelineModel, elapsed, walk

_START_DELAY = 2.0
"""Seconds a step runs before its start line prints (keeps fast runs terse)."""

_TICK_INTERVAL = 1.0
"""Seconds between ticker passes."""

_FAILURE_TAIL = 20
"""Output lines expanded under a failed step."""


class PlainTimelineRenderer:
    """Line-oriented renderer: one append-only line per step event.

    A lightweight ticker thread prints a ``→`` start line once a step has
    been running for 2 s, so a hang is always visible without doubling every
    line. Every pass is also available synchronously via :meth:`poll`, which
    is what tests drive under a fake clock.
    """

    def __init__(
        self,
        console: Console,
        model: TimelineModel,
        *,
        verbose: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Bind to ``console`` and ``model`` without printing anything yet."""
        self._console = console
        self._model = model
        self._verbose = verbose
        self._clock = clock
        self._header_mode = ""
        self._t0: float | None = None
        self._announced: set[str] = set()
        self._reported: set[str] = set()
        self._seen_tail: dict[str, int] = {}
        self._stop = threading.Event()
        self._ticker: threading.Thread | None = None
        self._poll_lock = threading.Lock()
        self._finalized = False

    def set_header(self, mode: str) -> None:
        """Set the install mode shown in the header line."""
        self._header_mode = mode

    def header_line(self) -> str:
        """Return the header line printed on entry."""
        if self._header_mode:
            return f"sase update · {self._header_mode}"
        return "sase update"

    def __enter__(self) -> PlainTimelineRenderer:
        """Print the header and start the ticker thread."""
        self._console.print(Text(self.header_line(), style="bold"))
        self.attach()
        return self

    def __exit__(self, *exc: object) -> None:
        """Flush pending lines and stop the ticker thread."""
        del exc
        try:
            self.poll()
        finally:
            self.detach()

    def attach(self) -> None:
        """Start the ticker thread without printing a header.

        Used when a degraded live renderer hands over mid-run.
        """
        if self._t0 is None:
            self._t0 = self._clock()
        if self._ticker is None:
            self._stop.clear()
            self._ticker = threading.Thread(
                target=self._tick, name="plain-timeline-ticker", daemon=True
            )
            self._ticker.start()

    def detach(self) -> None:
        """Stop the ticker thread."""
        self._stop.set()
        ticker, self._ticker = self._ticker, None
        if ticker is not None and ticker is not threading.current_thread():
            ticker.join(timeout=5.0)

    def print_final(self, *, expand_failures: bool = True) -> None:
        """Flush every unreported finish line (with failure tails)."""
        del expand_failures  # Plain always expands: tails print on finish.
        self.detach()
        if self._finalized:
            return
        self.poll()
        self._finalized = True

    def _tick(self) -> None:
        while not self._stop.wait(_TICK_INTERVAL):
            try:
                self.poll()
            except Exception:  # noqa: BLE001 - progress must never fail a run
                pass

    def poll(self) -> None:
        """Print newly due start lines, verbose lines, and finish lines once."""
        if self._finalized:
            return
        with self._poll_lock:
            self._poll_locked()

    def _poll_locked(self) -> None:
        if self._t0 is None:
            self._t0 = self._clock()
        t0 = self._t0
        now = self._clock()
        stamp = format_stamp(now - t0)
        for _depth, row in walk(self._model.snapshot()):
            if self._verbose:
                omitted, new_lines = _new_verbose_lines(
                    row, self._seen_tail.get(row.id, 0)
                )
                if omitted:
                    self._console.print(
                        Text.assemble(
                            ("    ", ""),
                            ("│ ", "dim"),
                            Text(
                                f"… {omitted} lines omitted (see full log)",
                                style="dim",
                            ),
                        )
                    )
                for line in new_lines:
                    self._console.print(
                        Text.assemble(("    ", ""), ("│ ", "dim"), line)
                    )
                self._seen_tail[row.id] = row.lines_total
            if row.status == "running":
                if row.id not in self._announced and elapsed(row, now) >= _START_DELAY:
                    self._console.print(Text(f"[{stamp}] → {row.title}"))
                    self._announced.add(row.id)
            elif row.status in TERMINAL_STATUSES and row.id not in self._reported:
                self._reported.add(row.id)
                glyph = FINAL_GLYPH[row.status]
                style = STATUS_STYLE[row.status]
                line = f"[{stamp}] {glyph} {row.title}"
                if row.detail:
                    line += f" — {row.detail}"
                if row.started_at is not None:
                    line += f" ({format_duration(elapsed(row, now))})"
                self._console.print(Text(line, style=style))
                if row.status == "failed":
                    for tail_line in row.tail[-_FAILURE_TAIL:]:
                        self._console.print(
                            Text.assemble(("    ", ""), ("│ ", "dim"), tail_line)
                        )


def _new_verbose_lines(row: StepSnapshot, emitted: int) -> tuple[int, list[str]]:
    """Return ``(omitted, lines)`` for verbose streaming by line counter."""
    total = row.lines_total
    if total <= emitted:
        return 0, []
    tail = row.tail
    tail_start = total - len(tail)
    first_available = max(emitted, tail_start)
    omitted = first_available - emitted
    return omitted, list(tail[first_available - tail_start :])
