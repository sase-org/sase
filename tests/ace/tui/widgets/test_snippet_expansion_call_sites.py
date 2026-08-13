"""Regression coverage for snippet session policy at non-trigger call sites."""

from __future__ import annotations

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_completion import PromptSoftCompletion
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.xprompt_arg_assist import (
    ActiveXPromptArgHint,
    XPromptAssistEntry,
    XPromptInputHint,
)

from ._completion_helpers import CompletionTestApp


def _input(name: str, type_: str = "path") -> XPromptInputHint:
    return XPromptInputHint(
        name=name,
        type=type_,
        required=True,
        default_display=None,
        position=0,
    )


def _entry(name: str, *, inputs: tuple[XPromptInputHint, ...]) -> XPromptAssistEntry:
    return XPromptAssistEntry(
        name=name,
        insertion=f"#{name}",
        reference_prefix="#",
        kind="xprompt",
        input_signature=None,
        inputs=inputs,
        content_preview=None,
    )


def _start_outer_session(ta: PromptTextArea) -> None:
    ta.load_text("wrap")
    ta.cursor_location = (0, len("wrap"))
    assert ta._expand_snippet_template_at_range(
        "($1)$0",
        (0, 0),
        (0, len("wrap")),
        session_policy="nest",
    )
    assert ta.text == "()"
    assert ta.cursor_location == (0, 1)
    assert ta.snippet_session_active is True


def _insert_at_cursor(
    ta: PromptTextArea,
    text: str,
) -> tuple[tuple[int, int], tuple[int, int]]:
    start = ta.cursor_location
    ta._replace_via_keyboard(text, start, start)
    return start, ta.cursor_location


def _seed_entries(
    ta: PromptTextArea,
    entries: list[XPromptAssistEntry],
    project: str | None = None,
) -> None:
    ta._xprompt_arg_assist_entries_by_project[project] = entries


def _assert_nested_and_outer_resumes(ta: PromptTextArea) -> None:
    assert len(ta._snippet_session.sessions) == 2
    saw_outer_end = False
    for _ in range(5):
        if not ta.snippet_session_active:
            break
        advanced = ta._try_advance_tabstop()
        if not advanced:
            break
        saw_outer_end = saw_outer_end or (
            ta._absolute_offset(ta.cursor_location) == len(ta.text)
        )

    assert saw_outer_end is True
    assert ta._try_advance_tabstop() is False
    assert ta.snippet_session_active is False


async def test_file_completion_xprompt_skeleton_nests_inside_active_session() -> None:
    entry = _entry("many", inputs=(_input("path"), _input("body", "text")))
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        _start_outer_session(ta)
        _insert_at_cursor(ta, "#m")
        _seed_entries(ta, [entry])

        assert ta._try_file_completion_tab() is True

        assert ta.text == "(#many())"
        _assert_nested_and_outer_resumes(ta)


async def test_soft_completion_xprompt_skeleton_nests_inside_active_session() -> None:
    entry = _entry("many", inputs=(_input("path"), _input("body", "text")))
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        _start_outer_session(ta)
        start, end = _insert_at_cursor(ta, "#m")
        start_offset = ta._absolute_offset(start)
        end_offset = ta._absolute_offset(end)
        ta._soft_completion = PromptSoftCompletion(
            candidate=CompletionCandidate(
                display="review",
                insertion=entry.insertion,
                is_dir=False,
                name=entry.name,
                metadata=entry,
            ),
            completion_kind="xprompt",
            replacement_start=start_offset,
            replacement_end=end_offset,
            replacement_token="#m",
            display="#many",
        )

        original_blocked = ta._soft_completion_blocked
        ta._soft_completion_blocked = lambda: False  # type: ignore[method-assign]
        try:
            assert ta._accept_soft_completion() is True
        finally:
            ta._soft_completion_blocked = original_blocked  # type: ignore[method-assign]

        assert ta.text == "(#many())"
        _assert_nested_and_outer_resumes(ta)


async def test_ctrl_t_xprompt_skeleton_nests_inside_active_session() -> None:
    entry = _entry("many", inputs=(_input("path"), _input("body", "text")))
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        _start_outer_session(ta)
        _insert_at_cursor(ta, "#m")
        start = (0, 2)
        end = (0, 3)

        assert bar._insert_xprompt_smart_snippet(ta, entry, start, end) is True

        assert ta.text == "(#many())"
        _assert_nested_and_outer_resumes(ta)


async def test_named_arg_skeleton_nests_inside_active_session() -> None:
    entry = _entry("review", inputs=(_input("path"),))
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        _start_outer_session(ta)
        start, end = _insert_at_cursor(ta, "#review")
        start_offset = ta._absolute_offset(start)
        end_offset = ta._absolute_offset(end)
        ta._active_xprompt_arg_hint = ActiveXPromptArgHint(
            entry=entry,
            reference_start=start_offset,
            reference_end=end_offset,
            reference_text="#review",
        )

        assert ta._apply_xprompt_named_arg_hint() is True

        assert ta.text == "(#review(path=))"
        _assert_nested_and_outer_resumes(ta)


async def test_whole_pane_local_xprompt_skeleton_resets_active_session() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        _start_outer_session(ta)

        bar._replace_active_pane_with_skeleton("#_helper(arg=$1)$0", enter_insert=True)

        assert ta.text == "#_helper(arg=)"
        assert len(ta._snippet_session.sessions) == 1
        assert ta._try_advance_tabstop() is True
        assert ta.cursor_location == (0, len("#_helper(arg=)"))
        assert ta._try_advance_tabstop() is False
        assert ta.snippet_session_active is False
