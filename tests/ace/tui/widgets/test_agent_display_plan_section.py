"""Agents-tab SASE CONTEXT PLAN lane rendering tests."""

from __future__ import annotations

import pytest
from rich.cells import cell_len
from rich.style import Style

from sase.ace.tui.models.agent_associated_plan import (
    AssociatedPlanPhaseSummary,
    AssociatedPlanSummary,
)
from sase.ace.tui.widgets.prompt_panel._artifact_files import ArtifactFilePath
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    DetailHeaderSummary,
    build_header_text,
)
from sase.ace.tui.widgets.prompt_panel._agent_context_common import (
    COLOR_ARTIFACTS_PRIMARY,
    COLOR_ARTIFACTS_SUBHEADER,
    COLOR_EMPTY,
    COLOR_MEMORY_PRIMARY,
    COLOR_MEMORY_SUBHEADER,
    COLOR_PLAN_PRIMARY,
    COLOR_PLAN_SUBHEADER,
    COLOR_REASON,
    COLOR_SKILL_NAME,
    COLOR_SKILLS_SUBHEADER,
    COLOR_SUMMARY,
    COLOR_WORKSPACE_NAME,
    COLOR_WORKSPACE_SUBHEADER,
)
from sase.ace.tui.widgets.prompt_panel._agent_plan_section import (
    PLAN_FIELD_LABEL_WIDTH,
    PLAN_PHASE_ID_STYLE,
    PLAN_PHASE_MODEL_STYLE,
    ResponsivePlanSection,
)
from sase.ace.tui.widgets.renderable_text import renderable_to_text
from sase.phase_size_presentation import PHASE_SIZE_STYLES
from tests.ace.tui.widgets._agent_display_plan_helpers import (
    covering_style as _covering_style,
    epic_summary as _epic_summary,
    plan_summary as _plan_summary,
    render_header as _render_header,
    style_color as _style_color,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import assert_span_covers


def test_plan_lane_follows_optional_sections_inside_sase_context() -> None:
    agent = make_agent(agent_name="planner", output_variables={"result": "ok"})
    header, _ = build_header_text(
        agent,
        summary=DetailHeaderSummary(associated_plan=_plan_summary()),
    )

    plain = header.plain
    assert plain.index("Timestamps:") < plain.index("OUTPUT VARIABLES")
    assert plain.index("OUTPUT VARIABLES") < plain.index("SASE CONTEXT")
    assert plain.index("SASE CONTEXT") < plain.index("▸ PLAN · plan")
    assert plain.index("▸ PLAN · plan") < plain.index("  Title:")
    assert plain.index("  Title:") < plain.index("   Goal:") < plain.index("   Path:")
    assert plain.count("Title:") == 1
    assert plain.count("Goal:") == 1
    assert "Tier:" not in plain
    assert "SASE PLAN" not in plain
    assert plain.splitlines()[1].startswith("ChangeSpec:")
    assert_span_covers(header, "▸ PLAN", "bold #AF87FF")
    assert_span_covers(header, "Title: ", COLOR_SUMMARY)
    assert_span_covers(header, "Required plan titles", COLOR_PLAN_PRIMARY)
    assert_span_covers(header, "Goal: ", COLOR_SUMMARY)
    assert_span_covers(header, "Make agent intent immediately legible.", COLOR_REASON)


def test_plan_field_labels_align_colons_in_the_shared_column() -> None:
    section = ResponsivePlanSection(_plan_summary())
    header, _ = build_header_text(
        make_agent(agent_name="planner"),
        summary=DetailHeaderSummary(associated_plan=section.summary),
    )

    for lines in (
        section.logical_text.plain.splitlines(),
        _render_header(header, width=120),
    ):
        labels = [
            line[:PLAN_FIELD_LABEL_WIDTH]
            for line in lines
            if line[:PLAN_FIELD_LABEL_WIDTH].strip() in {"Title:", "Goal:", "Path:"}
        ]
        assert labels == ["  Title: ", "   Goal: ", "   Path: "]
        assert {cell_len(label) for label in labels} == {PLAN_FIELD_LABEL_WIDTH}
        assert {label.index(":") for label in labels} == {7}


def test_title_and_goal_values_have_no_competing_decoration() -> None:
    header, _ = build_header_text(
        make_agent(agent_name="planner"),
        summary=DetailHeaderSummary(associated_plan=_plan_summary()),
    )

    title_style = _covering_style(header, "Required plan titles")
    goal_style = _covering_style(header, "Make agent intent immediately legible.")
    assert title_style == Style.parse(COLOR_PLAN_PRIMARY)
    assert title_style.underline is not True
    assert goal_style == Style.parse(COLOR_REASON)
    assert goal_style.italic is not True


def test_plan_palette_is_distinct_from_every_other_lane_palette() -> None:
    lane_palette = (
        COLOR_PLAN_SUBHEADER,
        COLOR_MEMORY_SUBHEADER,
        COLOR_SKILLS_SUBHEADER,
        COLOR_WORKSPACE_SUBHEADER,
        COLOR_ARTIFACTS_SUBHEADER,
        COLOR_PLAN_PRIMARY,
        COLOR_MEMORY_PRIMARY,
        COLOR_SKILL_NAME,
        COLOR_WORKSPACE_NAME,
        COLOR_ARTIFACTS_PRIMARY,
    )
    lane_colors = {_style_color(style) for style in lane_palette}
    assert len(lane_colors) == len(lane_palette)

    plan_text = ResponsivePlanSection(_epic_summary()).logical_text
    plan_colors = {
        color.get_truecolor()
        for span in plan_text.spans
        if (color := Style.parse(str(span.style)).color) is not None
    }
    other_lane_colors = {
        _style_color(style)
        for style in (
            COLOR_MEMORY_SUBHEADER,
            COLOR_SKILLS_SUBHEADER,
            COLOR_WORKSPACE_SUBHEADER,
            COLOR_ARTIFACTS_SUBHEADER,
            COLOR_MEMORY_PRIMARY,
            COLOR_SKILL_NAME,
            COLOR_WORKSPACE_NAME,
        )
    }
    assert _style_color(COLOR_ARTIFACTS_PRIMARY) in plan_colors
    assert plan_colors.isdisjoint(other_lane_colors)


@pytest.mark.parametrize(
    "summary",
    [_plan_summary(), _plan_summary(tier="tale"), _epic_summary()],
    ids=["plan", "tale", "epic"],
)
@pytest.mark.parametrize("width", [32, 120], ids=["narrow", "wide"])
def test_plan_lane_header_is_immediately_followed_by_title(
    summary: AssociatedPlanSummary,
    width: int,
) -> None:
    header, _ = build_header_text(
        make_agent(agent_name="planner"),
        summary=DetailHeaderSummary(associated_plan=summary),
    )

    assert "▸ PLAN ·" in header.plain
    logical_lines = header.plain.splitlines()
    logical_heading_index = next(
        index for index, line in enumerate(logical_lines) if line.startswith("▸ PLAN ·")
    )
    assert logical_lines[logical_heading_index + 1].startswith("  Title:")

    lines = _render_header(header, width=width)
    heading_index = next(
        index for index, line in enumerate(lines) if line.startswith("▸ PLAN ·")
    )
    assert lines[heading_index + 1].startswith("  Title:")


def test_plan_and_artifacts_lead_context_in_maximal_append_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.widgets.prompt_panel import _agent_context
    from sase.ace.tui.widgets.prompt_panel import _agent_display_header
    from sase.ace.tui.widgets.prompt_panel import _agent_slow_tools

    def section(label: str):  # type: ignore[no-untyped-def]
        def append(text, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            text.append(f"\n{label}\n")

        return append

    monkeypatch.setattr(
        _agent_display_header,
        "append_agent_output_variables_section",
        section("OUTPUT VARIABLES"),
    )

    def append_context(
        text,
        *,
        plan_section,
        agent,
        delta_entries,
        artifact_file_paths,
        **_kwargs,
    ):  # type: ignore[no-untyped-def]
        text.append("\nSASE CONTEXT\n")
        assert plan_section is not None
        assert agent is not None
        assert delta_entries
        assert artifact_file_paths
        plan_start = len(text)
        text.append_text(plan_section.logical_text)
        plan_range = (plan_start, len(text))
        text.append(
            "\n▸ ARTIFACTS\n  Commits:\n  Deltas:\n  Files:\n\n"
            "▸ MEMORY\n\n▸ SKILLS\n\n▸ WORKSPACES\n"
        )
        return plan_range

    monkeypatch.setattr(
        _agent_context,
        "append_agent_context_section",
        append_context,
    )
    monkeypatch.setattr(
        _agent_slow_tools,
        "append_slow_tool_calls_section",
        section("SLOW TOOL CALLS"),
    )
    agent = make_agent(
        agent_name="planner",
        model="gpt-5",
        llm_provider="codex",
        vcs_provider="github",
        pid=123,
        activity="editing",
        output_variables={"result": "ok"},
        step_output={
            "meta_result": "ready",
            "meta_commit_message": "feat: output lane",
            "meta_new_commit": "abc123",
        },
        error_message="fixture error",
    )
    summary = DetailHeaderSummary(
        xprompts_used=[{"kind": "part", "name": "plan"}],
        associated_plan=_epic_summary(),
        memory_reads=(object(),),  # type: ignore[arg-type]
        skill_uses=(object(),),  # type: ignore[arg-type]
        opened_workspaces=(object(),),  # type: ignore[arg-type]
        delta_entries=[object()],  # type: ignore[list-item]
        artifact_file_paths=[
            ArtifactFilePath("artifact.txt", "/tmp/artifact.txt"),
        ],
        slow_tool_sources=(object(),),  # type: ignore[arg-type]
    )

    header, _ = build_header_text(agent, summary=summary)
    header.append(
        "AGENT XPROMPT\nAGENT PROMPT\nAGENT REPLY\nAGENT CHAT\n",
    )

    plain = header.plain
    context_index = plain.index("SASE CONTEXT")
    plan_index = plain.index("▸ PLAN")
    assert plain.count("▸ PLAN") == 1
    assert "SASE PLAN" not in plain
    for metadata_label in (
        "Name:",
        "ChangeSpec:",
        "Model:",
        "Xprompts:",
        "VCS:",
        "PID:",
        "Activity:",
        "Timestamps:",
    ):
        assert plain.index(metadata_label) < context_index
    for section_label in (
        "OUTPUT VARIABLES",
        "WORKFLOW VARIABLES",
    ):
        assert plain.index(section_label) < context_index
    assert context_index < plan_index
    artifacts_index = plain.index("▸ ARTIFACTS")
    assert plan_index < artifacts_index
    assert artifacts_index < plain.index("Commits:")
    assert plain.index("Commits:") < plain.index("Deltas:")
    assert plain.index("Deltas:") < plain.index("Files:")
    assert plain.index("Files:") < plain.index("▸ MEMORY")
    assert plain.index("▸ MEMORY") < plain.index("▸ SKILLS")
    assert plain.index("▸ SKILLS") < plain.index("▸ WORKSPACES")
    for section_label in (
        "SLOW TOOL CALLS",
        "ERROR",
        "AGENT XPROMPT",
        "AGENT PROMPT",
        "AGENT REPLY",
        "AGENT CHAT",
    ):
        assert plan_index < plain.index(section_label)


def test_epic_phase_roadmap_has_canonical_order_content_and_styles() -> None:
    header, _ = build_header_text(
        make_agent(agent_name="planner"),
        summary=DetailHeaderSummary(associated_plan=_epic_summary()),
    )

    plain = header.plain
    assert plain.index("▸ PLAN · epic · 3 phases") < plain.index("Title:")
    assert plain.index("Title:") < plain.index("Goal:") < plain.index("Path:")
    assert plain.index("Path:") < plain.index("  1 ◆")
    assert "Tier:" not in plain
    assert "Phases:" not in plain
    assert "  1 ◆ Planner and safety checks small  \n" in plain
    assert "    core · no dependencies\n" in plain
    assert "    Establish the canonical normalized data model.\n" in plain
    assert "  2 ◆ Responsive phase renderer medium \n" in plain
    assert "    render · after core · model codex/gpt-5.6-sol\n" in plain
    assert "  3 ◆ Responsive verification large  \n" in plain
    assert "    verify · after core, render\n" in plain
    assert_span_covers(header, "3 phases", COLOR_SUMMARY)
    assert_span_covers(header, "  1 ", COLOR_SUMMARY)
    assert_span_covers(header, "◆ ", COLOR_PLAN_SUBHEADER)
    assert_span_covers(header, "Planner and safety checks", COLOR_PLAN_PRIMARY)
    for label in ("small", "medium", "large"):
        assert_span_covers(header, label, PHASE_SIZE_STYLES[label])  # type: ignore[index]
    assert_span_covers(header, "core", PLAN_PHASE_ID_STYLE)
    assert_span_covers(header, "codex/gpt-5.6-sol", PLAN_PHASE_MODEL_STYLE)
    assert_span_covers(
        header,
        "Establish the canonical normalized data model.",
        COLOR_REASON,
    )


def test_epic_phase_sizes_are_visible_in_logical_text_for_search_and_copy() -> None:
    section = ResponsivePlanSection(_epic_summary())
    header, _ = build_header_text(
        make_agent(agent_name="planner"),
        summary=DetailHeaderSummary(associated_plan=section.summary),
    )

    assert section.logical_text.plain.count(" small  ") == 1
    assert section.logical_text.plain.count(" medium ") == 1
    assert section.logical_text.plain.count(" large  ") == 1
    assert header.plain.count("small") == 1
    assert header.plain.count("medium") == 1
    assert header.plain.count("large") == 1
    searchable = renderable_to_text(header)
    assert searchable is not None
    for label in ("small", "medium", "large"):
        assert searchable.count(label) == 1


def test_single_phase_count_and_omitted_optional_values_are_compact() -> None:
    phase = AssociatedPlanPhaseSummary(
        id="only",
        title="Only phase",
        depends_on=(),
        description=None,
        size="small",
        model=None,
    )
    header, _ = build_header_text(
        make_agent(agent_name="planner"),
        summary=DetailHeaderSummary(
            associated_plan=_epic_summary(phases=(phase,)),
        ),
    )

    assert "▸ PLAN · epic · 1 phase\n" in header.plain
    assert "  1 ◆ Only phase small  \n" in header.plain
    assert "    only · no dependencies\n" in header.plain
    assert "model" not in header.plain
    assert "None" not in header.plain


def test_section_is_omitted_without_cached_association() -> None:
    agent = make_agent(agent_name="utility")

    cheap_header, _ = build_header_text(agent, cheap=True)
    empty_header, _ = build_header_text(
        agent,
        summary=DetailHeaderSummary(associated_plan=None),
    )

    assert "▸ PLAN" not in cheap_header.plain
    assert "Goal:" not in cheap_header.plain
    assert "▸ PLAN" not in empty_header.plain


def test_tale_plan_keeps_compact_layout_without_phase_block() -> None:
    header, _ = build_header_text(
        make_agent(agent_name="planner"),
        summary=DetailHeaderSummary(
            associated_plan=_plan_summary(tier="tale"),
        ),
    )

    assert "▸ PLAN · tale\n" in header.plain
    assert "Tier:" not in header.plain
    assert "Phases:" not in header.plain
    assert "◆" not in header.plain


@pytest.mark.parametrize("tier", ["plan", "tale", "epic"])
def test_tier_values_use_uniform_dim_header_details_style(tier: str) -> None:
    header, _ = build_header_text(
        make_agent(agent_name="planner"),
        summary=DetailHeaderSummary(
            associated_plan=_plan_summary(tier=tier),
        ),
    )

    assert f"▸ PLAN · {tier}" in header.plain
    start = header.plain.index(f"▸ PLAN · {tier}") + len("▸ PLAN · ")
    end = start + len(tier)
    assert any(
        span.start <= start and span.end >= end and str(span.style) == COLOR_SUMMARY
        for span in header.spans
    )
