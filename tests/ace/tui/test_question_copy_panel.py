"""Copy-panel behavior for the user-question modal."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from textual.app import App
from textual.widgets import SelectionList

from sase.ace.tui.actions.clipboard._delivery import CopyDeliveryOutcome
from sase.ace.tui.modals.copy_as_types import CopyAsRow
from sase.ace.tui.modals.question_copy_items import (
    RESERVED_PANEL_KEYS,
    SNIPPET_KEY_POOL,
    QuestionCopySnapshot,
    _allocate_snippet_keys,
    build_question_copy_context,
    _first_line_summary,
    _row_preview_for_value,
    toast_label_for_target,
    _truncate_preview_text,
)
from sase.ace.tui.modals.question_copy_modal import QuestionCopyModal
from sase.ace.tui.modals.user_question_modal import UserQuestionModal
from sase.core.question_copy_facade import QuestionCopyItem
from sase.main.qa_markdown import build_qa_markdown


def _items(n: int) -> tuple[QuestionCopyItem, ...]:
    return tuple(QuestionCopyItem(text=f"/tmp/value-{i}") for i in range(n))


def _snapshot(
    items: tuple[QuestionCopyItem, ...] = (),
    *,
    copied: frozenset[str] = frozenset(),
    unavailable: int = 0,
    highlighted_label: str | None = "Done",
    highlighted_description: str | None = "Did it",
    is_other: bool = False,
    has_options: bool = True,
    header: str = "Mac GUI",
    question_text: str = "What did you do?",
    qa_value: str = "QA",
) -> QuestionCopySnapshot:
    return QuestionCopySnapshot(
        question_index=0,
        total_questions=1,
        header=header,
        question_text=question_text,
        highlighted_label=highlighted_label,
        highlighted_description=highlighted_description,
        highlighted_is_other=is_other,
        has_options=has_options,
        items=items,
        unavailable=unavailable,
        copied_texts=copied,
        qa_value=qa_value,
    )


def test_snippet_key_pool_has_29_keys_and_reserves_panel_keys() -> None:
    assert len(SNIPPET_KEY_POOL) == 29
    assert len(set(SNIPPET_KEY_POOL)) == 29
    assert not (set(SNIPPET_KEY_POOL) & RESERVED_PANEL_KEYS)
    for reserved in ("a", "j", "k", "o", "q", "t", "y"):
        assert reserved not in SNIPPET_KEY_POOL


def test_key_map_covers_20_declared_plus_5_detected() -> None:
    keys = _allocate_snippet_keys(25)
    assert len(keys) == 25
    assert len(set(keys)) == 25
    assert not (set(keys) & RESERVED_PANEL_KEYS)


def test_truncate_middle_keeps_root_and_tail() -> None:
    long_path = "/Users/bbugyi/projects/github/bobs-org/bob-cli/target/nested/deep"
    out = _truncate_preview_text(long_path, 40)
    assert len(out) <= 40
    assert out.startswith("/Users/…")
    assert out.endswith("target/nested/deep"[-38:])


def test_truncate_end_for_non_paths() -> None:
    out = _truncate_preview_text("x" * 60)
    assert out.endswith("…")
    assert len(out) == 48


def test_multiline_first_line_summary_with_badge() -> None:
    preview, badge = _row_preview_for_value("first\nsecond\nthird")
    assert preview == "first"
    assert badge == "+2 lines"
    preview, badge = _row_preview_for_value("\n\n  \nrun this")
    assert preview == "run this"
    assert badge is None


def test_toast_labels() -> None:
    item = QuestionCopyItem(text="/tmp/x", label="My label")
    snap = _snapshot((item,))
    row = CopyAsRow(
        key="1", key_display="1", target=f"snippet:{item.text}", label="My label"
    )
    assert toast_label_for_target(row.target, snap, row) == "My label"
    unlabeled = QuestionCopyItem(text="/tmp/long-value-here")
    snap2 = _snapshot((unlabeled,))
    row2 = CopyAsRow(
        key="1", key_display="1", target=f"snippet:{unlabeled.text}", label=""
    )
    assert toast_label_for_target(row2.target, snap2, row2) == "/tmp/long-value-here"
    assert toast_label_for_target("all", _snapshot(_items(8))) == "8 snippets"
    assert toast_label_for_target("question", snap) == "question text"
    assert toast_label_for_target("option:Done", snap) == 'option "Done"'
    assert toast_label_for_target("qa", snap) == "questions & answers"


def test_yy_byte_identical_without_copy() -> None:
    questions = [
        {
            "header": "H",
            "question": "Pick?",
            "options": [{"label": "A", "description": "a"}],
        }
    ]
    answers = [{"selected": ["A"], "custom_feedback": None}]
    plain = build_qa_markdown(questions=questions, answers=answers, global_note=None)
    with_copy = build_qa_markdown(
        questions=questions,
        answers=answers,
        global_note=None,
        include_copy_items=True,
    )
    assert plain == with_copy
    assert "Copyable items" not in plain


def test_yy_adds_copyable_section_with_copy() -> None:
    questions = [
        {
            "header": "H",
            "question": "Paste where?",
            "options": [{"label": "A"}],
            "copy": [
                {"text": "/tmp/with space/path", "label": "Target"},
                {"text": "single"},
            ],
        }
    ]
    answers = [{"selected": ["A"], "custom_feedback": None}]
    out = build_qa_markdown(
        questions=questions,
        answers=answers,
        global_note=None,
        include_copy_items=True,
    )
    assert "**Copyable items:**" in out
    assert "/tmp/with space/path" in out
    assert "` single `" in out
    plain = build_qa_markdown(questions=questions, answers=answers, global_note=None)
    assert "Copyable items" not in plain


def test_copyable_multiline_uses_fenced_block() -> None:
    questions = [
        {
            "question": "Run?",
            "options": [{"label": "A"}],
            "copy": [{"text": "line one\nline two", "label": "Cmd"}],
        }
    ]
    out = build_qa_markdown(
        questions=[questions[0]],
        answers=[{"selected": ["A"]}],
        global_note=None,
        include_copy_items=True,
    )
    assert "```" in out
    assert "line one\nline two" in out


def test_exactness_matrix_row_values_are_byte_exact() -> None:
    tricky = [
        "/Users/bbugyi/Library/Application Support/sase",
        "chrome://settings/performance",
        "[/]",
        "\"quoted\" and 'single'",
        "ünïcödé ✓",
        "col\there",
        "line one\nline two\n  indented",
        "`backtick` value",
        "[bold]x",
    ]
    items = tuple(QuestionCopyItem(text=value) for value in tricky)
    ctx = build_question_copy_context(_snapshot(items))
    by_target = {row.target: row for row in ctx.rows}
    for value in tricky:
        row = by_target[f"snippet:{value}"]
        assert row.value == value


def test_option_disabled_reasons() -> None:
    no_options = build_question_copy_context(_snapshot((), has_options=False))
    option_row = next(r for r in no_options.rows if r.key == "o")
    assert option_row.disabled_reason == "No options to copy"

    other = build_question_copy_context(
        _snapshot((), highlighted_label=None, is_other=True)
    )
    other_row = next(r for r in other.rows if r.key == "o")
    assert other_row.disabled_reason == "Other answer is typed, not copyable"


def test_unavailable_row_is_informational_and_disabled() -> None:
    ctx = build_question_copy_context(_snapshot((), unavailable=2))
    rows = [r for r in ctx.rows if r.target == "unavailable"]
    assert len(rows) == 1
    assert rows[0].disabled_reason == "2 snippets unavailable — malformed copy metadata"


def test_initial_highlight_states() -> None:
    items = _items(3)
    partial = build_question_copy_context(
        _snapshot(items, copied=frozenset({items[0].text}))
    )
    assert partial.initial_row_key == "2"
    everything = build_question_copy_context(
        _snapshot(items, copied=frozenset(i.text for i in items))
    )
    assert everything.initial_row_key == "y"
    empty = build_question_copy_context(_snapshot(()))
    assert empty.initial_row_key == "y"
    first = build_question_copy_context(_snapshot(items))
    assert first.initial_row_key == "1"


def test_markup_safety_label_and_value() -> None:
    item = QuestionCopyItem(text="[bold]x", label="[/]")
    ctx = build_question_copy_context(_snapshot((item,)))
    row = next(r for r in ctx.rows if r.target.startswith("snippet:"))
    assert row.value == "[bold]x"
    assert row.label == "[/]"


class _QuestionApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, questions: list[dict[str, Any]], **kwargs: Any) -> None:
        super().__init__()
        self._questions = questions
        self._modal_kwargs = kwargs
        self.copied: list[str] = []

    def on_mount(self) -> None:
        self.push_screen(UserQuestionModal(self._questions, **self._modal_kwargs))


def _spotlight_questions() -> list[dict[str, Any]]:
    return [
        {
            "header": "Mac GUI",
            "question": "What did you do?",
            "options": [
                {"label": "Done, both", "description": "Added folders"},
                {"label": "Skip for now"},
            ],
            "copy": [
                {"text": "/Users/bbugyi/.sase", "label": ".sase"},
                {"text": "/Users/bbugyi/.cargo"},
            ],
        }
    ]


async def test_y_opens_panel_and_enter_copies_exact_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda content: copied.append(content) is None or True,
    )
    app = _QuestionApp(_spotlight_questions())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, UserQuestionModal)
        await pilot.press("y")
        await pilot.pause()
        panel = app.screen_stack[-1]
        assert isinstance(panel, QuestionCopyModal)
        await pilot.press("enter")
        await pilot.pause()
        assert copied == ["/Users/bbugyi/.sase"]
        assert isinstance(app.screen_stack[-1], UserQuestionModal)


async def test_y_in_other_and_global_inputs_types_y() -> None:
    app = _QuestionApp(_spotlight_questions())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, UserQuestionModal)
        modal.action_global_note()
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert isinstance(app.screen_stack[-1], UserQuestionModal)
        assert not any(
            isinstance(screen, QuestionCopyModal) for screen in app.screen_stack
        )


async def test_y_with_app_copy_mode_active_does_not_open_panel() -> None:
    app = _QuestionApp(_spotlight_questions())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app._copy_mode_active = True  # type: ignore[attr-defined]
        await pilot.press("y")
        await pilot.pause()
        assert not any(
            isinstance(screen, QuestionCopyModal) for screen in app.screen_stack
        )


async def test_esc_closes_one_layer_and_focus_returns() -> None:
    app = _QuestionApp(_spotlight_questions())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, UserQuestionModal)
        await pilot.press("y")
        await pilot.pause()
        assert isinstance(app.screen_stack[-1], QuestionCopyModal)
        await pilot.press("escape")
        await pilot.pause()
        top = app.screen_stack[-1]
        assert isinstance(top, UserQuestionModal)
        assert isinstance(app.focused, SelectionList)


async def test_form_state_survives_panel() -> None:
    app = _QuestionApp(_spotlight_questions())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, UserQuestionModal)
        modal._global_note = "keep me"
        modal._other_text[0] = "draft"
        await pilot.press("y")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert modal._global_note == "keep me"
        assert modal._other_text[0] == "draft"
        assert modal._current_idx == 0


async def test_checkmark_persists_across_reopen_for_same_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda _content: True,
    )
    app = _QuestionApp(_spotlight_questions(), copy_bundle_key="/tmp/bundle-a")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, UserQuestionModal)
        await pilot.press("y")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        modal2 = app.screen_stack[-1]
        assert isinstance(modal2, UserQuestionModal)
        snapshot = modal2._build_question_copy_snapshot()
        ctx = build_question_copy_context(snapshot)
        first = next(r for r in ctx.rows if r.key == "1")
        assert first.marker == "✓"
        assert "1 of 2 snippets copied" in ctx.subtitle


async def test_failed_delivery_sets_no_checkmark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes: list[Any] = []

    def _fake_schedule(
        owner: object,
        value: Any,
        *,
        copied_label: Any,
        task_name: str,
        ordered: bool = False,
    ) -> Any:
        assert ordered is True

        async def _failed() -> CopyDeliveryOutcome:
            return CopyDeliveryOutcome.FAILED

        task = asyncio.ensure_future(_failed())

        def _record(done: Any) -> None:
            try:
                outcomes.append(done.result())
            except Exception:
                pass

        task.add_done_callback(_record)
        return task

    monkeypatch.setattr(
        "sase.ace.tui.modals.user_question_modal_copying.schedule_copy_delivery",
        _fake_schedule,
    )
    app = _QuestionApp(_spotlight_questions(), copy_bundle_key="/tmp/bundle-fail")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, UserQuestionModal)
        snapshot = modal._build_question_copy_snapshot()
        ctx = build_question_copy_context(snapshot)
        row = next(r for r in ctx.rows if r.key == "1")
        modal._dispatch_question_copy_row(row, snapshot)
        await pilot.pause()
        await pilot.pause()
        assert modal._question_copied_texts() == set()


async def test_ordered_delivery_seam_keeps_chosen_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.actions.clipboard import schedule_copy_delivery as seam

    order: list[str] = []

    async def _slow(value: str) -> bool:
        await asyncio.sleep(0.05)  # sase-test-wait: slow first delivery
        order.append(value)
        return True

    async def _fast(value: str) -> bool:
        order.append(value)
        return True

    calls = iter([_slow, _fast])
    real_to_thread = asyncio.to_thread

    async def _fake_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
        if func.__name__ == "copy_to_system_clipboard":
            return await next(calls)(*args)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery._emit_osc52",
        lambda _owner, _value: False,
    )

    class _Owner:
        pass

    owner = _Owner()
    owner.app = owner  # type: ignore[attr-defined]

    async with App[None]().run_test() as pilot:
        _ = pilot
        first = seam(owner, "first", copied_label="first", task_name="t1", ordered=True)
        second = seam(
            owner, "second", copied_label="second", task_name="t2", ordered=True
        )
        assert first is not None and second is not None
        await asyncio.wait_for(asyncio.gather(first, second), timeout=5)
    assert order == ["first", "second"]
