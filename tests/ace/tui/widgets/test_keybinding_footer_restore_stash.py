"""The leader footer shows ``,P`` restore only when a stash exists."""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.keybinding_footer import KeybindingFooter


class _Host(App):
    def compose(self) -> ComposeResult:
        yield KeybindingFooter(id="keybinding-footer")


def _captured_leader_labels(
    footer: KeybindingFooter, *, has_stashed_prompts: bool
) -> list[str]:
    captured: list[tuple[str, str]] = []
    footer._update_display = (  # type: ignore[method-assign]
        lambda bindings, mode_label="": captured.extend(bindings)
    )
    footer.update_leader_bindings(
        current_tab="agents", has_stashed_prompts=has_stashed_prompts
    )
    return [label for _key, label in captured]


async def test_restore_keymap_hidden_when_stash_empty() -> None:
    app = _Host()
    async with app.run_test():
        footer = app.query_one(KeybindingFooter)
        labels = _captured_leader_labels(footer, has_stashed_prompts=False)
        assert "restore stash" not in labels


async def test_restore_keymap_shown_when_stash_nonempty() -> None:
    app = _Host()
    async with app.run_test():
        footer = app.query_one(KeybindingFooter)
        labels = _captured_leader_labels(footer, has_stashed_prompts=True)
        assert "restore stash" in labels
