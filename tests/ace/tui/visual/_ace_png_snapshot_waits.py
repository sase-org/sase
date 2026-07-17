"""Render and state synchronization for ACE PNG visual snapshot tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import hashlib
from typing import Any

from sase.ace.testing import AcePage


def _svg_plain(page: AcePage, *, title: str) -> str:
    return page.export_svg(title=title).replace("&#160;", " ")


async def wait_for_state(
    page: AcePage,
    predicate: Callable[[], bool],
    *,
    description: str = "visual state predicate",
    timeout: float = 15.0,
) -> None:
    """Wait until a semantic visual-state predicate becomes true.

    Unlike :func:`wait_for_visual_idle`, this helper proves that the intended
    UI state was reached. Frame convergence alone can accept a stable but
    incorrect frame (for example, the screen behind a modal that has not
    painted yet).
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    while True:
        await page.pause()
        if predicate():
            return
        if loop.time() >= deadline:
            last_frame = page.export_svg(title="ACE visual state timeout")
            digest = hashlib.sha256(last_frame.encode()).hexdigest()[:12]
            raise AssertionError(
                f"Timed out after {timeout:.2f}s waiting for {description}; "
                f"last_frame_digest={digest}; last_frame_svg={last_frame!r}"
            )
        await asyncio.sleep(min(0.01, max(0.0, deadline - loop.time())))


async def wait_for_svg_contains(
    page: AcePage,
    text: str,
    *,
    timeout: float = 15.0,
) -> None:
    """Wait until the exported frame contains the expected text sentinel."""
    await wait_for_state(
        page,
        lambda: text in _svg_plain(page, title="ACE visual sentinel probe"),
        description=f"SVG sentinel {text!r}",
        timeout=timeout,
    )


_VISUAL_DEBOUNCERS = (
    "_changespec_detail_debouncer",
    "_agent_detail_debouncer",
    "_axe_detail_debouncer",
)
_VISUAL_STABLE_FRAME_COUNT = 3
# Short one-shot timers cover input diagnostics, validation, and pressed-state
# cleanup. Longer one-shots (for example toast expiry) intentionally keep a
# stable visible surface alive and must not be awaited until it disappears.
_VISUAL_SETTLING_TIMER_MAX_SECONDS = 0.5


def _clear_transient_button_state(page: AcePage) -> None:
    from textual.widgets import Button

    # Button.press() adds a transient pressed highlight and removes it on a
    # timer; visual snapshots should capture the resting state, not race that
    # timer.
    for screen in page.app.screen_stack:
        for button in screen.query(Button):
            button.remove_class("-active")


def _disable_cursor_blink(page: AcePage) -> None:
    from textual.widgets import Input, TextArea

    for screen in page.app.screen_stack:
        for widget in screen.walk_children():
            if isinstance(widget, (Input, TextArea)):
                widget.cursor_blink = False


def _pending_visual_work(page: AcePage) -> tuple[list[str], list[str], list[str]]:
    """Describe finite work that can still change an ACE screenshot."""
    debouncers = [
        name
        for name in _VISUAL_DEBOUNCERS
        if bool(getattr(getattr(page.app, name, None), "is_pending", False))
    ]
    workers = [
        str(getattr(worker, "name", None) or getattr(worker, "description", worker))
        for worker in page.app.workers
        if bool(getattr(worker, "is_running", False))
    ]

    # Textual does not expose a public timer registry. In this test helper it
    # is safe to inspect the message pumps' weak timer sets. Wait for one-shot
    # timers only; recurring clocks are expected to remain alive while the app
    # is mounted and render convergence handles whether they affect the frame.
    nodes: list[Any] = [page.app]
    for screen in page.app.screen_stack:
        nodes.extend(screen.walk_children(with_self=True))
    timers: list[str] = []
    seen_nodes: set[int] = set()
    for node in nodes:
        if id(node) in seen_nodes:
            continue
        seen_nodes.add(id(node))
        for timer in getattr(node, "_timers", ()):
            task = getattr(timer, "_task", None)
            if (
                getattr(timer, "_repeat", None) == 0
                and float(getattr(timer, "_interval", float("inf")))
                <= _VISUAL_SETTLING_TIMER_MAX_SECONDS
                and task is not None
                and not task.done()
            ):
                timers.append(str(getattr(timer, "name", timer)))
    return debouncers, workers, timers


async def wait_for_visual_idle(page: AcePage, *, timeout: float = 8.0) -> None:
    """Wait for finite work to finish and the rendered SVG frame to converge."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    previous_svg: str | None = None
    stable_frames = 0
    frame_digests: list[str] = []
    pending: tuple[list[str], list[str], list[str]] = ([], [], [])

    while True:
        await page.pause()
        _clear_transient_button_state(page)
        _disable_cursor_blink(page)
        pending = _pending_visual_work(page)

        if any(pending):
            previous_svg = None
            stable_frames = 0
        else:
            # Exporting forces Textual to materialize the compositor's current
            # frame. Requiring the same result across separate idle/layout
            # cycles prevents a partially painted frame from reaching the PNG
            # comparator merely because a fixed number of pauses elapsed.
            svg = page.export_svg(title="ACE visual convergence probe")
            digest = hashlib.sha256(svg.encode()).hexdigest()[:12]
            frame_digests.append(digest)
            frame_digests = frame_digests[-4:]
            stable_frames = stable_frames + 1 if svg == previous_svg else 1
            previous_svg = svg
            if stable_frames >= _VISUAL_STABLE_FRAME_COUNT:
                return

        if loop.time() >= deadline:
            debouncers, workers, timers = pending
            raise AssertionError(
                "Timed out waiting for ACE visual render convergence "
                f"after {timeout:.2f}s; stable_frames={stable_frames}/"
                f"{_VISUAL_STABLE_FRAME_COUNT}; frame_digests={frame_digests}; "
                f"pending_debouncers={debouncers}; pending_workers={workers}; "
                f"pending_one_shot_timers={timers}"
            )

        # ``Pilot.pause`` yields until the current queue is idle, but finite
        # timers and thread workers need a small amount of wall-clock progress.
        await asyncio.sleep(min(0.01, max(0.0, deadline - loop.time())))
