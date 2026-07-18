"""Idempotent ``KeybindingFooter`` updates skip when state is unchanged."""

from __future__ import annotations

from types import SimpleNamespace

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

        bindings = [("k", "kill")]
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
        footer._update_display([("k", "kill")])
        assert calls == 0


async def test_member_jump_footer_shows_pending_digit_and_completion_hints() -> None:
    app = _Host()
    async with app.run_test():
        footer = app.query_one(KeybindingFooter)
        footer._startup_stopwatch_active = False

        footer.update_member_jump_bindings("1")

        content = footer._content_widget
        assert content is not None
        assert footer._last_bindings_signature is not None
        assert footer._last_bindings_signature[0] == (
            " member 1▁  <esc> cancel · 0-9 second digit"
        )


async def test_numbered_member_binding_is_conditional_on_container_rows() -> None:
    app = _Host()
    async with app.run_test():
        footer = app.query_one(KeybindingFooter)
        common = {
            "status": "RUNNING",
            "pid": None,
            "agent_name": None,
            "workspace_num": None,
            "attempt_history": [],
        }
        clan = SimpleNamespace(
            **common,
            is_clan_container=True,
            is_family_container_row=False,
        )
        family = SimpleNamespace(
            **common,
            is_clan_container=False,
            is_family_container_row=True,
        )
        regular = SimpleNamespace(
            **common,
            is_clan_container=False,
            is_family_container_row=False,
        )

        assert ("0-9", "member") in footer._compute_agent_bindings(clan)
        assert ("0-9", "member") in footer._compute_agent_bindings(family)
        assert ("0-9", "member") not in footer._compute_agent_bindings(regular)
        assert ("0-9", "member") not in footer._compute_agent_bindings(
            clan,
            group_focused=True,
        )
