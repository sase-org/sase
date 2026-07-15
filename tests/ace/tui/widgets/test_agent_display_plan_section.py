"""Agents-tab SASE PLAN metadata rendering tests."""

from __future__ import annotations

from io import StringIO

import pytest
from rich.cells import cell_len
from rich.console import Console

from sase.ace.tui.models.agent_associated_plan import (
    AssociatedPlanPhaseSummary,
    AssociatedPlanSummary,
)
from sase.ace.tui.widgets.prompt_panel._agent_artifacts import AgentArtifactPath
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
from sase.ace.tui.widgets.prompt_panel._agent_plan_section import (
    PLAN_FIELD_LABEL_WIDTH,
    PLAN_PHASE_DESCRIPTION_STYLE,
    PLAN_PHASE_GLYPH_STYLE,
    PLAN_PHASE_ID_STYLE,
    PLAN_PHASE_MODEL_STYLE,
    PLAN_PHASE_ORDINAL_STYLE,
    PLAN_PHASE_TITLE_STYLE,
    PLAN_PHASES_LABEL_STYLE,
    PLAN_SECTION_MAX_WIDTH,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import assert_span_covers


def _plan_summary(
    *,
    goal: str | None = "Make agent intent immediately legible.",
    tier: str | None = "plan",
    actual_path: str = "/tmp/workspace/sase/repos/plans/202607/plan.md",
    display_path: str = "sase/repos/plans/202607/plan.md",
    exists: bool = True,
    phase_availability: str = "not-applicable",
    phases: tuple[AssociatedPlanPhaseSummary, ...] = (),
) -> AssociatedPlanSummary:
    return AssociatedPlanSummary(
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


def _rendered_goal_lines(header: AgentHeader, *, width: int) -> list[str]:
    lines = _render_header(header, width=width)
    start = next(index for index, line in enumerate(lines) if line.startswith("Goal:"))
    goal_lines = [lines[start]]
    continuation_prefix = " " * PLAN_FIELD_LABEL_WIDTH
    for line in lines[start + 1 :]:
        if not line.startswith(continuation_prefix):
            break
        goal_lines.append(line)
    return goal_lines


def _reconstruct_word_wrapped_goal(lines: list[str]) -> str:
    return " ".join(line[PLAN_FIELD_LABEL_WIDTH:].rstrip() for line in lines)


def _reconstruct_folded_token(lines: list[str]) -> str:
    return "".join(line[PLAN_FIELD_LABEL_WIDTH:].rstrip() for line in lines)


def test_section_follows_timestamps_and_precedes_optional_major_sections() -> None:
    agent = make_agent(agent_name="planner", output_variables={"result": "ok"})
    header, _ = build_header_text(
        agent,
        summary=DetailHeaderSummary(associated_plan=_plan_summary()),
    )

    plain = header.plain
    assert plain.index("Timestamps:") < plain.index("SASE PLAN")
    assert plain.index("SASE PLAN") < plain.index("OUTPUT VARIABLES")
    assert plain.index("SASE PLAN") < plain.index("Goal:")
    assert plain.index("Goal:") < plain.index("Tier:") < plain.index("Path:")
    assert plain.count("Goal:") == 1
    assert plain.splitlines()[1].startswith("ChangeSpec:")
    assert_span_covers(header, "SASE PLAN", "bold #D7AF5F underline")
    assert_span_covers(header, "Goal: ", "bold #87D7FF")
    assert_span_covers(
        header, "Make agent intent immediately legible.", "italic #FFD787"
    )


def test_plan_is_first_major_section_in_maximal_append_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.widgets.prompt_panel import _agent_artifacts
    from sase.ace.tui.widgets.prompt_panel import _agent_commits
    from sase.ace.tui.widgets.prompt_panel import _agent_context
    from sase.ace.tui.widgets.prompt_panel import _agent_deltas
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
    monkeypatch.setattr(
        _agent_commits,
        "append_agent_commits_section",
        section("COMMITS"),
    )
    monkeypatch.setattr(
        _agent_deltas,
        "append_agent_deltas_section",
        section("DELTAS"),
    )
    monkeypatch.setattr(
        _agent_artifacts,
        "append_agent_artifacts_section",
        section("ARTIFACTS"),
    )
    monkeypatch.setattr(
        _agent_context,
        "append_agent_context_section",
        section("SASE CONTEXT"),
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
        step_output={"meta_result": "ready"},
        error_message="fixture error",
    )
    summary = DetailHeaderSummary(
        xprompts_used=[{"kind": "part", "name": "plan"}],
        associated_plan=_epic_summary(),
        memory_reads=(object(),),  # type: ignore[arg-type]
        slow_tool_sources=(object(),),  # type: ignore[arg-type]
    )

    header, _ = build_header_text(agent, summary=summary)
    header.append(
        "AGENT XPROMPT\nAGENT PROMPT\nAGENT REPLY\nAGENT CHAT\n",
    )

    plain = header.plain
    plan_index = plain.index("SASE PLAN")
    assert plain.count("SASE PLAN") == 1
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
        assert plain.index(metadata_label) < plan_index
    for section_label in (
        "OUTPUT VARIABLES",
        "COMMITS",
        "DELTAS",
        "ARTIFACTS",
        "WORKFLOW VARIABLES",
        "SASE CONTEXT",
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
    assert plain.index("Goal:") < plain.index("Tier:") < plain.index("Path:")
    assert plain.index("Path:") < plain.index("Phases: 3")
    assert "  1 ◆ Planner and safety checks\n" in plain
    assert "    core · no dependencies\n" in plain
    assert "    Establish the canonical normalized data model.\n" in plain
    assert "  2 ◆ Responsive phase renderer\n" in plain
    assert "    render · after core · model codex/gpt-5.6-sol\n" in plain
    assert "  3 ◆ Responsive verification\n" in plain
    assert "    verify · after core, render\n" in plain
    assert_span_covers(header, "Phases: ", PLAN_PHASES_LABEL_STYLE)
    assert_span_covers(header, "  1 ", PLAN_PHASE_ORDINAL_STYLE)
    assert_span_covers(header, "◆ ", PLAN_PHASE_GLYPH_STYLE)
    assert_span_covers(header, "Planner and safety checks", PLAN_PHASE_TITLE_STYLE)
    assert_span_covers(header, "core", PLAN_PHASE_ID_STYLE)
    assert_span_covers(header, "codex/gpt-5.6-sol", PLAN_PHASE_MODEL_STYLE)
    assert_span_covers(
        header,
        "Establish the canonical normalized data model.",
        PLAN_PHASE_DESCRIPTION_STYLE,
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

    assert "Phases: 1\n" in header.plain
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

    assert "SASE PLAN" not in cheap_header.plain
    assert "Goal:" not in cheap_header.plain
    assert "SASE PLAN" not in empty_header.plain


def test_tale_plan_keeps_compact_layout_without_phase_block() -> None:
    header, _ = build_header_text(
        make_agent(agent_name="planner"),
        summary=DetailHeaderSummary(associated_plan=_plan_summary()),
    )

    assert "Phases:" not in header.plain
    assert "◆" not in header.plain


@pytest.mark.parametrize(
    ("tier", "style"),
    [
        ("plan", "bold #5FD7FF"),
        ("epic", "bold #AF87FF"),
        ("none", "italic #8787AF"),
    ],
)
def test_tier_values_have_distinct_restrained_styles(tier: str, style: str) -> None:
    header, _ = build_header_text(
        make_agent(agent_name="planner"),
        summary=DetailHeaderSummary(
            associated_plan=_plan_summary(tier=tier),
        ),
    )

    assert f"Tier: {tier}" in header.plain
    start = header.plain.index(f"Tier: {tier}") + len("Tier: ")
    end = start + len(tier)
    assert any(
        span.start <= start and span.end >= end and str(span.style) == style
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
                goal=None,
                tier=None,
                actual_path="/tmp/missing plan.md",
                display_path="~/missing plan.md",
                exists=False,
            )
        ),
    )

    assert "Goal: unavailable" in header.plain
    assert "Tier: unavailable" in header.plain
    assert "Path: ~/missing plan.md (missing)" in header.plain
    assert_span_covers(header, "unavailable", "dim italic #878787")
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

    assert header.plain.count("Phases: unavailable") == 1
    assert "◆" not in header.plain
    assert_span_covers(header, "unavailable", "dim italic #878787")


def test_header_append_interface_preserves_section_and_suffix() -> None:
    header, _ = build_header_text(
        make_agent(agent_name="planner"),
        summary=DetailHeaderSummary(associated_plan=_plan_summary()),
    )

    header.append("AGENT PROMPT\n", style="bold")

    assert header.plain.endswith("AGENT PROMPT\n")
    assert "AGENT PROMPT" in _render_header(header, width=36)
    assert "SASE PLAN" in header.plain


def test_detail_summary_resolves_plan_only_in_enrichment_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(agent_name="planner", step_type="bash")
    plan = _plan_summary()
    calls: list[object] = []

    def resolve(agent_arg: object, *, lookup_session: object) -> AssociatedPlanSummary:
        calls.extend((agent_arg, lookup_session))
        return plan

    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_header_summary."
        "resolve_agent_associated_plan",
        resolve,
    )

    summary = build_detail_header_summary(agent)

    assert summary.associated_plan is plan
    assert calls[0] is agent
    assert calls[1].__class__.__name__ == "BeadIssueLookupSession"


def test_canonical_plan_is_removed_from_generic_artifact_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(agent_name="planner", step_type="bash")
    plan = _plan_summary(actual_path="/tmp/plan.md", display_path="~/plan.md")
    other = AgentArtifactPath("notes.md", "/tmp/notes.md")
    duplicate = AgentArtifactPath("plan.md", "/tmp/plan.md", view_mode="markdown")
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_header_summary."
        "resolve_agent_associated_plan",
        lambda *_args, **_kwargs: plan,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_artifacts.agent_artifact_paths",
        lambda _agent: [duplicate, other],
    )

    summary = build_detail_header_summary(agent)

    assert summary.artifact_paths == [other]


def test_cheap_header_never_resolves_or_stats_plan(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("hot render path must remain memory-only")

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_associated_plan.resolve_agent_associated_plan",
        fail,
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_associated_plan._PlanFileCache.get",
        fail,
    )

    header, _ = build_header_text(make_agent(agent_name="planner"), cheap=True)

    assert "SASE PLAN" not in header.plain


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
