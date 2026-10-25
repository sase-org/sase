"""Tests for the pure Rich question-round presenter."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text

from sase.ace.tui.models.agent_question_rounds import QuestionRoundStub
from sase.ace.tui.models.fold_state import FoldLevel
from sase.core.time import get_timezone
from sase.ace.tui.widgets.prompt_panel._agent_questions_render import (
    QuestionNumberCursor,
    question_rounds_heading_suffix,
    render_question_round,
    render_question_rounds,
)
from sase.question_gate_turn.projection import (
    NumberedQuestionRound,
    QuestionAnswerView,
    QuestionCancellationView,
    QuestionEntryView,
    QuestionOptionView,
    QuestionPolicyView,
    QuestionProvenanceView,
    QuestionRoundView,
)


def _now() -> datetime:
    return datetime(2026, 1, 15, 12, 0, 0)


def _unix(moment: datetime) -> float:
    """Interpret naive fixture wall time in the configured timezone.

    Fixture datetimes are naive Eastern wall times (see
    ``_pin_configured_timezone``); a bare ``.timestamp()`` would read them in
    the system timezone and drift whenever the system clock differs.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=get_timezone())
    return moment.timestamp()


_DEFAULT_ANSWER = QuestionAnswerView(selected=("Yes",))


def _entry(
    question: str = "Ship it?",
    *,
    header: str | None = "Release",
    options: tuple[QuestionOptionView, ...] = (
        QuestionOptionView(label="Yes", description="Ship today"),
        QuestionOptionView(label="No"),
    ),
    answer: QuestionAnswerView | None = _DEFAULT_ANSWER,
    recommendation_match: str | None = "followed",
    multi_select: bool = False,
) -> QuestionEntryView:
    return QuestionEntryView(
        question=question,
        header=header,
        options=options,
        multi_select=multi_select,
        recommended_index=0 if options else None,
        recommendation_basis="option_order" if options else "none",
        answer=answer,
        recommendation_match=recommendation_match,
    )


def _round(
    entries: tuple[QuestionEntryView, ...] = (_entry(),),
    *,
    status: str = "answered",
    gate_state: str = "answered",
    data_state: str = "complete",
    actor: str = "human",
    channel: str | None = "tui",
    policy: QuestionPolicyView | None = None,
    asked_at_unix: float | None = None,
    responded_at_unix: float | None = None,
    member_label: str = "gate",
    first_number: int = 1,
    deadline_unix: float | None = None,
    cancellation_reason: str | None = None,
    global_note: str | None = None,
) -> NumberedQuestionRound:
    asked = (
        _unix(datetime(2026, 1, 15, 11, 57, 0))
        if asked_at_unix is None
        else asked_at_unix
    )
    responded = (
        _unix(datetime(2026, 1, 15, 12, 0, 0))
        if responded_at_unix is None
        else responded_at_unix
    )
    return NumberedQuestionRound(
        view=QuestionRoundView(
            gate_id="question-abc123",
            status=status,
            data_state=data_state,
            asked_at_unix=asked,
            gate_state=gate_state,
            entries=entries,
            global_note=global_note,
            provenance=QuestionProvenanceView(
                channel=channel,
                actor=actor,
                policy=policy,
                responded_at_unix=responded,
            ),
            cancellation=None
            if cancellation_reason is None
            else QuestionCancellationView(reason=cancellation_reason),
        ),
        first_number=first_number,
        member_label=member_label,
        deadline_unix=deadline_unix,
    )


def test_heading_suffix_counts_rounds_and_awaiting() -> None:
    rounds = [
        _round(member_label="gate"),
        _round(member_label="gate-0"),
        _round(
            member_label="gate-1",
            status="pending",
            gate_state="pending",
        ),
    ]
    assert (
        question_rounds_heading_suffix(rounds).plain
        == " · 3 rounds · 1 awaiting answer"
    )


def test_heading_suffix_omits_zero_parts() -> None:
    assert question_rounds_heading_suffix([_round()]).plain == " · 1 round"
    assert question_rounds_heading_suffix([]).plain == ""


