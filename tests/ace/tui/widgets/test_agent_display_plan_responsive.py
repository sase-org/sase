"""Responsive and fallback rendering tests for the agent plan lane."""

from __future__ import annotations

import pytest
from rich.cells import cell_len

from sase.ace.tui.models.agent_associated_plan import AssociatedPlanPhaseSummary
from sase.ace.tui.widgets.prompt_panel._agent_context_common import (
    COLOR_EMPTY,
    COLOR_PLAN_PRIMARY,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    DetailHeaderSummary,
    HeaderHintState,
    build_header_text,
)
from sase.ace.tui.widgets.prompt_panel._agent_plan_section import (
    PLAN_FIELD_LABEL_WIDTH,
    PLAN_SECTION_MAX_WIDTH,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import assert_span_covers
from tests.ace.tui.widgets._agent_display_plan_helpers import (
    epic_summary as _epic_summary,
    plan_summary as _plan_summary,
    reconstruct_folded_token as _reconstruct_folded_token,
    reconstruct_word_wrapped_field as _reconstruct_word_wrapped_goal,
    render_header as _render_header,
    rendered_goal_lines as _rendered_goal_lines,
    rendered_text_with_style as _rendered_text_with_style,
    rendered_title_lines as _rendered_title_lines,
)


def test_long_goal_is_complete_with_hanging_indent_and_80_cell_cap() -> None:
    goal = " ".join(f"outcome{index}" for index in range(40))
    header, _ = build_header_text(
        make_agent(agent_name="planner"),
        summary=DetailHeaderSummary(
            associated_plan=_plan_summary(goal=goal),
        ),
    )

    wide_lines = _rendered_goal_lines(header, width=120)
    narrow_lines = _rendered_goal_lines(header, width=32)
    assert _reconstruct_word_wrapped_goal(wide_lines) == goal
    assert _reconstruct_word_wrapped_goal(narrow_lines) == goal
    assert len(narrow_lines) > len(wide_lines)
    assert all(cell_len(line) <= PLAN_SECTION_MAX_WIDTH for line in wide_lines)
    assert all(cell_len(line) <= 32 for line in narrow_lines)
    assert all(
        line.startswith(" " * PLAN_FIELD_LABEL_WIDTH) for line in narrow_lines[1:]
    )
    assert "…" not in "".join(narrow_lines)


@pytest.mark.parametrize(
    "title",
    [
        " ".join(f"title{index}" for index in range(40)),
        "responsive_plan_title_must_never_drop_this_final_suffix",
        "界" * 25 + "終",
    ],
)
def test_long_ascii_and_wide_unicode_titles_fold_without_loss(title: str) -> None:
    header, _ = build_header_text(
        make_agent(agent_name="planner"),
        summary=DetailHeaderSummary(
            associated_plan=_plan_summary(title=title),
        ),
    )

    wide_lines = _rendered_title_lines(header, width=120)
    narrow_lines = _rendered_title_lines(header, width=24)
    reconstruct = (
        _reconstruct_word_wrapped_goal if " " in title else _reconstruct_folded_token
    )
    assert reconstruct(wide_lines) == title
    assert reconstruct(narrow_lines) == title
    assert len(narrow_lines) >= len(wide_lines)
    assert all(cell_len(line) <= PLAN_SECTION_MAX_WIDTH for line in wide_lines)
    assert all(cell_len(line) <= 24 for line in narrow_lines)
    assert all(
        line.startswith(" " * PLAN_FIELD_LABEL_WIDTH) for line in narrow_lines[1:]
    )
    assert "…" not in "".join(narrow_lines)
    for width in (120, 24):
        styled_title = _rendered_text_with_style(
            header,
            width=width,
            style=COLOR_PLAN_PRIMARY,
        )
        if " " in title:
            assert styled_title.replace(" ", "") == title.replace(" ", "")
        else:
            assert styled_title == title


@pytest.mark.parametrize(
    "goal",
    [
        "responsive_metadata_rendering_must_never_drop_this_final_suffix",
        "界" * 25 + "終",
    ],
)
def test_oversized_tokens_fold_by_terminal_cell_without_loss(goal: str) -> None:
    header, _ = build_header_text(
        make_agent(agent_name="planner"),
        summary=DetailHeaderSummary(
            associated_plan=_plan_summary(goal=goal),
        ),
    )

    lines = _rendered_goal_lines(header, width=24)
    assert _reconstruct_folded_token(lines) == goal
    assert len(lines) > 1
    assert all(cell_len(line) <= 24 for line in lines)


@pytest.mark.parametrize(
    ("title", "description", "model"),
    [
        (
            "responsive_phase_title_must_retain_the_final_suffix",
            "description_token_must_retain_the_final_suffix",
            "codex/model_identifier_that_must_retain_the_final_suffix",
        ),
        ("界" * 20 + "題", "語" * 20 + "終", "provider/模型" + "界" * 12),
    ],
)
def test_phase_values_fold_by_terminal_cells_without_loss(
    title: str,
    description: str,
    model: str,
) -> None:
    phase = AssociatedPlanPhaseSummary(
        id="responsive_phase_identifier_with_a_complete_suffix",
        title=title,
        depends_on=(
            "dependency_identifier_with_a_complete_suffix",
            "second_dependency_identifier_with_a_complete_suffix",
        ),
        description=description,
        size="large",
        model=model,
    )
    header, _ = build_header_text(
        make_agent(agent_name="planner"),
        summary=DetailHeaderSummary(
            associated_plan=_epic_summary(phases=(phase,)),
        ),
    )

    rendered = _render_header(header, width=24)
    rendered_text = "\n".join(rendered)
    compact = "".join(rendered_text.split())
    for value in (
        phase.id,
        *phase.depends_on,
        description,
        model,
        phase.size,
    ):
        assert "".join(value.split()) in compact
    rendered_titles = _rendered_text_with_style(
        header,
        width=24,
        style=COLOR_PLAN_PRIMARY,
    )
    assert "".join(title.split()) in "".join(rendered_titles.split())
    assert "…" not in rendered_text
    assert all(cell_len(line) <= 24 for line in rendered)

    wide = _render_header(header, width=120)
    assert all(cell_len(line) <= PLAN_SECTION_MAX_WIDTH for line in wide if line)


def test_fixed_phase_size_chips_survive_narrow_rendering_while_titles_fold() -> None:
    header, _ = build_header_text(
        make_agent(agent_name="planner"),
        summary=DetailHeaderSummary(associated_plan=_epic_summary()),
    )

    rendered = _render_header(header, width=24)
    roadmap = "\n".join(rendered)
    assert roadmap.count("small") == 1
    assert roadmap.count("medium") == 1
    assert roadmap.count("large") == 1
    rendered_titles = _rendered_text_with_style(
        header,
        width=24,
        style=COLOR_PLAN_PRIMARY,
    )
    assert "Planner and safety checks".replace(" ", "") in rendered_titles.replace(
        " ", ""
    ).replace("\n", "")
    assert "…" not in roadmap
    assert all(cell_len(line) <= 24 for line in rendered)


def test_path_with_spaces_registers_actual_path_hint() -> None:
    actual = "/tmp/workspace/sase/repos/plans/202607/approved plan.md"
    hint_state = HeaderHintState(3, {}, "/tmp/workspace", {})
    header, _ = build_header_text(
        make_agent(agent_name="planner"),
        summary=DetailHeaderSummary(
            associated_plan=_plan_summary(
                actual_path=actual,
                display_path="sase/repos/plans/202607/approved plan.md",
            )
        ),
        hint_state=hint_state,
    )

    assert "Path: [3] sase/repos/plans/202607/approved plan.md" in header.plain
    assert hint_state.hint_mappings == {3: actual}
    assert hint_state.hint_counter == 4


def test_missing_or_damaged_plan_keeps_section_with_quiet_fallbacks() -> None:
    header, _ = build_header_text(
        make_agent(agent_name="planner"),
        summary=DetailHeaderSummary(
            associated_plan=_plan_summary(
                title=None,
                goal=None,
                tier=None,
                actual_path="/tmp/missing plan.md",
                display_path="~/missing plan.md",
                exists=False,
            )
        ),
    )

    assert "Title: unavailable" in header.plain
    assert "Goal: unavailable" in header.plain
    assert "▸ PLAN · tier unavailable" in header.plain
    assert "Tier:" not in header.plain
    assert "Path: ~/missing plan.md (missing)" in header.plain
    assert_span_covers(header, "unavailable", COLOR_EMPTY)
    assert_span_covers(header, "(missing)", "dim italic #FF8787")


def test_known_invalid_epic_renders_one_quiet_unavailable_phase_state() -> None:
    header, _ = build_header_text(
        make_agent(agent_name="planner"),
        summary=DetailHeaderSummary(
            associated_plan=_epic_summary(
                phases=(),
                phase_availability="unavailable",
            )
        ),
    )

    assert header.plain.count("phases unavailable") == 1
    assert "◆" not in header.plain
    assert_span_covers(header, "unavailable", COLOR_EMPTY)


def test_header_append_interface_preserves_section_and_suffix() -> None:
    header, _ = build_header_text(
        make_agent(agent_name="planner"),
        summary=DetailHeaderSummary(associated_plan=_plan_summary()),
    )

    header.append("AGENT PROMPT\n", style="bold")

    assert header.plain.endswith("AGENT PROMPT\n")
    assert "AGENT PROMPT" in _render_header(header, width=36)
    assert "▸ PLAN" in header.plain
