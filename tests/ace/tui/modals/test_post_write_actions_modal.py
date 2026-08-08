"""Post-write action chooser behavior."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.modals.post_write_actions_modal import PostWriteActionsModal
from sase.xprompt.write_targets import PostWriteActionKind, PostWriteActionOffer


class _ModalApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield Static("")


def _offer(
    kind: PostWriteActionKind,
    *,
    key: str,
    label: str,
) -> PostWriteActionOffer:
    return PostWriteActionOffer(
        kind=kind,
        key=key,
        label=label,
        subtitle=f"Run {label}.",
        default_on=True,
        file_path="/tmp/review.md",
        rel_path="xprompts/review.md",
    )


async def test_post_write_modal_toggles_rows_and_returns_selected() -> None:
    results: list[tuple[PostWriteActionKind, ...]] = []
    app = _ModalApp()
    actions = (
        _offer(PostWriteActionKind.COMMIT_PUSH, key="c", label="Commit & push"),
        _offer(PostWriteActionKind.APPLY_CHEZMOI, key="a", label="Apply chezmoi"),
    )

    async with app.run_test(size=(90, 28)) as pilot:
        app.push_screen(
            PostWriteActionsModal(actions, subject="xprompts/review.md"),
            results.append,
        )
        await pilot.pause()

        modal = app.screen
        assert isinstance(modal, PostWriteActionsModal)
        rows = modal.query_one("#post-write-actions-list", Static)
        assert "[x] Commit & push" in rows.render().plain

        await pilot.press("c")
        await pilot.pause()
        assert "[ ] Commit & push" in rows.render().plain

        await pilot.press("enter")
        await pilot.pause()

    assert results == [(PostWriteActionKind.APPLY_CHEZMOI,)]


async def test_post_write_modal_escape_skips_all() -> None:
    results: list[tuple[PostWriteActionKind, ...]] = []
    app = _ModalApp()
    actions = (
        _offer(PostWriteActionKind.MEMORY_INIT, key="m", label="sase memory init"),
    )

    async with app.run_test(size=(90, 24)) as pilot:
        app.push_screen(
            PostWriteActionsModal(actions, subject="sase/memory/obsidian.md"),
            results.append,
        )
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert results == [()]
