"""Idempotent ``KeybindingFooter`` updates skip when state is unchanged."""

from __future__ import annotations

from rich.text import Text
from textual.app import App, ComposeResult

from sase.ace.tui.widgets.keybinding_footer import KeybindingFooter


class _Host(App):
    def compose(self) -> ComposeResult:
        yield KeybindingFooter(id="keybinding-footer")


async def test_repeat_status_update_skips_static_update() -> None:
    """A second ``_update_status`` with no state change does not repaint."""
    app = _Host()
    async with app.run_test():
        footer = app.query_one(KeybindingFooter)
        footer._startup_stopwatch_active = False
        footer._last_status_signature = None
        footer._update_status()
        assert footer._last_status_signature is not None
        first = footer._last_status_signature

        # Track Static.update via the cached child ref.
        status = footer._status_widget
        assert status is not None
        calls = 0
        original = status.update

        def _counting_update(text):
            nonlocal calls
            calls += 1
            return original(text)

        status.update = _counting_update  # type: ignore[method-assign]

        # Same state → must not repaint.
        footer._update_status()
        assert calls == 0
        assert footer._last_status_signature == first

        # Flip a state field → repaint runs once.
        footer._axe_running = True
        footer._update_status()
        assert calls == 1


async def test_repeat_bindings_update_skips_static_update() -> None:
    """Identical bindings text on consecutive ``_update_display`` calls is a no-op."""
    app = _Host()
    async with app.run_test():
        footer = app.query_one(KeybindingFooter)
        footer._startup_stopwatch_active = False
        footer._last_status_signature = None
        footer._last_bindings_signature = None

        bindings = Text("k kill", style="bold")
        footer._update_display(bindings)
        assert footer._last_bindings_signature is not None

        content = footer._content_widget
        assert content is not None
        calls = 0
        original = content.update

        def _counting_update(text):
            nonlocal calls
            calls += 1
            return original(text)

        content.update = _counting_update  # type: ignore[method-assign]

        # Same bindings + same status → both signatures hit, zero updates.
        footer._update_display(Text("k kill", style="bold"))
        assert calls == 0
