"""Regression tests for PromptInputBar detach race in `_update_height`."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.geometry import Region

from sase.ace.tui.actions.agent_workflow._prompt_bar_mount import (
    PromptBarMountMixin,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class PromptDetachTestApp(App[None]):
    """Minimal app that hosts a single PromptInputBar."""

    def compose(self) -> ComposeResult:
        yield PromptInputBar("hello", id="prompt-input-bar")


class _DetachApp(PromptBarMountMixin, App[None]):
    """Drive `_detach_prompt_bar` / spare discard against a live bar."""

    def compose(self) -> ComposeResult:
        yield PromptInputBar("hello", id="prompt-input-bar")


async def test_update_height_after_synchronous_detach_does_not_crash() -> None:
    """Mirrors `_detach_prompt_bar`: synchronously remove the bar from its
    parent's `_nodes`, then invoke `_update_height` (as a deferred
    `call_after_refresh` would). The bar should bail out instead of raising
    `NoScreen`."""
    app = PromptDetachTestApp()
    async with app.run_test():
        bar = app.query_one("#prompt-input-bar", PromptInputBar)
        parent = bar._parent
        assert parent is not None
        parent._nodes._remove(bar)  # type: ignore[attr-defined]
        await bar.remove()

        bar._update_height()


async def test_pruned_prompt_text_area_survives_full_repaint() -> None:
    """A pruned PromptTextArea still in the compositor map must not crash."""
    app = PromptDetachTestApp()
    async with app.run_test(size=(80, 24)):
        bar = app.query_one("#prompt-input-bar", PromptInputBar)
        text_area = bar.active_text_area()
        parent = bar._parent
        assert parent is not None
        parent._nodes._remove(bar)  # type: ignore[attr-defined]
        await bar.remove()

        assert text_area in app.screen._compositor.visible_widgets
        app.screen._compositor.render_update(full=True)


async def test_detached_prompt_text_area_render_contract() -> None:
    """Detached TextAreas return blank strips; attached ones still paint text."""
    app = PromptDetachTestApp()
    async with app.run_test(size=(80, 24)):
        bar = app.query_one("#prompt-input-bar", PromptInputBar)
        text_area = bar.active_text_area()
        attached = text_area.render_lines(
            Region(0, 0, max(text_area.size.width, 1), max(text_area.size.height, 1))
        )
        assert any("hello" in strip.text for strip in attached)

        parent = bar._parent
        assert parent is not None
        parent._nodes._remove(bar)  # type: ignore[attr-defined]
        await bar.remove()

        width, height = 10, 3
        lines = text_area.render_lines(Region(0, 0, width, height))
        assert len(lines) == height
        assert all(line.cell_length == width for line in lines)
        text_area.render_line(0)


async def test_detach_prompt_bar_requests_layout_before_next_paint() -> None:
    """Synchronous detach rebuilds the compositor map on the next timer tick."""
    app = _DetachApp()
    async with app.run_test(size=(80, 24)):
        bar = app.query_one("#prompt-input-bar", PromptInputBar)
        text_area = bar.active_text_area()
        # Consume the mount-time layout so this tick only sees the unlink.
        app.screen._on_timer_update()
        assert app.screen._layout_required is False
        assert bar in app.screen._compositor.visible_widgets
        app._detach_prompt_bar(bar)
        assert app.screen._layout_required is True
        app.screen._on_timer_update()
        visible = app.screen._compositor.visible_widgets
        assert bar not in visible
        assert text_area not in visible


async def test_discard_prompt_bar_spare_requests_layout() -> None:
    """Spare discard requests a layout refresh at unlink time."""
    app = _DetachApp()
    async with app.run_test(size=(80, 24)):
        bar = app.query_one("#prompt-input-bar", PromptInputBar)
        app._prompt_bar_spare = bar
        app.screen._layout_required = False
        app._discard_prompt_bar_spare()
        assert app.screen._layout_required is True
        assert app._prompt_bar_spare is None
