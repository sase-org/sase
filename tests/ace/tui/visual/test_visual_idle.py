"""Focused tests for the ACE visual render-convergence barrier."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Input, TextArea

from sase.ace.testing import AcePage
from sase.ace.tui import AceApp
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    _pending_visual_work,
    assert_visual_frame_converged,
    patch_startup_loaders,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_png_snapshot_waits import _disable_cursor_blink

pytestmark = pytest.mark.visual


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
        animator: Any = None,
    ) -> None:
        self.workers = workers
        self.screen_stack: tuple[Any, ...] = ()
        self._timers = timers
        self.animator = animator


class _Task:
    def done(self) -> bool:
        return False


class _Timer:
    _repeat = 0

    def __init__(self, name: str, interval: float) -> None:
        self.name = name
        self._interval = interval
        self._task = _Task()


class _Animator:
    def __init__(
        self,
        *,
        animations: dict[tuple[int, str], object] | None = None,
        scheduled: dict[tuple[int, str], object] | None = None,
    ) -> None:
        self._animations = animations or {}
        self._scheduled = scheduled or {}


class _DelayedPaintPage:
    def __init__(self) -> None:
        self.worker = _Worker()
        self.app = _App((self.worker,))
        self.pause_count = 0
        self.export_count = 0
        self.frame = "mounting"

    async def pause(self, delay: float | None = None) -> None:
        del delay
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
        self.pause_delays: list[float | None] = []
        self.export_count = 0

    async def pause(self, delay: float | None = None) -> None:
        self.pause_delays.append(delay)
        await asyncio.sleep(0)
        self.pause_count += 1

    def export_svg(self, title: str | None = None, simplify: bool = True) -> str:
        del title, simplify
        self.export_count += 1
        # The first two frames appear stable, then a delayed layout/paint lands.
        return "shell" if self.export_count < 3 else "complete"


class _StarvedPaintPage(_ChangingPage):
    def __init__(self) -> None:
        super().__init__()
        self.frame = "shell"

    async def pause(self, delay: float | None = None) -> None:
        await super().pause(delay)
        # Model work that only advances when the harness performs a full
        # scheduler/CPU-idle pause. Zero-delay queue drains leave the shell
        # unchanged and used to produce a false convergence result.
        if delay is None and self.pause_count >= 3:
            self.frame = "complete"

    def export_svg(self, title: str | None = None, simplify: bool = True) -> str:
        del title, simplify
        self.export_count += 1
        return self.frame


class _AnimatingPage(_ChangingPage):
    def __init__(self) -> None:
        super().__init__()
        self.animator = _Animator(animations={(17, "scroll_y"): object()})
        self.app = _App(animator=self.animator)
        self.exports_before_animation_finished: int | None = None

    async def pause(self, delay: float | None = None) -> None:
        await super().pause(delay)
        if self.pause_count == 4:
            self.exports_before_animation_finished = self.export_count
            self.animator._animations.clear()


class _NeverStablePage(_ChangingPage):
    def export_svg(self, title: str | None = None, simplify: bool = True) -> str:
        del title, simplify
        self.export_count += 1
        return f"frame-{self.export_count % 2}"


class _SemanticPage(_ChangingPage):
    def __init__(self) -> None:
        super().__init__()
        self.ready = False

    async def pause(self, delay: float | None = None) -> None:
        await super().pause(delay)
        if self.pause_count >= 3:
            self.ready = True

    def export_svg(self, title: str | None = None, simplify: bool = True) -> str:
        del title, simplify
        self.export_count += 1
        return "<svg>expected sentinel</svg>" if self.ready else "<svg>shell</svg>"


@pytest.mark.asyncio
async def test_visual_idle_waits_for_worker_and_five_converged_frames() -> None:
    page = _DelayedPaintPage()

    await wait_for_visual_idle(cast(Any, page), timeout=0.5)

    assert page.pause_count >= 8
    assert page.export_count == 5
    assert page.frame == "fully-painted"


@pytest.mark.asyncio
async def test_visual_snapshots_disable_animations_on_running_app() -> None:
    async with AcePage() as page:
        assert page.app.animation_level == "none"


@pytest.mark.asyncio
async def test_visual_startup_patch_disables_prompt_catalog_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage() as page:
        page.app._schedule_prompt_catalog_rebuild(reason="assist_cache_miss")
        await page.pause()

        assert page.app._prompt_catalog_rebuild_in_flight is False
        assert page.app._prompt_catalog_rebuild_pending is False
        running_worker_names = [
            str(getattr(worker, "name", worker))
            for worker in page.app.workers
            if bool(getattr(worker, "is_running", False))
        ]
        assert not any(
            name.startswith("prompt-catalog:") for name in running_worker_names
        )
        assert AceApp._schedule_prompt_catalog_rebuild.__name__ == (
            "_fake_prompt_catalog_rebuild"
        )


@pytest.mark.asyncio
async def test_visual_idle_observes_delayed_paint_before_converging() -> None:
    page = _ChangingPage()

    await wait_for_visual_idle(cast(Any, page), timeout=0.5)

    assert page.export_count == 7
    assert page.pause_delays
    assert set(page.pause_delays) == {None}


@pytest.mark.asyncio
async def test_visual_idle_requires_scheduler_progress_under_starvation() -> None:
    page = _StarvedPaintPage()

    await wait_for_visual_idle(cast(Any, page), timeout=0.5)

    assert page.frame == "complete"
    assert page.export_count >= 7
    assert set(page.pause_delays) == {None}


@pytest.mark.asyncio
async def test_visual_idle_waits_for_in_flight_animation() -> None:
    page = _AnimatingPage()

    await wait_for_visual_idle(cast(Any, page), timeout=0.5)

    assert page.pause_count >= 8
    assert page.exports_before_animation_finished == 0
    assert page.export_count == 7


@pytest.mark.asyncio
async def test_visual_idle_records_the_exact_converged_capture_frame() -> None:
    page = _ChangingPage()

    await wait_for_visual_idle(cast(Any, page), timeout=0.5)

    assert_visual_frame_converged(cast(Any, page))
    page.export_count = 1
    with pytest.raises(
        AssertionError,
        match=r"frame changed after visual convergence.*converged_digest=",
    ):
        assert_visual_frame_converged(cast(Any, page))


def test_visual_capture_requires_a_convergence_barrier() -> None:
    page = _ChangingPage()

    with pytest.raises(
        AssertionError,
        match=r"requires wait_for_visual_idle",
    ):
        assert_visual_frame_converged(cast(Any, page))


@pytest.mark.asyncio
async def test_visual_idle_timeout_reports_recent_render_state() -> None:
    page = _NeverStablePage()

    with pytest.raises(
        AssertionError,
        match=r"render convergence.*stable_frames=.*frame_digests=",
    ):
        await wait_for_visual_idle(cast(Any, page), timeout=0.04)


@pytest.mark.asyncio
async def test_wait_for_state_polls_until_semantic_state_is_ready() -> None:
    page = _SemanticPage()

    await wait_for_state(
        cast(Any, page),
        lambda: page.ready,
        description="semantic fixture readiness",
        timeout=0.5,
    )

    assert page.pause_count == 3


@pytest.mark.asyncio
async def test_wait_for_svg_contains_polls_exported_frame() -> None:
    page = _SemanticPage()

    await wait_for_svg_contains(cast(Any, page), "expected sentinel", timeout=0.5)

    assert page.ready


@pytest.mark.asyncio
async def test_wait_for_svg_contains_timeout_names_sentinel_and_last_frame() -> None:
    page = _ChangingPage()

    with pytest.raises(
        AssertionError,
        match=r"SVG sentinel 'missing'.*last_frame_digest=.*last_frame_svg=",
    ):
        await wait_for_svg_contains(cast(Any, page), "missing", timeout=0.02)


def test_visual_idle_waits_for_short_timers_but_not_surface_lifetimes() -> None:
    page = _ChangingPage()
    page.app = _App(
        timers=(
            _Timer("input-validation", 0.15),
            _Timer("toast-expiry", 10.0),
        )
    )

    _debouncers, _workers, timers, _animations = _pending_visual_work(cast(Any, page))

    assert timers == ["input-validation"]


def test_pending_visual_work_reports_running_and_scheduled_animations() -> None:
    animator = _Animator(
        animations={(17, "scroll_y"): object()},
        scheduled={(23, "opacity"): object()},
    )
    page = _ChangingPage()
    page.app = _App(animator=animator)

    _debouncers, _workers, _timers, animations = _pending_visual_work(cast(Any, page))

    assert animations == [
        "running:(17, 'scroll_y')",
        "scheduled:(23, 'opacity')",
    ]


class _CursorCacheApp(App[None]):
    """Tiny app that can hold a focused caret and a blurred editor cache."""

    CSS = "TextArea { width: 40; height: 5; } Input { height: 3; }"

    def compose(self) -> ComposeResult:
        yield TextArea(
            "hello world",
            id="editor",
            show_line_numbers=False,
            highlight_cursor_line=False,
        )
        yield Input(id="other")
        yield Button("OK", id="ok")


class _CursorCachePage:
    def __init__(self, app: App[None], pilot: Any) -> None:
        self.app = app
        self._pilot = pilot

    async def pause(self, delay: float | None = None) -> None:
        if delay is None:
            await self._pilot.pause()
        else:
            await self._pilot.pause(delay)

    def export_svg(self, title: str | None = None, simplify: bool = True) -> str:
        return self.app.export_screenshot(title=title, simplify=simplify)


def _copy_line_cache(text_area: TextArea) -> dict[object, object]:
    return {key: text_area._line_cache[key] for key in text_area._line_cache.keys()}


def _restore_line_cache(text_area: TextArea, snapshot: dict[object, object]) -> None:
    text_area._line_cache.clear()
    for key, strip in snapshot.items():
        text_area._line_cache[key] = strip


def _textarea_caret_cells(text_area: TextArea) -> list[str]:
    theme = text_area._theme
    cursor_style = None if theme is None else theme.cursor_style
    if cursor_style is None or cursor_style.bgcolor is None:
        return []
    hits: list[str] = []
    for segment in text_area.render_line(0)._segments:
        style = segment.style
        if style is not None and style.bgcolor == cursor_style.bgcolor:
            hits.append(segment.text)
    return hits


def _focused_only_disable_cursor_blink(page: Any) -> bool:
    """Pre-repair helper: invalidate only the currently focused widget."""
    from textual.widgets import Input, TextArea

    focused_cursor_refreshed = False
    for screen in page.app.screen_stack:
        for widget in screen.walk_children():
            if not isinstance(widget, (Input, TextArea)):
                continue
            widget.cursor_blink = False
            widget._pause_blink(visible=widget.has_focus)
            if widget.has_focus:
                if isinstance(widget, TextArea):
                    widget._line_cache.clear()
                widget.refresh()
                focused_cursor_refreshed = True
    return focused_cursor_refreshed


async def _paint_focused_editor_cache(
    editor: TextArea, pilot: Any
) -> dict[object, object]:
    editor.focus()
    editor.cursor_blink = False
    editor._pause_blink(visible=True)
    editor._line_cache.clear()
    await pilot.pause()
    editor.render_line(0)
    snapshot = _copy_line_cache(editor)
    assert _textarea_caret_cells(editor)
    return snapshot


@pytest.mark.asyncio
async def test_visual_idle_clears_stale_cursor_on_blurred_textarea() -> None:
    app = _CursorCacheApp()
    async with app.run_test(size=(40, 16)) as pilot:
        editor = app.query_one("#editor", TextArea)
        ok_button = app.query_one("#ok", Button)
        stale_cursor_cache = await _paint_focused_editor_cache(editor, pilot)

        ok_button.focus()
        await pilot.pause()
        assert not editor.has_focus
        _restore_line_cache(editor, stale_cursor_cache)
        assert _textarea_caret_cells(editor)

        page = _CursorCachePage(app, pilot)
        # Confirm-dialog style: a Button holds focus, so the old
        # focused-only invalidation never clears the background editor.
        assert _focused_only_disable_cursor_blink(page) is False
        assert _textarea_caret_cells(editor)

        _restore_line_cache(editor, stale_cursor_cache)
        assert _disable_cursor_blink(page) is True
        assert _textarea_caret_cells(editor) == []

        _restore_line_cache(editor, stale_cursor_cache)
        await wait_for_visual_idle(cast(Any, page), timeout=2.0)

        assert not editor.has_focus
        assert editor._draw_cursor is False
        assert _textarea_caret_cells(editor) == []


@pytest.mark.asyncio
async def test_visual_idle_repaints_focused_textarea_cursor() -> None:
    app = _CursorCacheApp()
    async with app.run_test(size=(40, 16)) as pilot:
        editor = app.query_one("#editor", TextArea)
        ok_button = app.query_one("#ok", Button)

        ok_button.focus()
        editor.cursor_blink = False
        editor._pause_blink(visible=False)
        editor._line_cache.clear()
        await pilot.pause()
        editor.render_line(0)
        caret_free_cache = _copy_line_cache(editor)
        assert _textarea_caret_cells(editor) == []

        editor.focus()
        editor.cursor_blink = False
        editor._pause_blink(visible=True)
        await pilot.pause()
        _restore_line_cache(editor, caret_free_cache)
        assert editor.has_focus
        assert editor._draw_cursor is True
        assert _textarea_caret_cells(editor) == []

        page = _CursorCachePage(app, pilot)
        await wait_for_visual_idle(cast(Any, page), timeout=2.0)

        assert editor.has_focus
        assert editor._draw_cursor is True
        assert _textarea_caret_cells(editor)
