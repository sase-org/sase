"""QUESTIONS section mount tests (phase `context-section`).

The Context card shows a QUESTIONS section ahead of OUTPUT VARIABLES when
the selected session container, asking turn, or gate row has question
rounds in scope. Before the ``questions`` lane resolves, the section first
paints from zero-I/O stubs; once ready, it renders the lane's rounds
through the Rich presenter. Gate rows keep only the shared GATE fields in
their GATE section; the round body lives in QUESTIONS.
"""

from __future__ import annotations

from datetime import datetime

from rich.text import Text

from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from sase.ace.tui.widgets.prompt_panel._agent_gate_section import build_gate_section
from sase.ace.tui.widgets.prompt_panel._agent_questions_section import (
    QUESTIONS_SECTION_ID,
    append_agent_questions_section,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
    DetailHeaderSummary,
)
from sase.core.time import get_timezone
from sase.question_gate_turn.projection import (
    NumberedQuestionRound,
    QuestionAnswerView,
    QuestionEntryView,
    QuestionOptionView,
    QuestionProvenanceView,
    QuestionRoundView,
)
from tests.ace.tui.models._agent_session_members_helpers import (
    make_agent as make_member,
    make_gate_member,
)
from tests.ace.tui.widgets._agent_display_metadata_helpers import (
    assert_dim_divider_before,
)

_NOW = datetime(2026, 7, 19, 12, 0, 0)


