"""Tests for the commit view modal."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.modals.commit_view_modal import CommitViewModal
from sase.ace.tui.widgets.prompt_panel._agent_display_state import CommitViewSpec


class _CommitModalTestApp(App[None]):
    def __init__(self, spec: CommitViewSpec) -> None:
        super().__init__()
        self.spec = spec

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(CommitViewModal(self.spec))


def _spec(diff_path: str) -> CommitViewSpec:
    return CommitViewSpec(
        short_sha="abcdef123456",
        sha="abcdef1234567890",
        repo_name="sase",
        cwd="/workspace/sase",
        subject="feat: modal",
        message="feat: modal\n\nRender commit details.",
        diff_path=diff_path,
        is_primary=True,
    )


async def test_commit_view_modal_copies_sha_and_closes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    diff_path = tmp_path / "commit.diff"
    diff_path.write_text(
        """diff --git a/src/example.py b/src/example.py
--- a/src/example.py
+++ b/src/example.py
@@ -1 +1 @@
-old
+new
""",
        encoding="utf-8",
    )
    copied: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.modals.commit_view_modal.copy_to_system_clipboard",
        lambda content: copied.append(content) is None or True,
    )
    app = _CommitModalTestApp(_spec(str(diff_path)))

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CommitViewModal)

        for _ in range(5):
            await pilot.pause()
        modal.query_one("#commit-view-content", Static)
        assert modal._diff_loaded is True
        assert modal._diff_text is not None
        assert "diff --git" in modal._diff_text

        await pilot.press("y")
        await pilot.pause()
        assert copied == ["abcdef1234567890"]

        await pilot.press("q")
        await pilot.pause()
        assert not isinstance(app.screen_stack[-1], CommitViewModal)
