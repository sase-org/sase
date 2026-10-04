"""Project-variable tests for prompt snippet expansion.

Split from ``test_prompt_snippet_expansion``; shared helpers live in
``_prompt_snippet_expansion_shared`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from textual.app import App

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._prompt_snippet_expansion_shared import SnippetTestApp


def _ace_app_ctx(ta: PromptTextArea, app: App) -> Any:
    """Patch the ``_ace_app`` property onto the widget type for *app*."""
    return patch.object(
        type(ta),
        "_ace_app",
        new_callable=lambda: property(lambda self: app),
    )


class TestSnippetProjectVariable:
    async def test_tag_led_prompt_expands_project_with_cursor_at_marker(self) -> None:
        """A prompt-target project resolves ``#{project}`` on Tab expansion."""
        app = SnippetTestApp({"epic": "the #{project}-$1 epic bead"})
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("+sase epic")
            ta.cursor_location = (0, 10)
            with (
                _ace_app_ctx(ta, app),
                patch.object(
                    type(ta),
                    "_macro_arg_assist_project_from_text",
                    return_value="sase",
                ),
                patch.object(PromptTextArea, "notify") as notify,
            ):
                assert ta._try_expand_snippet() is True
            assert ta.text == "+sase the sase- epic bead"
            assert ta.cursor_location == (0, 15)
            notify.assert_not_called()

    async def test_non_home_prompt_context_used_without_tag(self) -> None:
        """No tag: a non-home prompt context supplies the project name."""
        app = SnippetTestApp({"epic": "the #{project}-$1 epic bead"})
        app._prompt_context = SimpleNamespace(  # type: ignore[attr-defined]
            is_home_mode=False,
            project_name="bob-cli",
        )
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("epic")
            ta.cursor_location = (0, 4)
            with (
                _ace_app_ctx(ta, app),
                patch.object(PromptTextArea, "notify") as notify,
            ):
                assert ta._try_expand_snippet() is True
            assert ta.text == "the bob-cli- epic bead"
            assert ta.cursor_location == (0, 12)
            notify.assert_not_called()

    async def test_no_tag_falls_back_to_stubbed_current_project(self) -> None:
        """No tag or context: the cached current project is the fallback."""
        app = SnippetTestApp({"epic": "the #{project}-$1 epic bead"})
        stub_source = SimpleNamespace(
            state=SimpleNamespace(
                project_snapshot=SimpleNamespace(
                    project=SimpleNamespace(display_name="sase"),
                ),
            ),
        )
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("epic")
            ta.cursor_location = (0, 4)
            real_query_one = app.query_one

            def _query_one(selector: Any, expect_type: Any = None) -> Any:
                if selector == "#launch-context-source":
                    return stub_source
                if expect_type is None:
                    return real_query_one(selector)
                return real_query_one(selector, expect_type)

            with (
                _ace_app_ctx(ta, app),
                patch.object(
                    type(ta),
                    "_macro_arg_assist_project_from_text",
                    return_value=None,
                ),
                patch.object(app, "query_one", side_effect=_query_one),
                patch.object(PromptTextArea, "notify") as notify,
            ):
                assert ta._try_expand_snippet() is True
            assert ta.text == "the sase- epic bead"
            assert ta.cursor_location == (0, 9)
            notify.assert_not_called()

    async def test_nothing_resolved_leaves_token_verbatim_and_warns(self) -> None:
        """No project anywhere: ``#{project}`` stays literal with a warning."""
        app = SnippetTestApp({"epic": "the #{project}-$1 epic bead"})
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("epic")
            ta.cursor_location = (0, 4)
            with (
                _ace_app_ctx(ta, app),
                patch.object(
                    type(ta),
                    "_macro_arg_assist_project_from_text",
                    return_value=None,
                ),
                patch.object(PromptTextArea, "notify") as notify,
            ):
                assert ta._try_expand_snippet() is True
            assert ta.text == "the #{project}- epic bead"
            assert ta.cursor_location == (0, 15)
            notify.assert_called_once_with(
                "Snippet left #{project} unresolved; add a +<project> tag",
                severity="warning",
            )

    async def test_composed_caller_is_substituted_too(self) -> None:
        """A composed ``#[epic]`` body inherits the variable substitution."""
        app = SnippetTestApp({"repic": "re: the #{project}-$1 epic bead"})
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("repic")
            ta.cursor_location = (0, 5)
            with (
                _ace_app_ctx(ta, app),
                patch.object(
                    type(ta),
                    "_macro_arg_assist_project_from_text",
                    return_value="sase",
                ),
            ):
                assert ta._try_expand_snippet() is True
            assert ta.text == "re: the sase- epic bead"

    async def test_unknown_variable_stays_verbatim(self) -> None:
        """An unknown ``#{foo}`` is untouched even when a project resolves."""
        app = SnippetTestApp({"weird": "the #{foo}-$1 bead"})
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("weird")
            ta.cursor_location = (0, 5)
            with (
                _ace_app_ctx(ta, app),
                patch.object(
                    type(ta),
                    "_macro_arg_assist_project_from_text",
                    return_value="sase",
                ),
                patch.object(PromptTextArea, "notify") as notify,
            ):
                assert ta._try_expand_snippet() is True
            assert ta.text == "the #{foo}- bead"
            notify.assert_not_called()

    async def test_template_without_token_never_calls_resolver(self) -> None:
        """Ordinary snippets pay nothing: the resolver is never consulted."""
        app = SnippetTestApp({"hello": "Hello World"})
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("hello")
            ta.cursor_location = (0, 5)
            resolver = MagicMock(
                side_effect=AssertionError("resolver must not run"),
            )
            with (
                _ace_app_ctx(ta, app),
                patch.object(type(ta), "_snippet_project_name", resolver),
            ):
                assert ta._try_expand_snippet() is True
            assert ta.text == "Hello World"
            resolver.assert_not_called()
