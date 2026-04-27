"""Shared helpers for prompt file-completion tests."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class CompletionTestApp(App[None]):
    """Minimal app that hosts PromptInputBar for file completion tests."""

    def __init__(self, snippets: dict[str, str] | None = None) -> None:
        super().__init__()
        self._snippets: dict[str, str] = snippets or {}

    def get_snippets(self) -> dict[str, str]:
        return self._snippets

    def compose(self) -> ComposeResult:
        yield PromptInputBar()


def create_entries(root: Path) -> None:
    """Create a deterministic home tree for completion tests."""
    (root / "alpha").mkdir()
    (root / "apple").mkdir()
    (root / "docs").mkdir()
    (root / "readme.md").write_text("x", encoding="utf-8")
    (root / "results.txt").write_text("x", encoding="utf-8")
