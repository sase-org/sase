"""Startup splash screen for the sase ace TUI.

Shows a big-digit stopwatch measuring time since process start, plus live
milestone checkmarks for ChangeSpecs / Agents / AXE. Auto-dismisses once all
three milestones report ready (honouring a minimum on-screen time so fast
paths do not flash), and a single keystroke also dismisses early.
"""

from __future__ import annotations

import time
from typing import Final

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Static

from ..widgets.startup_stopwatch import StartupStopwatch, format_elapsed

# Minimum on-screen time (seconds) before we allow the splash to freeze +
# auto-dismiss. Keeps the splash from flashing on warm-cache startups.
MINIMUM_DISPLAY_SECONDS: Final[float] = 0.3

# Delay after freeze before the splash auto-dismisses (seconds).
FREEZE_HOLD_SECONDS: Final[float] = 0.45

# Milestone label text.
_MILESTONES: Final[tuple[tuple[str, str], ...]] = (
    ("changespecs", "ChangeSpecs"),
    ("agents", "Agents"),
    ("axe", "AXE"),
)

_CHECK: Final[str] = "✓"
_ELLIPSIS_FRAMES: Final[tuple[str, ...]] = (".  ", ".. ", "...")


class StartupSplashScreen(ModalScreen[None]):
    """Full-screen splash with big-digit stopwatch + milestone checklist."""

    BINDINGS = [
        ("escape", "skip", "Skip"),
        ("q", "skip", "Skip"),
        ("space", "skip", "Skip"),
        ("enter", "skip", "Skip"),
    ]

    def __init__(self, *, process_start: float) -> None:
        super().__init__()
        self._process_start = process_start
        self._shown_at: float | None = None
        self._ready_flags: dict[str, bool] = {key: False for key, _ in _MILESTONES}
        self._dismissed: bool = False
        self._frozen: bool = False
        self._freeze_timer: Timer | None = None
        self._dismiss_timer: Timer | None = None
        self._ellipsis_timer: Timer | None = None
        self._ellipsis_frame: int = 0

    # ----------------------------------------------------------------- compose

    def compose(self) -> ComposeResult:
        with Vertical(id="splash-body"):
            yield Static("starting sase ace", id="splash-title")
            yield StartupStopwatch(id="splash-stopwatch")
            yield Static("starting sase ace…", id="splash-subtitle")
            yield Static(self._build_milestones(), id="splash-milestones")
            yield Static("press any key to skip", id="splash-hint")

    def on_mount(self) -> None:
        self._shown_at = time.perf_counter()
        self._ellipsis_timer = self.set_interval(
            0.4, self._advance_ellipsis, name="splash-ellipsis"
        )

    # ----------------------------------------------------------- milestone API

    def mark_changespecs_ready(self) -> None:
        self._mark_ready("changespecs")

    def mark_agents_ready(self) -> None:
        self._mark_ready("agents")

    def mark_axe_ready(self) -> None:
        self._mark_ready("axe")

    def _mark_ready(self, key: str) -> None:
        if self._dismissed:
            return
        if self._ready_flags.get(key):
            return
        self._ready_flags[key] = True
        self._refresh_milestones()
        if all(self._ready_flags.values()):
            self._schedule_completion()

    # --------------------------------------------------------------- rendering

    def _build_milestones(self) -> Text:
        text = Text()
        frame = _ELLIPSIS_FRAMES[self._ellipsis_frame % len(_ELLIPSIS_FRAMES)]
        for i, (key, label) in enumerate(_MILESTONES):
            if self._ready_flags[key]:
                text.append(f"  {_CHECK}  ", style="bold green")
            else:
                text.append(f"  {frame}  ", style="dim")
            text.append(label)
            if i < len(_MILESTONES) - 1:
                text.append("\n")
        return text

    def _refresh_milestones(self) -> None:
        try:
            panel = self.query_one("#splash-milestones", Static)
        except Exception:
            return
        panel.update(self._build_milestones())

    def _advance_ellipsis(self) -> None:
        if self._dismissed or self._frozen:
            return
        self._ellipsis_frame += 1
        self._refresh_milestones()

    # ---------------------------------------------------------- completion path

    def _schedule_completion(self) -> None:
        if self._frozen or self._dismissed:
            return
        now = time.perf_counter()
        shown = self._shown_at if self._shown_at is not None else now
        elapsed_on_screen = now - shown
        delay = max(0.0, MINIMUM_DISPLAY_SECONDS - elapsed_on_screen)
        if delay <= 0:
            self._do_freeze()
            return
        self._freeze_timer = self.set_timer(
            delay, self._do_freeze, name="splash-freeze"
        )

    def _do_freeze(self) -> None:
        if self._frozen or self._dismissed:
            return
        self._frozen = True
        elapsed = time.perf_counter() - self._process_start
        try:
            stopwatch = self.query_one("#splash-stopwatch", StartupStopwatch)
            stopwatch.freeze(elapsed)
        except Exception:
            pass
        try:
            subtitle = self.query_one("#splash-subtitle", Static)
            subtitle.update(f"ready in {format_elapsed(elapsed)}s")
        except Exception:
            pass
        self.add_class("-ready")
        if self._ellipsis_timer is not None:
            self._ellipsis_timer.stop()
            self._ellipsis_timer = None
        self._dismiss_timer = self.set_timer(
            FREEZE_HOLD_SECONDS, self._do_dismiss, name="splash-dismiss"
        )

    def _do_dismiss(self) -> None:
        if self._dismissed:
            return
        self._dismissed = True
        try:
            self.dismiss(None)
        except Exception:
            pass

    # ------------------------------------------------------------- user skip

    def action_skip(self) -> None:
        """Skip the splash in response to a dismissal key."""
        if self._dismissed:
            return
        self._dismissed = True
        for timer in (self._freeze_timer, self._dismiss_timer, self._ellipsis_timer):
            if timer is not None:
                timer.stop()
        self._freeze_timer = None
        self._dismiss_timer = None
        self._ellipsis_timer = None
        try:
            self.dismiss(None)
        except Exception:
            pass
