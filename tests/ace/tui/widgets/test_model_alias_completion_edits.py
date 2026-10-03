"""Edit-plan and literal-text tests for ``=alias`` model completion.

Split from ``test_model_alias_completion``; shared helpers live in
``_model_alias_completion_shared`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets._model_shortcut_edits import apply_model_shortcut_edit
from sase.ace.tui.widgets.model_alias_completion import (
    build_model_alias_completion_candidates,
    detect_model_alias_completion_context,
    plan_model_alias_completion_edit,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

from tests._macro_model_completion_helpers import (
    clear_model_completion_cache as clear_model_completion_cache,
)

from ._model_alias_completion_shared import (
    ModelAliasCompletionTestApp,
    alias_entries,
)

__all__ = [
    "clear_model_completion_cache",
    "test_equals_alias_accept_moves_value_to_existing_directive",
    "test_equals_alias_accept_removes_adjacent_directive_and_undo_restores",
    "test_equals_alias_context_detects_prompt_boundaries",
    "test_equals_alias_context_rejects_protected_regions_and_unicode_columns",
    "test_equals_alias_edit_plan_applies_segment_replacement",
    "test_equals_alias_edit_plan_is_cursor_complete",
    "test_legacy_star_alias_stays_literal_and_can_submit",
    "test_unknown_equals_alias_stays_literal_and_can_submit",
]


@pytest.mark.parametrize(
    ("text", "cursor", "query", "token"),
    [
        ("=", (0, 1), "", "="),
        ("Use =la", (0, 7), "la", "=la"),
        ("first\nnext =SM", (1, 8), "SM", "=SM"),
        ("  =small", (0, 8), "small", "=small"),
    ],
)
def test_equals_alias_context_detects_prompt_boundaries(
    text: str,
    cursor: tuple[int, int],
    query: str,
    token: str,
) -> None:
    context = detect_model_alias_completion_context(text, cursor)

    assert context is not None
    assert context.query == query
    assert context.token == token


@pytest.mark.parametrize(
    ("text", "cursor", "expected_text", "expected_replacement"),
    [
        ("Use =la", (0, 7), "Use %m:@large ", "%m:@large "),
        ("Use =la now", (0, 7), "Use %m:@large now", "%m:@large "),
        ("Use =la   now", (0, 7), "Use %m:@large   now", "%m:@large "),
        ("Use =la\tnow", (0, 7), "Use %m:@large\tnow", "%m:@large"),
        ("Use =la\nnow", (0, 7), "Use %m:@large \nnow", "%m:@large "),
        ("Explain =laX later", (0, 11), "Explain %m:@large later", "%m:@large "),
        (
            "Title\r\nUse =la\ttail",
            (1, len("Use =la")),
            "Title\r\nUse %m:@large\ttail",
            "%m:@large",
        ),
        ("🙂 =la\r\nnext", (0, 5), "🙂 %m:@large \r\nnext", "%m:@large "),
    ],
)
def test_equals_alias_edit_plan_is_cursor_complete(
    text: str,
    cursor: tuple[int, int],
    expected_text: str,
    expected_replacement: str,
) -> None:
    context = detect_model_alias_completion_context(text, cursor)
    assert context is not None
    candidates = build_model_alias_completion_candidates(context, alias_entries())
    planned = plan_model_alias_completion_edit(
        text,
        cursor,
        alias_entries(),
        candidates[0],
    )

    assert planned is not None
    assert planned.replacement == expected_replacement
    applied = (
        f"{text[: planned.replacement_start]}"
        f"{planned.replacement}"
        f"{text[planned.replacement_end :]}"
    )
    assert applied == expected_text
    assert planned.caret_offset == planned.replacement_start + len(planned.replacement)


@pytest.mark.parametrize(
    ("text", "cursor", "expected_text", "expected_caret"),
    [
        ("%model:old Use =la", (0, 18), "%m:@large Use ", 10),
        ("Use =la then %m:old", (0, 7), "Use then %m:@large ", 19),
    ],
)
def test_equals_alias_edit_plan_applies_segment_replacement(
    text: str,
    cursor: tuple[int, int],
    expected_text: str,
    expected_caret: int,
) -> None:
    """A standalone directive in the trigger's segment takes the value."""
    context = detect_model_alias_completion_context(text, cursor)
    assert context is not None
    candidates = build_model_alias_completion_candidates(context, alias_entries())
    planned = plan_model_alias_completion_edit(
        text,
        cursor,
        alias_entries(),
        candidates[0],
    )

    assert planned is not None
    assert planned.additional_edits
    applied = apply_model_shortcut_edit(
        text,
        planned.replacement_start,
        planned.replacement_end,
        planned.replacement,
        planned.additional_edits,
    )
    assert applied == expected_text
    assert planned.caret_offset == expected_caret


