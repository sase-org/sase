"""Tests for the shared Q&A markdown formatter and prompt-section formatter."""

from __future__ import annotations

from sase.axe.run_agent_helpers import format_qa_for_prompt
from sase.main.qa_markdown import build_qa_markdown


def _q(question, options, header="", multi=False):
    return {
        "question": question,
        "options": [{"label": lbl, "description": desc} for lbl, desc in options],
        "header": header,
        "multiSelect": multi,
    }


def test_single_select_shows_checked_and_unchecked() -> None:
    q = _q("Pick one", [("A: foo", "first"), ("B: bar", "second")])
    response = {
        "answers": [{"selected": ["B: bar"], "custom_feedback": None}],
        "global_note": "",
    }
    out = format_qa_for_prompt([q], response)
    assert "- [ ] **A: foo** — first" in out
    assert "- [x] **B: bar** — second" in out
    assert "*Multi-select*" not in out


def test_multi_select_marks_indicator_and_multiple_checks() -> None:
    q = _q(
        "Pick many",
        [("A", "a"), ("B", "b"), ("C", "c")],
        multi=True,
    )
    response = {
        "answers": [{"selected": ["A", "C"], "custom_feedback": None}],
        "global_note": "",
    }
    out = format_qa_for_prompt([q], response)
    assert "- [x] **A**" in out
    assert "- [ ] **B**" in out
    assert "- [x] **C**" in out
    assert "*Multi-select*" in out


def test_other_with_custom_feedback_renders_quoted_line() -> None:
    q = _q("Pick", [("A", "a")])
    response = {
        "answers": [{"selected": ["Other"], "custom_feedback": "free-form text"}],
        "global_note": "",
    }
    out = format_qa_for_prompt([q], response)
    assert '- [x] **Other:** "free-form text"' in out


def test_other_without_custom_feedback() -> None:
    q = _q("Pick", [("A", "")])
    response = {
        "answers": [{"selected": ["Other"], "custom_feedback": ""}],
        "global_note": "",
    }
    out = format_qa_for_prompt([q], response)
    assert "- [x] **Other**" in out
    assert '"Other:"' not in out


def test_question_header_renders() -> None:
    q = _q("Pick", [("A", "")], header="My Header")
    out = format_qa_for_prompt(
        [q], {"answers": [{"selected": ["A"]}], "global_note": ""}
    )
    assert "#### Q1: My Header" in out


def test_question_without_header() -> None:
    q = _q("Pick", [("A", "")])
    out = format_qa_for_prompt(
        [q], {"answers": [{"selected": ["A"]}], "global_note": ""}
    )
    assert "#### Q1\n" in out
    assert "#### Q1: " not in out


def test_global_note_appears_under_divider() -> None:
    q = _q("Pick", [("A", "")])
    out = format_qa_for_prompt(
        [q],
        {"answers": [{"selected": ["A"]}], "global_note": "be careful"},
    )
    assert "---" in out
    assert "> **Global Note:** be careful" in out


def test_global_note_omitted_when_empty() -> None:
    q = _q("Pick", [("A", "")])
    out = format_qa_for_prompt(
        [q], {"answers": [{"selected": ["A"]}], "global_note": ""}
    )
    assert "Global Note" not in out
    assert "---" not in out


def test_legacy_string_selected_still_renders() -> None:
    q = _q("Pick", [("A", "alpha"), ("B", "beta")])
    response = {
        "answers": [{"selected": "B", "custom_feedback": None}],
        "global_note": "",
    }
    out = format_qa_for_prompt([q], response)
    assert "- [ ] **A** — alpha" in out
    assert "- [x] **B** — beta" in out


def test_unknown_selected_label_is_surfaced() -> None:
    q = _q("Pick", [("A", "alpha"), ("B", "beta")])
    response = {
        "answers": [{"selected": ["Z: stale"], "custom_feedback": None}],
        "global_note": "",
    }
    out = format_qa_for_prompt([q], response)
    # Known options remain unchecked.
    assert "- [ ] **A** — alpha" in out
    assert "- [ ] **B** — beta" in out
    # Stale label is surfaced as a synthetic checked entry.
    assert "- [x] **Z: stale**" in out


def test_question_text_rendered_as_blockquote() -> None:
    q = _q("line one\nline two", [("A", "")])
    out = format_qa_for_prompt(
        [q], {"answers": [{"selected": ["A"]}], "global_note": ""}
    )
    assert "> line one" in out
    assert "> line two" in out


def test_build_qa_markdown_direct_matches_format_qa_for_prompt() -> None:
    q = _q("Pick", [("A", "a"), ("B", "b")], header="hdr", multi=True)
    questions = [q]
    answers = [{"selected": ["A"], "custom_feedback": None}]

    direct = build_qa_markdown(questions=questions, answers=answers, global_note="note")
    via_response = format_qa_for_prompt(
        questions, {"answers": answers, "global_note": "note"}
    )
    assert direct == via_response


def test_length_mismatch_falls_back_to_text_match() -> None:
    q1 = _q("First?", [("A", "")])
    q2 = _q("Second?", [("X", "")])
    # Response only has one answer (mismatch), keyed by question text.
    response = {
        "answers": [
            {"question": "Second?", "selected": ["X"], "custom_feedback": None}
        ],
        "global_note": "",
    }
    out = format_qa_for_prompt([q1, q2], response)
    assert "- [ ] **A**" in out  # q1: not answered
    assert "- [x] **X**" in out  # q2: matched by text


def test_tui_modal_preview_matches_prompt_section() -> None:
    """The TUI modal's preview and the prompt-section output are byte-identical
    for the same inputs (since both delegate to ``build_qa_markdown``)."""
    from sase.ace.tui.modals.user_question_modal import (
        UserQuestionModal,
        _QuestionAnswer,
    )

    q = _q(
        "Pick one",
        [("A", "alpha"), ("B", "beta")],
        header="Choose",
        multi=False,
    )
    questions = [q]

    modal = UserQuestionModal.__new__(UserQuestionModal)
    modal._questions = questions
    modal._answers = {0: _QuestionAnswer(question="Pick one", selected=["A"])}
    modal._other_text = {}
    modal._global_note = "note"

    tui_out = modal._build_qa_markdown()
    prompt_out = format_qa_for_prompt(
        questions,
        {
            "answers": [{"selected": ["A"], "custom_feedback": None}],
            "global_note": "note",
        },
    )
    assert tui_out == prompt_out
