"""Edit-plan and literal-text tests for ``==model`` model completion.

Split from ``test_model_explicit_completion``; shared helpers live in
``_model_explicit_completion_shared`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets._model_shortcut_edits import apply_model_shortcut_edit
from sase.ace.tui.widgets.model_explicit_completion import (
    build_model_explicit_completion_candidates,
    detect_model_explicit_completion_context,
    plan_model_explicit_completion_edit,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

from ._model_explicit_completion_shared import (
    ModelExplicitCompletionTestApp,
    explicit_entries,
)

__all__ = [
    "test_double_equals_accept_moves_value_to_existing_directive",
    "test_double_equals_accept_removes_adjacent_directive_and_undo_restores",
    "test_double_equals_context_and_filtering_use_model_rows_only",
    "test_double_equals_context_rejects_protected_regions",
    "test_double_equals_edit_plan_applies_segment_replacement",
    "test_double_equals_edit_plan_spacer_cases",
    "test_legacy_double_star_stays_literal_and_can_submit",
    "test_unknown_double_equals_stays_literal_and_can_submit",
]


def test_double_equals_context_and_filtering_use_model_rows_only() -> None:
    context = detect_model_explicit_completion_context("Review ==gp", (0, 11))

    assert context is not None
    assert context.query == "gp"
    assert context.token == "==gp"
    assert [
        candidate.insertion
        for candidate in build_model_explicit_completion_candidates(
            context,
            explicit_entries(),
        )
    ] == ["gpt-5.6-sol"]

    scoped = detect_model_explicit_completion_context("Review ==codex/g", (0, 16))
    assert scoped is not None
    assert [
        candidate.insertion
        for candidate in build_model_explicit_completion_candidates(
            scoped,
            explicit_entries(),
        )
    ] == ["codex/gpt-5.6-sol"]

    short_hint = detect_model_explicit_completion_context("Review ==fable", (0, 14))
    assert short_hint is not None
    assert [
        candidate.insertion
        for candidate in build_model_explicit_completion_candidates(
            short_hint,
            explicit_entries(),
        )
    ] == ["claude-fable-5"]


def test_double_equals_edit_plan_spacer_cases() -> None:
    cases = [
        ("Use ==gp", (0, 8), "Use %m:gpt-5.6-sol ", "%m:gpt-5.6-sol "),
        ("Use ==gp now", (0, 8), "Use %m:gpt-5.6-sol now", "%m:gpt-5.6-sol "),
        ("Use ==gp\tnow", (0, 8), "Use %m:gpt-5.6-sol\tnow", "%m:gpt-5.6-sol"),
        (
            "Title\r\nUse ==gp",
            (1, len("Use ==gp")),
            "Title\r\nUse %m:gpt-5.6-sol ",
            "%m:gpt-5.6-sol ",
        ),
        ("🙂 ==gp\r\nnext", (0, 6), "🙂 %m:gpt-5.6-sol \r\nnext", "%m:gpt-5.6-sol "),
    ]
    for text, cursor, expected_text, expected_replacement in cases:
        context = detect_model_explicit_completion_context(text, cursor)
        assert context is not None
        selected = build_model_explicit_completion_candidates(
            context,
            explicit_entries(),
        )[0]
        planned = plan_model_explicit_completion_edit(
            text,
            cursor,
            explicit_entries(),
            selected,
        )

        assert planned is not None
        assert planned.replacement == expected_replacement
        applied = (
            f"{text[: planned.replacement_start]}"
            f"{planned.replacement}"
            f"{text[planned.replacement_end :]}"
        )
        assert applied == expected_text
        assert planned.caret_offset == planned.replacement_start + len(
            planned.replacement
        )


@pytest.mark.parametrize(
    ("text", "cursor", "expected_text", "expected_caret"),
    [
        ("%model:old Use ==gp", (0, 19), "%m:gpt-5.6-sol Use ", 15),
        ("Use ==gp then %m:old", (0, 8), "Use then %m:gpt-5.6-sol ", 24),
    ],
)
def test_double_equals_edit_plan_applies_segment_replacement(
    text: str,
    cursor: tuple[int, int],
    expected_text: str,
    expected_caret: int,
) -> None:
    """A standalone directive in the trigger's segment takes the value."""
    context = detect_model_explicit_completion_context(text, cursor)
    assert context is not None
    selected = build_model_explicit_completion_candidates(
        context,
        explicit_entries(),
    )[0]
    planned = plan_model_explicit_completion_edit(
        text,
        cursor,
        explicit_entries(),
        selected,
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


async def test_double_equals_accept_moves_value_to_existing_directive() -> None:
    """Accepting with a segment directive rewrites it and deletes the token."""
    app = ModelExplicitCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()
        original = "%model:old Use ==gp"
        expanded = "%m:gpt-5.6-sol Use "
        ta.load_text(original)
        ta.cursor_location = (0, len(original))

        await pilot.press("ctrl+t")
        await pilot.press("ctrl+f")

        assert ta.text == expanded
        assert ta.cursor_location == (0, len("%m:gpt-5.6-sol "))
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


async def test_double_equals_accept_removes_adjacent_directive_and_undo_restores() -> (
    None
):
    """Accepting with adjacent directives leaves one; undo restores all."""
    app = ModelExplicitCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()
        original = "==gp %m:a %m:b"
        expanded = "%m:gpt-5.6-sol "
        ta.load_text(original)
        ta.cursor_location = (0, 4)

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


async def test_unknown_double_equals_stays_literal_and_can_submit() -> None:
    app = ModelExplicitCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("=")
        await pilot.press("=")
        await pilot.press("z")
        await pilot.press("z")

        assert ta.text == "==zz"
        assert ta._file_completion_active is False

        await pilot.press("enter")

        assert app.submitted == ["==zz"]


async def test_legacy_double_star_stays_literal_and_can_submit() -> None:
    app = ModelExplicitCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("*")
        await pilot.press("*")
        await pilot.press("g")

        assert ta.text == "**g"
        assert ta._file_completion_active is False

        await pilot.press("enter")

        assert app.submitted == ["**g"]


def test_double_equals_context_rejects_protected_regions() -> None:
    protected = [
        ("a==gp", (0, 5)),
        ("path/==gp", (0, 9)),
        (r"\==gp", (0, 5)),
        ("`==gp`", (0, 4)),
        ("```\n==gp", (1, 4)),
        ("%model:==gp", (0, 11)),
        ("{{ ==gp }}", (0, 7)),
        ("{% if ==gp %}", (0, 10)),
        ("---\nname: ==gp\n---\nbody", (1, 10)),
        ("===gp", (0, 5)),
        ("==bold==", (0, 4)),
    ]
    for text, cursor in protected:
        assert detect_model_explicit_completion_context(text, cursor) is None
