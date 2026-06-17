"""Regression: the leader footer no longer advertises a restore-stash keymap.

The global ``,P`` restore-stash leader binding was retired in favour of the
prompt-local ``gP`` / ``gp`` keymaps on the prompt input bar.  The leader footer
must never surface a "restore stash" entry, and ``update_leader_bindings`` no
longer accepts the old ``has_stashed_prompts`` gate.
"""

from __future__ import annotations

import inspect

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.keybinding_footer import KeybindingFooter


class _Host(App):
    def compose(self) -> ComposeResult:
        yield KeybindingFooter(id="keybinding-footer")


def _captured_leader_labels(footer: KeybindingFooter) -> list[str]:
    captured: list[tuple[str, str]] = []
    footer._update_display = (  # type: ignore[method-assign]
        lambda bindings, mode_label="": captured.extend(bindings)
    )
    footer.update_leader_bindings(current_tab="agents")
    return [label for _key, label in captured]


async def test_leader_footer_never_shows_restore_stash() -> None:
    app = _Host()
    async with app.run_test():
        footer = app.query_one(KeybindingFooter)
        labels = _captured_leader_labels(footer)
        assert "restore stash" not in labels


def test_update_leader_bindings_dropped_has_stashed_prompts_param() -> None:
    """The retired gate is gone from the signature, not just unused."""
    params = inspect.signature(KeybindingFooter.update_leader_bindings).parameters
    assert "has_stashed_prompts" not in params
