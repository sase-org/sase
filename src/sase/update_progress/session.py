"""Renderer selection and the session owning model, renderer, and log sink."""

from __future__ import annotations

import time

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

from rich.console import Console

from .events import UpdateProgress
from .fanout import FanOutProgress
from .log_sink import UpdateLogSink
from .render_live import LiveTimelineRenderer
from .render_plain import PlainTimelineRenderer
from .timeline import TimelineModel

RendererKind = Literal["live", "plain", "none"]
"""Which progress surface a session uses."""


def select_renderer(
    err_console: Console, *, as_json: bool, quiet: bool, verbose: bool
) -> RendererKind:
    """Pick the progress surface for an update run.

    ``"none"`` for JSON and quiet output (the log sink still runs in every
    mode). ``"live"`` when stderr is a non-dumb terminal, ``"plain"``
    otherwise. ``verbose`` only affects how much output renderers print, not
    which surface is picked.
    """
    del verbose
    if as_json or quiet:
        return "none"
    if err_console.is_terminal and not err_console.is_dumb_terminal:
        return "live"
    return "plain"


class UpdateProgressSession:
    """Own the model, renderer, and log sink for one update run.

    Backends emit into :attr:`progress` (a fan-out over the timeline model
    and the log sink); renderers read the model. Use as a context manager so
    leftover steps are finalized and renderer threads stop.
    """

    def __init__(
        self,
        err_console: Console,
        *,
        mode: str = "",
        argv: Sequence[str] = (),
        as_json: bool = False,
        quiet: bool = False,
        verbose: bool = False,
        clock: Callable[[], float] = time.monotonic,
        log_dir: Path | None = None,
        sase_version: str | None = None,
    ) -> None:
        """Build the model, log sink, fan-out, and selected renderer."""
        self._err = err_console
        self._verbose = verbose
        self._clock = clock
        self.kind = select_renderer(
            err_console, as_json=as_json, quiet=quiet, verbose=verbose
        )
        self.model = TimelineModel(clock=clock)
        self.log_sink = UpdateLogSink(
            argv=argv, mode=mode, log_dir=log_dir, sase_version=sase_version
        )
        self._progress = FanOutProgress(self.model, self.log_sink)
        self._renderer: LiveTimelineRenderer | PlainTimelineRenderer | None
        if self.kind == "live":
            self._renderer = LiveTimelineRenderer(
                err_console, self.model, verbose=verbose, clock=clock
            )
        elif self.kind == "plain":
            self._renderer = PlainTimelineRenderer(
                err_console, self.model, verbose=verbose, clock=clock
            )
        else:
            self._renderer = None
        if self._renderer is not None:
            self._renderer.set_header(mode)

    @property
    def progress(self) -> UpdateProgress:
        """Return the fan-out sink backends emit into."""
        return self._progress

    @property
    def log_path(self) -> Path | None:
        """Return the run transcript path, or `None` when unwritable."""
        return self.log_sink.path

    @property
    def shown(self) -> bool:
        """Return True when a timeline surface is displayed."""
        return self._renderer is not None

    @property
    def degraded(self) -> bool:
        """Return True once the live renderer has fallen back to plain."""
        renderer = self._renderer
        return isinstance(renderer, LiveTimelineRenderer) and renderer.degraded

    def set_header(self, mode: str) -> None:
        """Update the install mode shown in the timeline header."""
        if self._renderer is not None:
            self._renderer.set_header(mode)

    def print_final(self, *, expand_failures: bool = True) -> None:
        """Print the static final frame (no-op when no timeline is shown)."""
        if self._renderer is not None:
            self._renderer.print_final(expand_failures=expand_failures)

    def __enter__(self) -> UpdateProgressSession:
        """Enter the active renderer and return this session."""
        if self._renderer is not None:
            self._renderer.__enter__()
        return self

    def __exit__(self, *exc: object) -> None:
        """Finalize leftover steps and exit the renderer. Never suppresses."""
        del exc
        try:
            self._progress.finalize()
        finally:
            if self._renderer is not None:
                self._renderer.__exit__()