def test_heading_suffix_accepts_first_paint_stubs() -> None:
    def stub(gate_state: str | None) -> QuestionRoundStub:
        return QuestionRoundStub(
            gate_id="question-abc123",
            member_label="gate",
            gate_state=gate_state,
            gate_label="Ship it?",
            asked_at_unix=None,
            deadline_unix=None,
        )

    assert (
        question_rounds_heading_suffix([stub("pending"), stub("answered")]).plain
        == " · 2 rounds · 1 awaiting answer"
    )


def test_collapsed_renders_no_body() -> None:
    assert (
        render_question_rounds([_round()], level=FoldLevel.COLLAPSED, now=_now())
        == Text()
    )


def test_expanded_answered_round_uses_question_vocabulary() -> None:
    text = render_question_rounds([_round()], level=FoldLevel.EXPANDED, now=_now())

    assert isinstance(text, Text)
    plain = text.plain
    assert "ANSWERED" in plain
    assert "human via TUI" in plain
    assert "3m after asking" in plain
    assert "Q1 Release" in plain
    assert "Yes ★" in plain


def test_expanded_marks_skipped_recommendation() -> None:
    entry = _entry(
        answer=QuestionAnswerView(selected=("No",)),
        recommendation_match="different_option",
    )
    plain = render_question_rounds(
        [_round(entries=(entry,))], level=FoldLevel.EXPANDED, now=_now()
    ).plain
    assert "No ≠★" in plain


def test_expanded_pending_round_lists_options_with_recommended() -> None:
    asked = datetime(2026, 1, 15, 14, 2, 0)
    now = datetime(2026, 1, 15, 15, 2, 0)
    entry = _entry(answer=None)
    text = render_question_rounds(
        [
            _round(
                entries=(entry,),
                status="pending",
                gate_state="pending",
                actor="unknown",
                channel=None,
                asked_at_unix=_unix(asked),
                responded_at_unix=None,
                member_label="gate-1",
                deadline_unix=_unix(datetime(2026, 1, 16, 14, 2, 0)),
            )
        ],
        level=FoldLevel.EXPANDED,
        now=now,
    )

    plain = text.plain
    assert "QUESTION" in plain
    assert "awaiting answer" in plain
    assert "asked 14:02" in plain
    assert "23h left" in plain
    assert "★ Yes (recommended, listed first)" in plain
    assert "No" in plain
    assert "→" not in plain.split("Q1")[1].splitlines()[0]


def test_expanded_option_less_pending_names_free_text() -> None:
    entry = _entry(options=(), answer=None, recommendation_match=None)
    plain = render_question_rounds(
        [_round(entries=(entry,), status="pending", gate_state="pending")],
        level=FoldLevel.EXPANDED,
        now=_now(),
    ).plain
    assert "(free text, no recommendation)" in plain


def test_expanded_auto_policy_round_is_loud() -> None:
    policy = QuestionPolicyView(
        profile="standard", rule="gates.question", value="first"
    )
    plain = render_question_rounds(
        [_round(actor="auto_policy", policy=policy)],
        level=FoldLevel.EXPANDED,
        now=_now(),
    ).plain
    assert "⚠ auto policy (standard · gates.question=first) · no human" in plain


def test_expanded_answered_failed_gate_warns_follow_up() -> None:
    plain = render_question_rounds(
        [_round(status="answered", gate_state="failed")],
        level=FoldLevel.EXPANDED,
        now=_now(),
    ).plain
    assert "follow-up failed" in plain


def test_expanded_unknown_source_is_honest() -> None:
    plain = render_question_rounds(
        [_round(actor="unknown", channel=None)],
        level=FoldLevel.EXPANDED,
        now=_now(),
    ).plain
    assert "answered (source unknown)" in plain


def test_expanded_agent_actor_names_channel() -> None:
    plain = render_question_rounds(
        [_round(actor="agent", channel="cli")],
        level=FoldLevel.EXPANDED,
        now=_now(),
    ).plain
    assert "agent via cli" in plain


