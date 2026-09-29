"""Shared helpers for the split prompt snippet-expansion tests.

The tests formerly lived in a single ``test_prompt_snippet_expansion`` module.
Helpers needed by more than one split module live here under public names;
the ``test_prompt_snippet_expansion_*`` modules import only these public names
(never ``_``-prefixed names from each other).
"""

from __future__ import annotations

from unittest.mock import patch

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

__all__ = [
    "SnippetTestApp",
    "setup_snippet_expansion",
]


class SnippetTestApp(App):
    """Minimal app that hosts a PromptTextArea for snippet testing."""

    def __init__(self, snippets: dict[str, str] | None = None) -> None:
        super().__init__()
        self._snippets: dict[str, str] = snippets or {}

    def get_snippets(self) -> dict[str, str]:
        return self._snippets

    def compose(self) -> ComposeResult:
        yield PromptTextArea()


async def setup_snippet_expansion(
    snippets: dict[str, str],
    text: str = "",
    cursor: tuple[int, int] = (0, 0),
) -> tuple[PromptTextArea, bool]:
    """Mount a PromptTextArea with text/cursor and try to expand a snippet.

    Returns (widget, expanded) so tests can assert on both the result
    and the resulting text/cursor state.
    """
    app = SnippetTestApp(snippets)
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        if text:
            ta.load_text(text)
        ta.cursor_location = cursor
        with patch.object(
            type(ta), "_ace_app", new_callable=lambda: property(lambda self: app)
        ):
            result = ta._try_expand_snippet()
        return ta, result
