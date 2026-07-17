"""Agents-tab SASE CONTEXT PLAN lane rendering tests."""

from __future__ import annotations

from io import StringIO

import pytest
from rich.cells import cell_len
from rich.console import Console
from rich.style import Style

from sase.ace.tui.models.agent_associated_plan import (
    _AgentPlanEnrichment,
    AssociatedPlanPhaseSummary,
    AssociatedPlanSummary,
)
from sase.ace.tui.widgets.prompt_panel._artifact_files import ArtifactFilePath
from sase.ace.tui.widgets.prompt_panel._agent_display_header import AgentHeader
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    DetailHeaderSummary,
    HeaderHintState,
    build_detail_header_summary,
    build_header_text,
    cache_detail_header_summary,
    get_cached_detail_header_summary,
    should_refresh_detail_header_summary,
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
    PLAN_SECTION_MAX_WIDTH,
    ResponsivePlanSection,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import assert_span_covers


def _plan_summary(
    *,
    title: str | None = "Required plan titles",
    goal: str | None = "Make agent intent immediately legible.",
    tier: str | None = "plan",
    actual_path: str = "/tmp/workspace/sase/repos/plans/202607/plan.md",
    display_path: str = "sase/repos/plans/202607/plan.md",
    exists: bool = True,
    phase_availability: str = "not-applicable",
    phases: tuple[AssociatedPlanPhaseSummary, ...] = (),
) -> AssociatedPlanSummary:
    return AssociatedPlanSummary(
        title=title,
        goal=goal,
        authored_tier="tale" if tier != "epic" else "epic",
        effective_tier=tier,  # type: ignore[arg-type]
        actual_path=actual_path,
        display_path=display_path,
        committed=True,
        exists=exists,
        readable=exists,
        frontmatter_readable=exists,
        phase_availability=phase_availability,  # type: ignore[arg-type]
        phases=phases,
    )


def _epic_summary(
    *,
    phases: tuple[AssociatedPlanPhaseSummary, ...] | None = None,
    phase_availability: str = "available",
) -> AssociatedPlanSummary:
    if phases is None:
        phases = (
            AssociatedPlanPhaseSummary(
                id="core",
                title="Planner and safety checks",
                depends_on=(),
                description="Establish the canonical normalized data model.",
                model=None,
            ),
            AssociatedPlanPhaseSummary(
                id="render",
                title="Responsive phase renderer",
                depends_on=("core",),
                description="Render every phase without truncation.",
                model="codex/gpt-5.6-sol",
            ),
            AssociatedPlanPhaseSummary(
                id="verify",
                title="Responsive verification",
                depends_on=("core", "render"),
                description=None,
                model=None,
            ),
        )
    return _plan_summary(
        tier="epic",
        phase_availability=phase_availability,
        phases=phases,
    )


def _render_header(header: AgentHeader, *, width: int) -> list[str]:
    output = StringIO()
    console = Console(file=output, width=width, color_system=None)
    console.print(header, end="")
    return output.getvalue().splitlines()


def _rendered_text_with_style(
    header: AgentHeader,
    *,
    width: int,
    style: str,
) -> str:
    console = Console(width=width, color_system=None)
    expected = Style.parse(style)
    return "".join(
        segment.text for segment in console.render(header) if segment.style == expected
    )


def _rendered_goal_lines(header: AgentHeader, *, width: int) -> list[str]:
    lines = _render_header(header, width=width)
    start = next(
        index
        for index, line in enumerate(lines)
        if line[:PLAN_FIELD_LABEL_WIDTH].strip() == "Goal:"
    )
    goal_lines = [lines[start]]
    continuation_prefix = " " * PLAN_FIELD_LABEL_WIDTH
    for line in lines[start + 1 :]:
        if not line.startswith(continuation_prefix):
            break
        goal_lines.append(line)
    return goal_lines