def test_expanded_unavailable_round_points_at_gate_show() -> None:
    plain = render_question_rounds(
        [_round(status="unknown", gate_state="pending", data_state="unavailable")],
        level=FoldLevel.EXPANDED,
        now=_now(),
    ).plain
    assert "answer details unavailable — sase gate show questi" in plain
    assert "ANSWERED" not in plain


def test_expanded_timeout_uses_cancel_vocabulary() -> None:
    plain = render_question_rounds(
        [
            _round(
                entries=(_entry(answer=None, recommendation_match=None),),
                status="timed_out",
                gate_state="timeout",
                actor="unknown",
                channel=None,
                cancellation_reason="timeout",
            )
        ],
        level=FoldLevel.EXPANDED,
        now=_now(),
    ).plain
    assert "QUESTION TIMED OUT" in plain
    assert "timeout" in plain


def test_expanded_multi_select_lists_every_label() -> None:
    entry = _entry(
        options=(
            QuestionOptionView(label="Red"),
            QuestionOptionView(label="Green"),
            QuestionOptionView(label="Blue"),
        ),
        answer=QuestionAnswerView(selected=("Red", "Blue")),
        recommendation_match="followed",
        multi_select=True,
    )
    plain = render_question_rounds(
        [_round(entries=(entry,))], level=FoldLevel.EXPANDED, now=_now()
    ).plain
    assert "Red, Blue ★" in plain


def test_expanded_other_text_shows_feedback_with_mismatch() -> None:
    entry = _entry(
        answer=QuestionAnswerView(selected=("Other",), custom_feedback="Need offline"),
        recommendation_match="other_text",
    )
    plain = render_question_rounds(
        [_round(entries=(entry,))], level=FoldLevel.EXPANDED, now=_now()
    ).plain
    assert '"Need offline" ≠★' in plain


def test_expanded_long_question_clips_to_one_line() -> None:
    long_question = "Why? " * 300
    entry = _entry(question=long_question, header=None, answer=None)
    text = render_question_rounds(
        [_round(entries=(entry,), status="pending", gate_state="pending")],
        level=FoldLevel.EXPANDED,
        now=_now(),
    )
    lines = [line for line in text.plain.splitlines() if "Q1" in line]
    assert len(lines) == 1
    assert lines[0].rstrip().endswith("…")


def test_fully_expanded_keeps_long_question_whole() -> None:
    long_question = "Why? " * 300
    entry = _entry(question=long_question, header=None, answer=None)
    plain = render_question_rounds(
        [_round(entries=(entry,), status="pending", gate_state="pending")],
        level=FoldLevel.FULLY_EXPANDED,
        now=_now(),
    ).plain
    assert "…" not in plain.split("Q1")[1].split("Note:")[0]
    assert long_question.strip() in plain


def test_fully_expanded_shows_descriptions_comment_note_and_times() -> None:
    entry = _entry(
        answer=QuestionAnswerView(selected=("No",), custom_feedback="Need offline"),
        recommendation_match="different_option",
    )
    plain = render_question_rounds(
        [_round(entries=(entry,), global_note="Ship only on green")],
        level=FoldLevel.FULLY_EXPANDED,
        now=_now(),
    ).plain
    assert "Ship today" in plain
    assert '- Comment: "Need offline"' in plain
    assert 'Note: "Ship only on green"' in plain
    assert "Asked: 2026-01-15" in plain
    assert "Answered: 2026-01-15" in plain


def test_cursor_accumulates_first_numbers() -> None:
    cursor = QuestionNumberCursor()
    assert cursor.take(2) == 1
    assert cursor.take(1) == 3
    assert cursor.next_number == 4


def test_single_round_helper_matches_multi() -> None:
    voted = _round(first_number=4)
    assert (
        render_question_round(voted, level=FoldLevel.EXPANDED, now=_now()).plain
        == render_question_rounds([voted], level=FoldLevel.EXPANDED, now=_now()).plain
    )
