"""Focused tests for the ACE visual render-convergence barrier."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    _pending_visual_work,
    wait_for_visual_idle,
)


class _Worker:
    name = "delayed-paint"
    description = "delayed visual paint"

    def __init__(self) -> None:
        self.is_running = True


class _App:
    def __init__(
        self,
        workers: tuple[_Worker, ...] = (),
        timers: tuple[Any, ...] = (),
    ) -> None:
        self.workers = workers
        self.screen_stack: tuple[Any, ...] = ()
        self._timers = timers


class _Task:
    def done(self) -> bool:
        return False


class _Timer:
    _repeat = 0

    def __init__(self, name: str, interval: float) -> None:
        self.name = name
        self._interval = interval
        self._task = _Task()


class _DelayedPaintPage:
    def __init__(self) -> None:
        self.worker = _Worker()
        self.app = _App((self.worker,))
        self.pause_count = 0
        self.export_count = 0
        self.frame = "mounting"

    async def pause(self) -> None:
        await asyncio.sleep(0)
        self.pause_count += 1
        if self.pause_count == 4:
            self.frame = "fully-painted"
            self.worker.is_running = False

    def export_svg(self, title: str | None = None, simplify: bool = True) -> str:
        del title, simplify
        self.export_count += 1
        return self.frame


class _ChangingPage:
    def __init__(self) -> None:
        self.app = _App()
        self.pause_count = 0
        self.export_count = 0

    async def pause(self) -> None:
        await asyncio.sleep(0)
        self.pause_count += 1

    def export_svg(self, title: str | None = None, simplify: bool = True) -> str:
        del title, simplify
        self.export_count += 1
        # The first two frames appear stable, then a delayed layout/paint lands.
        return "shell" if self.export_count < 3 else "complete"


class _NeverStablePage(_ChangingPage):
    def export_svg(self, title: str | None = None, simplify: bool = True) -> str:
        del title, simplify
        self.export_count += 1
        return f"frame-{self.export_count % 2}"


@pytest.mark.asyncio
async def test_visual_idle_waits_for_worker_and_three_converged_frames() -> None:
    page = _DelayedPaintPage()

    await wait_for_visual_idle(cast(Any, page), timeout=0.5)

    assert page.pause_count >= 6
    assert page.export_count == 3
    assert page.frame == "fully-painted"


@pytest.mark.asyncio
async def test_visual_idle_observes_delayed_paint_before_converging() -> None:
    page = _ChangingPage()

    await wait_for_visual_idle(cast(Any, page), timeout=0.5)

    assert page.export_count == 5


@pytest.mark.asyncio
async def test_visual_idle_timeout_reports_recent_render_state() -> None:
    page = _NeverStablePage()

    with pytest.raises(
        AssertionError,
        match=r"render convergence.*stable_frames=.*frame_digests=",
    ):
        await wait_for_visual_idle(cast(Any, page), timeout=0.04)


def test_visual_idle_waits_for_short_timers_but_not_surface_lifetimes() -> None:
    page = _ChangingPage()
    page.app = _App(
        timers=(
            _Timer("input-validation", 0.15),
            _Timer("toast-expiry", 10.0),
        )
    )

    _debouncers, _workers, timers = _pending_visual_work(cast(Any, page))

    assert timers == ["input-validation"]