def _rendered_title_lines(header: AgentHeader, *, width: int) -> list[str]:
    lines = _render_header(header, width=width)
    start = next(
        index
        for index, line in enumerate(lines)
        if line[:PLAN_FIELD_LABEL_WIDTH].strip() == "Title:"
    )
    title_lines = [lines[start]]
    continuation_prefix = " " * PLAN_FIELD_LABEL_WIDTH
    for line in lines[start + 1 :]:
        if not line.startswith(continuation_prefix):
            break
        title_lines.append(line)
    return title_lines


def _reconstruct_word_wrapped_goal(lines: list[str]) -> str:
    return " ".join(line[PLAN_FIELD_LABEL_WIDTH:].rstrip() for line in lines)


def _reconstruct_folded_token(lines: list[str]) -> str:
    return "".join(line[PLAN_FIELD_LABEL_WIDTH:].rstrip() for line in lines)


def _covering_style(header: AgentHeader, needle: str) -> Style:
    start = header.plain.index(needle)
    end = start + len(needle)
    styles = [
        Style.parse(str(span.style))
        for span in header.spans
        if span.start <= start and span.end >= end
    ]
    assert len(styles) == 1
    return styles[0]


def _style_color(style: str):  # type: ignore[no-untyped-def]
    color = Style.parse(style).color
    assert color is not None
    return color.get_truecolor()


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
    assert "  1 ◆ Planner and safety checks\n" in plain
    assert "    core · no dependencies\n" in plain
    assert "    Establish the canonical normalized data model.\n" in plain
    assert "  2 ◆ Responsive phase renderer\n" in plain
    assert "    render · after core · model codex/gpt-5.6-sol\n" in plain
    assert "  3 ◆ Responsive verification\n" in plain
    assert "    verify · after core, render\n" in plain
    assert_span_covers(header, "3 phases", COLOR_SUMMARY)
    assert_span_covers(header, "  1 ", COLOR_SUMMARY)
    assert_span_covers(header, "◆ ", COLOR_PLAN_SUBHEADER)
    assert_span_covers(header, "Planner and safety checks", COLOR_PLAN_PRIMARY)
    assert_span_covers(header, "core", PLAN_PHASE_ID_STYLE)
    assert_span_covers(header, "codex/gpt-5.6-sol", PLAN_PHASE_MODEL_STYLE)
    assert_span_covers(
        header,
        "Establish the canonical normalized data model.",
        COLOR_REASON,
    )


def test_single_phase_count_and_omitted_optional_values_are_compact() -> None:
    phase = AssociatedPlanPhaseSummary(
        id="only",
        title="Only phase",
        depends_on=(),
        description=None,
        model=None,
    )
    header, _ = build_header_text(
        make_agent(agent_name="planner"),
        summary=DetailHeaderSummary(
            associated_plan=_epic_summary(phases=(phase,)),
        ),
    )

    assert "▸ PLAN · epic · 1 phase\n" in header.plain
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
        title,
        phase.id,
        *phase.depends_on,
        description,
        model,
    ):
        assert "".join(value.split()) in compact
    assert "…" not in rendered_text
    assert all(cell_len(line) <= 24 for line in rendered)

    wide = _render_header(header, width=120)
    assert all(cell_len(line) <= PLAN_SECTION_MAX_WIDTH for line in wide if line)


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


def test_detail_summary_resolves_plan_only_in_enrichment_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(agent_name="planner", step_type="bash")
    plan = _plan_summary()
    calls: list[object] = []

    def resolve(agent_arg: object) -> _AgentPlanEnrichment:
        calls.append(agent_arg)
        return _AgentPlanEnrichment("ordinary", None, plan, plan.actual_path)

    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_header_summary."
        "resolve_agent_plan_enrichment",
        resolve,
    )

    summary = build_detail_header_summary(agent)

    assert summary.associated_plan is plan
    assert calls[0] is agent


