"""Tests for prompt directive-name completion UI interactions."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from textual.widgets import Static

from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.feature_flags import override_flags

from ._completion_helpers import CompletionTestApp


@pytest.fixture(autouse=True)
def _typed_launch_units_off_by_default() -> Iterator[None]:
    """Keep the directive panel compact and independent of host flag state."""
    with override_flags(typed_launch_units=False):
        yield


async def test_ctrl_t_at_percent_opens_directive_panel() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("%")
        ta.cursor_location = (0, 1)
        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            assert ta._try_file_completion_tab() is True

        panel = bar.query_one("#prompt-completion", Static)
        assert ta._file_completion_active is True
        assert ta._completion_kind == "directive"
        assert panel.border_title == "directives"
        insertions = {
            candidate.insertion for candidate in ta._file_completion_candidates
        }
        assert {"%final", "%model"} <= insertions
        plain = panel.render().plain
        assert "Split prompt into variants with different text" in plain
        assert "Select configured finalizer instances for this launch" in plain


async def test_ctrl_t_at_partial_directive_inserts_single_candidate() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%mo")
        ta.cursor_location = (0, 3)
        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            assert ta._try_file_completion_tab() is True

    assert ta.text == "%model"
    assert ta._file_completion_active is True
    assert [c.insertion for c in ta._file_completion_candidates] == [
        "%model",
        "%model:value",
        "%model(model, alias=model)",
    ]


async def test_ctrl_t_at_alias_partial_inserts_canonical_directive() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%m")
        ta.cursor_location = (0, 2)
        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            assert ta._try_file_completion_tab() is True

    assert ta.text == "%model"
    assert ta._file_completion_active is True
    assert [c.insertion for c in ta._file_completion_candidates] == [
        "%model",
        "%model:value",
        "%model(model, alias=model)",
    ]


async def test_multi_candidate_directive_completion_accepts_ctrl_l() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("%a")
        ta.cursor_location = (0, 2)
        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            await pilot.press("ctrl+t")
            assert ta._file_completion_active is True
            await pilot.press("down")
            selected = ta._file_completion_candidates[
                ta._file_completion_index
            ].insertion
            await pilot.press("ctrl+l")

    assert ta.text == selected
    assert ta._file_completion_active is False


async def test_percent_partial_auto_opens_directive_panel() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)

        await pilot.press("%")
        assert ta.text == "%"
        assert ta._file_completion_active is True

        await pilot.press("m")

        # A single ``%m`` -> ``%model`` match keeps the menu open but never
        # auto-accepts: the text stays ``%m`` until the user accepts explicitly.
        assert ta.text == "%m"
        assert ta._file_completion_active is True
        assert ta._completion_kind == "directive"
        assert [c.insertion for c in ta._file_completion_candidates] == [
            "%model",
            "%model:value",
            "%model(model, alias=model)",
        ]
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "directives"


async def test_bare_percent_auto_opens_directive_panel() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)

        await pilot.press("%")

        assert ta.text == "%"
        assert ta._file_completion_active is True
        assert ta._completion_kind == "directive"
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "directives"


async def test_bare_percent_auto_menu_uses_directive_gate() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with patch.object(
            type(ta),
            "_prompt_completion_settings",
            return_value=PromptCompletionSettings(auto_directive_menu=False),
        ):
            await pilot.press("%")

        assert ta.text == "%"
        assert ta._file_completion_active is False


async def test_bare_percent_then_brace_clears_menu_and_inserts_alt_pair() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        await pilot.press("%")
        assert ta._file_completion_active is True

        await pilot.press("{")

        assert ta.text == "%{  }"
        assert ta._file_completion_active is False


async def test_unknown_directive_does_not_show_placeholder() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        await pilot.press("%")
        await pilot.press("z")

        assert ta.text == "%z"
        assert ta._file_completion_active is False
        assert ta._file_completion_candidates == []


async def test_directive_invalid_context_does_not_auto_open() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("word")
        ta.cursor_location = (0, 4)

        await pilot.press("%")
        await pilot.press("m")

        assert ta.text == "word%m"
        assert ta._file_completion_active is False


async def test_directive_typing_narrows_deleting_widens_and_space_dismisses() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        await pilot.press("%")
        await pilot.press("a")
        assert [c.insertion for c in ta._file_completion_candidates] == [
            "%alt",
            "%auto",
            "%auto:value",
            "%{A | B}",
        ]

        await pilot.press("u")
        assert ta.text == "%au"
        assert [c.insertion for c in ta._file_completion_candidates] == [
            "%auto",
            "%auto:value",
        ]

        await pilot.press("backspace")
        assert ta.text == "%a"
        assert [c.insertion for c in ta._file_completion_candidates] == [
            "%alt",
            "%auto",
            "%auto:value",
            "%{A | B}",
        ]

        await pilot.press("space")
        assert ta.text == "%a "
        assert ta._file_completion_active is False