async def test_equals_alias_accept_moves_value_to_existing_directive() -> None:
    """Accepting with a segment directive rewrites it and deletes the token."""
    app = ModelAliasCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()
        original = "%model:old Use =la"
        expanded = "%m:@large Use "
        ta.load_text(original)
        ta.cursor_location = (0, len(original))

        await pilot.press("ctrl+t")
        await pilot.press("ctrl+f")

        assert ta.text == expanded
        assert ta.cursor_location == (0, len("%m:@large "))
        assert app.submitted == []
        assert ta._file_completion_active is False
        assert ta._insert_g_prefix_pending is False

        await pilot.press("escape")
        await pilot.press("u")

        assert ta.text == original
        assert ta._file_completion_active is False

        await pilot.press("ctrl+r")

        assert ta.text == expanded
        assert ta._file_completion_active is False


async def test_equals_alias_accept_removes_adjacent_directive_and_undo_restores() -> (
    None
):
    """Accepting with adjacent directives leaves one; undo restores all."""
    app = ModelAliasCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()
        original = "=la %m:a %m:b"
        expanded = "%m:@large "
        ta.load_text(original)
        ta.cursor_location = (0, 3)

        await pilot.press("ctrl+t")
        await pilot.press("ctrl+f")

        assert ta.text == expanded
        assert ta.cursor_location == (0, len(expanded))
        assert ta.text.count("%m:") == 1
        assert app.submitted == []
        assert ta._file_completion_active is False
        assert ta._insert_g_prefix_pending is False

        await pilot.press("escape")
        await pilot.press("u")

        assert ta.text == original
        assert ta._file_completion_active is False

        await pilot.press("ctrl+r")

        assert ta.text == expanded
        assert ta._file_completion_active is False


async def test_unknown_equals_alias_stays_literal_and_can_submit() -> None:
    app = ModelAliasCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("=")
        await pilot.press("z")

        assert ta.text == "=z"
        assert ta._file_completion_active is False

        await pilot.press("enter")

        assert app.submitted == ["=z"]


async def test_legacy_star_alias_stays_literal_and_can_submit() -> None:
    app = ModelAliasCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("*")
        await pilot.press("l")

        assert ta.text == "*l"
        assert ta._file_completion_active is False

        await pilot.press("enter")

        assert app.submitted == ["*l"]


def test_equals_alias_context_rejects_protected_regions_and_unicode_columns() -> None:
    assert detect_model_alias_completion_context("🙂 =la", (0, 5)) is not None
    protected = [
        ("a=la", (0, 4)),
        ("path/=la", (0, 8)),
        (r"\=la", (0, 4)),
        ("`=la`", (0, 3)),
        ("```\n=la", (1, 3)),
        ("%model:=la", (0, 10)),
        ("{{ =la }}", (0, 6)),
        ("{% if =la %}", (0, 9)),
        ("---\nname: =la\n---\nbody", (1, 9)),
        ("---\nmodels:\n  - =la\n---\nbody", (2, 7)),
    ]
    for text, cursor in protected:
        assert detect_model_alias_completion_context(text, cursor) is None