def _unix(moment: datetime) -> float:
    """Interpret naive fixture wall time in the configured timezone."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=get_timezone())
    return moment.timestamp()


def _question_session() -> tuple[object, object, object, object, object]:
    """Build a container with one answered and one pending question round."""
    root = make_member("alpha--0", role="root")
    plan = make_member("alpha--plan", role="plan", parent_timestamp=root.raw_suffix)
    first = make_member("alpha--1", role="1", parent_timestamp=root.raw_suffix)
    root.followup_agents = [plan, first]

    gate = make_gate_member(
        "alpha--gate", root=plan, gate_id="g0", gate_state="answered"
    )
    gate.gate_kind = "question"
    gate.gate_creator_agent = "alpha--plan"
    gate.gate_label = "Ship it?"
    plan.runtime_children = [gate]

    gate0 = make_gate_member(
        "alpha--gate-0", root=first, gate_id="g1", gate_state="pending"
    )
    gate0.gate_kind = "question"
    gate0.gate_creator_agent = "alpha--1"
    gate0.role_suffix = "--gate-0"
    gate0.gate_label = "Roll back?"
    first.runtime_children = [gate0]

    for member in (plan, first, gate, gate0):
        member.agent_session_container = root
    return root, plan, first, gate, gate0


def _answered_round() -> NumberedQuestionRound:
    view = QuestionRoundView(
        gate_id="g0",
        status="answered",
        data_state="complete",
        gate_state="answered",
        asked_at_unix=_unix(_NOW) - 180,
        entries=(
            QuestionEntryView(
                index=0,
                header="Deploy",
                question="Ship it?",
                options=(
                    QuestionOptionView(label="Yes"),
                    QuestionOptionView(label="No"),
                ),
                recommended_index=0,
                recommendation_basis="option_order",
                answer=QuestionAnswerView(selected=("Yes",)),
                recommendation_match="followed",
            ),
        ),
        provenance=QuestionProvenanceView(
            channel="tui",
            actor="human",
            responded_at_unix=_unix(_NOW),
        ),
    )
    return NumberedQuestionRound(view=view, first_number=1, member_label="gate")


def _pending_round() -> NumberedQuestionRound:
    view = QuestionRoundView(
        gate_id="g1",
        status="pending",
        data_state="complete",
        gate_state="pending",
        asked_at_unix=_unix(_NOW) - 60,
        entries=(
            QuestionEntryView(
                index=0,
                question="Roll back?",
                options=(
                    QuestionOptionView(label="Yes"),
                    QuestionOptionView(label="No"),
                ),
                recommended_index=0,
                recommendation_basis="option_order",
            ),
        ),
    )
    return NumberedQuestionRound(
        view=view,
        first_number=2,
        member_label="gate-0",
        deadline_unix=_unix(_NOW) + 3600,
    )


def _ready_summary(*rounds: NumberedQuestionRound) -> DetailHeaderSummary:
    return DetailHeaderSummary(
        question_rounds=tuple(rounds),
        ready_lanes=frozenset({"questions"}),
    )


def _section_id_spans(header: Text, section_id: str) -> int:
    from sase.ace.tui.widgets.prompt_panel._helpers import SECTION_MARKER_META_KEY

    count = 0
    for span in header.spans:
        meta = getattr(span.style, "meta", None) or {}
        if meta.get(SECTION_MARKER_META_KEY) == section_id:
            count += 1
    return count


def test_no_section_without_question_rows() -> None:
    header, _ = build_header_text(make_member("solo--0", role="root"), cheap=True)

    assert "QUESTIONS" not in header.plain


def test_container_first_paint_shows_stub_lines() -> None:
    root, _plan, _first, _gate, _gate0 = _question_session()

    header, _ = build_header_text(root, cheap=True)
    plain = header.plain

    assert "QUESTIONS · 2 rounds · 1 awaiting answer\n" in plain
    assert "gate    QUESTION" not in plain
    assert "gate    ANSWERED  Ship it?\n" in plain
    assert "gate-0  QUESTION  Roll back?\n" in plain
    assert_dim_divider_before(header, "QUESTIONS · 2 rounds · 1 awaiting answer\n")
    assert _section_id_spans(header, QUESTIONS_SECTION_ID) == 1


def test_container_ready_renders_presenter_body() -> None:
    root, _plan, _first, _gate, _gate0 = _question_session()

    header, _ = build_header_text(
        root, cheap=False, summary=_ready_summary(_answered_round(), _pending_round())
    )
    plain = header.plain

    assert "QUESTIONS · 2 rounds · 1 awaiting answer\n" in plain
    assert "human via TUI" in plain
    assert "Q1 Deploy → Yes ★" in plain
    assert "Q2 Roll back?" in plain


def test_questions_mounts_before_output_variables() -> None:
    root, _plan, _first, _gate, _gate0 = _question_session()
    root.output_variables = {"plan_path": "/tmp/plan.md"}

    header, _ = build_header_text(
        root, cheap=False, summary=_ready_summary(_answered_round(), _pending_round())
    )
    plain = header.plain

    assert "QUESTIONS" in plain
    assert "OUTPUT VARIABLES" in plain
    assert plain.index("QUESTIONS") < plain.index("OUTPUT VARIABLES")


def _questions_body(plain: str) -> str:
    """Slice the QUESTIONS section body out of a rendered header."""
    start = plain.index("QUESTIONS")
    end = plain.index("─" * 50, start)
    return plain[start:end]


def test_asking_turn_sees_only_its_round() -> None:
    _root, plan, _first, _gate, _gate0 = _question_session()

    header, _ = build_header_text(plan, cheap=True)
    plain = header.plain

    assert "QUESTIONS · 1 round\n" in plain
    body = _questions_body(plain)
    assert "Ship it?" in body
    assert "Roll back?" not in body


def test_gate_row_sees_only_its_round() -> None:
    _root, _plan, _first, gate, _gate0 = _question_session()

    header, _ = build_header_text(gate, cheap=True)
    plain = header.plain

    assert "QUESTIONS · 1 round\n" in plain
    body = _questions_body(plain)
    assert "Ship it?" in body
    assert "Roll back?" not in body


def test_gate_row_ready_keeps_gate_fields_without_duplicating_body() -> None:
    _root, _plan, _first, gate, _gate0 = _question_session()
    summary = _ready_summary(_answered_round())

    header, _ = build_header_text(gate, cheap=False, summary=summary)
    plain = header.plain

    assert "QUESTIONS · 1 round\n" in plain
    assert "Q1 Deploy → Yes ★" in plain
    section = Text()
    for part in build_gate_section(gate, panel_level=FoldLevel.EXPANDED):
        assert isinstance(part, Text)
        section.append_text(part)
    assert "Q1 " not in section.plain
    assert "sase gate show" in section.plain


def test_container_session_fold_always_shows_body() -> None:
    # The session fold scale is (EXPANDED, FULLY_EXPANDED): there is no
    # heading-only state, so even COLLAPSED maps up to a body render, like
    # OUTPUT VARIABLES on container rows.
    root, _plan, _first, _gate, _gate0 = _question_session()

    header, _ = build_header_text(
        root,
        cheap=False,
        summary=_ready_summary(_answered_round(), _pending_round()),
        lane_fold_level=FoldLevel.COLLAPSED,
        lane_section_fold_overrides={},
    )
    plain = header.plain

    assert "QUESTIONS" in plain
    assert "Q1 Deploy → Yes ★" in plain


def test_container_fully_expanded_shows_exact_times() -> None:
    root, _plan, _first, _gate, _gate0 = _question_session()

    expanded, _ = build_header_text(
        root,
        cheap=False,
        summary=_ready_summary(_answered_round(), _pending_round()),
        lane_fold_level=FoldLevel.EXPANDED,
        lane_section_fold_overrides={},
    )
    full, _ = build_header_text(
        root,
        cheap=False,
        summary=_ready_summary(_answered_round(), _pending_round()),
        lane_fold_level=FoldLevel.EXPANDED,
        lane_section_fold_overrides={"questions": FoldLevel.FULLY_EXPANDED},
    )

    assert "Asked:" not in expanded.plain
    assert "Asked:" in full.plain


def test_ready_empty_rounds_renders_no_section() -> None:
    root, _plan, _first, _gate, _gate0 = _question_session()

    header, _ = build_header_text(root, cheap=False, summary=_ready_summary())
    assert "QUESTIONS" not in header.plain


def test_stub_lines_cover_status_words() -> None:
    from sase.ace.tui.models.agent_question_rounds import QuestionRoundStub
    from sase.ace.tui.widgets.prompt_panel._agent_questions_render import (
        render_question_stub_lines,
    )

    text = render_question_stub_lines(
        [
            QuestionRoundStub(
                gate_id="g0",
                member_label="gate",
                gate_state="pending",
                gate_label="Ship it?",
                asked_at_unix=None,
                deadline_unix=None,
            ),
            QuestionRoundStub(
                gate_id="g1",
                member_label="gate-0",
                gate_state="timeout",
                gate_label=None,
                asked_at_unix=None,
                deadline_unix=None,
            ),
            QuestionRoundStub(
                gate_id="",
                member_label="gate-1",
                gate_state="bogus",
                gate_label=None,
                asked_at_unix=None,
                deadline_unix=None,
            ),
        ]
    )

    assert "gate    QUESTION  Ship it?\n" in text.plain
    assert "QUESTION TIMED OUT" in text.plain
    assert "QUESTION UNKNOWN" in text.plain
    assert render_question_stub_lines([]).plain == ""


def test_mount_helper_is_zero_io_first_paint() -> None:
    root, _plan, _first, _gate, _gate0 = _question_session()
    text = Text()

    append_agent_questions_section(text, root, summary=None, fold_level=None, now=_NOW)

    assert "QUESTIONS · 2 rounds · 1 awaiting answer\n" in text.plain
    assert "Ship it?" in text.plain


__all__ = [
    "test_asking_turn_sees_only_its_round",
    "test_container_first_paint_shows_stub_lines",
    "test_container_fully_expanded_shows_exact_times",
    "test_container_ready_renders_presenter_body",
    "test_container_session_fold_always_shows_body",
    "test_gate_row_ready_keeps_gate_fields_without_duplicating_body",
    "test_gate_row_sees_only_its_round",
    "test_mount_helper_is_zero_io_first_paint",
    "test_no_section_without_question_rows",
    "test_questions_mounts_before_output_variables",
    "test_ready_empty_rounds_renders_no_section",
    "test_stub_lines_cover_status_words",
]