def test_canonical_plan_is_removed_from_generic_artifact_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(agent_name="planner", step_type="bash")
    plan = _plan_summary(actual_path="/tmp/plan.md", display_path="~/plan.md")
    other = ArtifactFilePath("notes.md", "/tmp/notes.md")
    duplicate = ArtifactFilePath("plan.md", "/tmp/plan.md", view_mode="markdown")
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_header_summary."
        "resolve_agent_plan_enrichment",
        lambda *_args, **_kwargs: _AgentPlanEnrichment(
            "ordinary",
            None,
            plan,
            plan.actual_path,
        ),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._artifact_files.artifact_file_paths",
        lambda _agent: [duplicate, other],
    )

    summary = build_detail_header_summary(agent)

    assert summary.artifact_file_paths == [other]


def test_phase_plan_is_not_exposed_as_generic_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(
        agent_name="sase-9.2",
        epic_bead_id="sase-9",
        phase_bead_id="sase-9.2",
        step_type="bash",
    )
    other = ArtifactFilePath("notes.md", "/tmp/notes.md")
    duplicate = ArtifactFilePath("epic.md", "/tmp/epic.md", view_mode="markdown")
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_header_summary."
        "resolve_agent_plan_enrichment",
        lambda *_args, **_kwargs: _AgentPlanEnrichment(
            "phase",
            "sase-9.2 - Selected phase",
            None,
            "/tmp/epic.md",
        ),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._artifact_files.artifact_file_paths",
        lambda _agent: [duplicate, other],
    )

    summary = build_detail_header_summary(agent)

    assert summary.associated_plan is None
    assert summary.artifact_file_paths == [other]


def test_cheap_header_never_resolves_or_stats_plan(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("hot render path must remain memory-only")

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_associated_plan.resolve_agent_plan_enrichment",
        fail,
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_associated_plan._PlanFileCache.get",
        fail,
    )

    header, _ = build_header_text(make_agent(agent_name="planner"), cheap=True)

    assert "▸ PLAN" not in header.plain


def test_approval_metadata_change_invalidates_cached_plan_summary() -> None:
    class Widget:
        pass

    widget = Widget()
    agent = make_agent(
        agent_name="planner",
        archived_plan_path="/tmp/archive.md",
        plan_committed=None,
    )
    summary = DetailHeaderSummary(associated_plan=_plan_summary())

    cache_detail_header_summary(widget, agent, summary)
    assert get_cached_detail_header_summary(widget, agent) is summary

    agent.plan_committed = False

    assert get_cached_detail_header_summary(widget, agent) is None
    assert should_refresh_detail_header_summary(widget, agent)


def test_modern_phase_renders_one_frontmatter_bead_and_no_plan(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # type: ignore[no-untyped-def]
    plan = tmp_path / "plans" / "epic.md"
    plan.parent.mkdir()
    plan.write_text(
        "---\n"
        "tier: epic\n"
        "title: Role-aware metadata\n"
        "goal: Keep the complete roadmap on epic owners only.\n"
        "phases:\n"
        "  - id: core\n"
        "    title: Build metadata\n"
        "    depends_on: []\n"
        "  - id: render\n"
        "    title: Render phase metadata\n"
        "    depends_on: [core]\n"
        "    description: >-\n"
        "      Show only this selected\n"
        "      phase description.\n"
        "---\n"
        "# Plan\n",
        encoding="utf-8",
    )
    agent = make_agent(
        agent_name="sase-9.2",
        epic_bead_id="sase-9",
        phase_bead_id="sase-9.2",
        sdd_plan_path="plans/epic.md",
        plan_committed=True,
        workspace_dir=str(tmp_path),
        step_type="bash",
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_associated_plan._lookup_issue",
        lambda *_args, **_kwargs: pytest.fail("modern phase must not read beads"),
    )

    summary = build_detail_header_summary(agent)
    header, _ = build_header_text(agent, summary=summary)

    assert summary.associated_plan is None
    assert header.plain.count("Bead:") == 1
    assert "Bead: sase-9.2 - Show only this selected phase description.\n" in (
        header.plain
    )
    assert "▸ PLAN" not in header.plain
    assert "Goal:" not in header.plain
    assert "Path:" not in header.plain
    assert "Build metadata" not in header.plain
