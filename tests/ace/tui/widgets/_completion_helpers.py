"""Shared helpers for prompt file-completion tests."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class CompletionTestApp(App[None]):
    """Minimal app that hosts PromptInputBar for file completion tests."""

    # Mirror AceApp: the prompt subsystem owns ctrl+n/ctrl+p/ctrl+r, so the
    # command palette (default ctrl+p) must not intercept them.
    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        snippets: dict[str, str] | None = None,
        common_placeholders: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._snippets: dict[str, str] = snippets or {}
        # ``None`` stands in for a cold cache, exactly as the real app's
        # ``common_placeholders()`` does before its first warm lands.
        self._common_placeholders: list[str] | None = common_placeholders
        self._common_placeholders_gen = 0

    def get_snippets(self) -> dict[str, str]:
        return self._snippets

    def common_placeholders(self) -> list[str] | None:
        return self._common_placeholders

    def common_placeholders_generation(self) -> int:
        return self._common_placeholders_gen

    def publish_common_placeholders(self, placeholders: list[str]) -> None:
        """Stand in for a warm cache landing while a menu is already open."""
        self._common_placeholders = list(placeholders)
        self._common_placeholders_gen += 1

    def compose(self) -> ComposeResult:
        yield PromptInputBar()


def create_entries(root: Path) -> None:
    """Create a deterministic home tree for completion tests."""
    (root / "alpha").mkdir()
    (root / "apple").mkdir()
    (root / "docs").mkdir()
    (root / "readme.md").write_text("x", encoding="utf-8")
    (root / "results.txt").write_text("x", encoding="utf-8")
