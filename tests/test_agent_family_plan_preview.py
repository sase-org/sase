"""Tests for sase.agent_family_plan_preview."""

from __future__ import annotations

from sase.agent_family_plan_preview import (
    EMPTY_AGENT_FAMILY_PLAN_PREVIEW,
    AgentFamilyPlanPreview,
    agent_family_plan_preview_accent,
    agent_family_plan_preview_detail,
    agent_family_plan_preview_documentation,
    agent_family_plan_preview_from_bead,
    agent_family_plan_preview_from_plan,
    agent_family_plan_preview_label,
    agent_family_plan_structure_text,
)
from sase.bead_type_presentation import BEAD_TYPE_PRESENTATIONS
from sase.plan_tier_presentation import GENERIC_PLAN_ACCENT, PLAN_TIER_PRESENTATIONS
from sase.sdd.plan_display import PlanDisplay, PlanDisplayPhase


def _epic_phase(
    phase_id: str,
    title: str,
    *,
    depends_on: tuple[str, ...] = (),
    size: str = "small",
) -> PlanDisplayPhase:
    return PlanDisplayPhase(
        id=phase_id,
        title=title,
        depends_on=depends_on,
        description=None,
        size=size,  # type: ignore[arg-type]
        model=None,
    )


def _plan(
    *,
    title: str | None = "Plan-aware agent-family completion previews",
    goal: str | None = "Lead with the tale or epic a family belongs to.",
    authored_tier: str | None = "epic",
    effective_tier: str | None = "epic",
    phase_availability: str = "available",
    phases: tuple[PlanDisplayPhase, ...] = (),
    size: str | None = None,
) -> PlanDisplay:
    return PlanDisplay(
        title=title,
        goal=goal,
        authored_tier=authored_tier,  # type: ignore[arg-type]
        effective_tier=effective_tier,  # type: ignore[arg-type]
        actual_path="/tmp/plan.md",
        display_path="plans/plan.md",
        committed=True,
        exists=True,
        readable=True,
        frontmatter_readable=True,
        phase_availability=phase_availability,  # type: ignore[arg-type]
        phases=phases,
        validation_ok=True,
        size=size,  # type: ignore[arg-type]
    )


class TestAgentFamilyPlanPreviewFromPlan:
    def test_epic_with_waves_computes_phase_and_wave_counts(self) -> None:
        phases = (
            _epic_phase("core", "Core"),
            _epic_phase("docs", "Docs"),
            _epic_phase("render", "Render", depends_on=("core", "docs")),
            _epic_phase("verify", "Verify", depends_on=("render",)),
        )
        preview = agent_family_plan_preview_from_plan(_plan(phases=phases))

        assert preview.kind == "epic"
        assert preview.title == "Plan-aware agent-family completion previews"
        assert preview.goal == "Lead with the tale or epic a family belongs to."
        assert preview.phase_count == 4
        assert preview.wave_count == 3
        assert preview.phase_titles == ("Core", "Docs", "Render", "Verify")
        assert preview.phase_ids == ("core", "docs", "render", "verify")
        assert preview.phase_sizes == ("small", "small", "small", "small")
        assert not preview.is_empty

    def test_epic_with_dependency_cycle_leaves_wave_count_unset(self) -> None:
        phases = (
            _epic_phase("a", "A", depends_on=("b",)),
            _epic_phase("b", "B", depends_on=("a",)),
        )
        preview = agent_family_plan_preview_from_plan(_plan(phases=phases))

        assert preview.phase_count == 2
        assert preview.wave_count is None

    def test_phase_titles_are_bounded(self) -> None:
        phases = tuple(_epic_phase(str(i), f"Phase {i}") for i in range(9))
        preview = agent_family_plan_preview_from_plan(_plan(phases=phases))

        assert preview.phase_count == 9
        assert len(preview.phase_titles) == 6
        assert preview.phase_titles[0] == "Phase 0"

    def test_epic_with_unavailable_phases_has_no_structure(self) -> None:
        preview = agent_family_plan_preview_from_plan(
            _plan(phase_availability="unavailable", phases=())
        )

        assert preview.kind == "epic"
        assert preview.phase_count is None
        assert preview.wave_count is None
        assert preview.phase_titles == ()

    def test_tale_has_no_phase_structure(self) -> None:
        preview = agent_family_plan_preview_from_plan(
            _plan(
                authored_tier="tale",
                effective_tier="tale",
                phase_availability="not-applicable",
                size="small",
            )
        )

        assert preview.kind == "tale"
        assert preview.phase_count is None
        assert preview.size == "small"

    def test_known_tier_with_missing_title_still_yields_a_preview(self) -> None:
        preview = agent_family_plan_preview_from_plan(
            _plan(
                title=None,
                goal=None,
                authored_tier=None,
                effective_tier="epic",
                phase_availability="unavailable",
            )
        )

        assert preview.kind == "epic"
        assert preview.title is None
        assert not preview.is_empty

    def test_unknown_tier_is_empty(self) -> None:
        preview = agent_family_plan_preview_from_plan(
            _plan(title=None, authored_tier=None, effective_tier=None)
        )

        assert preview is EMPTY_AGENT_FAMILY_PLAN_PREVIEW
        assert preview.is_empty


class TestAgentFamilyPlanPreviewFromBead:
    def test_phase_bead_yields_a_preview(self) -> None:
        preview = agent_family_plan_preview_from_bead(
            bead_type="phase",
            title="Prompt-input completion rows and panel subtitle",
            parent_title="Plan-aware agent-family completion previews",
            size="medium",
        )

        assert preview.kind == "phase"
        assert preview.title == "Prompt-input completion rows and panel subtitle"
        assert preview.parent_title == "Plan-aware agent-family completion previews"
        assert preview.size == "medium"
        assert not preview.is_empty

    def test_task_bead_yields_a_preview(self) -> None:
        preview = agent_family_plan_preview_from_bead(
            bead_type="task",
            title="Fix the flaky selection-health test",
            parent_title=None,
            size=None,
        )

        assert preview.kind == "task"
        assert preview.parent_title is None

    def test_missing_title_is_empty(self) -> None:
        preview = agent_family_plan_preview_from_bead(
            bead_type="phase",
            title=None,
            parent_title=None,
            size=None,
        )

        assert preview is EMPTY_AGENT_FAMILY_PLAN_PREVIEW


class TestAgentFamilyPlanPreviewLabelsAndAccents:
    def test_labels_match_shared_presentation_tables(self) -> None:
        assert agent_family_plan_preview_label("tale") == "Tale"
        assert agent_family_plan_preview_label("epic") == "Epic"
        assert agent_family_plan_preview_label("plan") == "Plan"
        assert agent_family_plan_preview_label("phase") == "Phase"
        assert agent_family_plan_preview_label("task") == "Task"

    def test_accents_match_shared_presentation_tables(self) -> None:
        assert (
            agent_family_plan_preview_accent("tale")
            == PLAN_TIER_PRESENTATIONS["tale"].accent_color
        )
        assert (
            agent_family_plan_preview_accent("epic")
            == PLAN_TIER_PRESENTATIONS["epic"].accent_color
        )
        assert agent_family_plan_preview_accent("plan") == GENERIC_PLAN_ACCENT
        assert (
            agent_family_plan_preview_accent("phase")
            == BEAD_TYPE_PRESENTATIONS["phase"].accent_color
        )
        assert (
            agent_family_plan_preview_accent("task")
            == BEAD_TYPE_PRESENTATIONS["task"].accent_color
        )


class TestAgentFamilyPlanStructureText:
    def test_full_text_includes_phases_and_waves(self) -> None:
        phases = (
            _epic_phase("core", "Core"),
            _epic_phase("docs", "Docs"),
            _epic_phase("render", "Render", depends_on=("core", "docs")),
        )
        preview = agent_family_plan_preview_from_plan(_plan(phases=phases))

        assert (
            agent_family_plan_structure_text(preview, compact=False)
            == "3 phases · 2 waves"
        )

    def test_singular_phase_and_wave_words(self) -> None:
        preview = agent_family_plan_preview_from_plan(
            _plan(phases=(_epic_phase("only", "Only"),))
        )

        assert (
            agent_family_plan_structure_text(preview, compact=False)
            == "1 phase · 1 wave"
        )

    def test_compact_form_drops_waves(self) -> None:
        phases = tuple(_epic_phase(str(i), f"Phase {i}") for i in range(6))
        preview = agent_family_plan_preview_from_plan(_plan(phases=phases))

        assert agent_family_plan_structure_text(preview, compact=True) == "6ph"

    def test_missing_phase_count_is_blank(self) -> None:
        preview = agent_family_plan_preview_from_bead(
            bead_type="phase",
            title="Untitled work",
            parent_title=None,
            size=None,
        )

        assert agent_family_plan_structure_text(preview, compact=False) == ""
        assert agent_family_plan_structure_text(preview, compact=True) == ""

    def test_cycle_omits_wave_segment(self) -> None:
        phases = (
            _epic_phase("a", "A", depends_on=("b",)),
            _epic_phase("b", "B", depends_on=("a",)),
        )
        preview = agent_family_plan_preview_from_plan(_plan(phases=phases))

        assert agent_family_plan_structure_text(preview, compact=False) == "2 phases"


class TestAgentFamilyPlanPreviewDetail:
    def test_epic_detail_includes_kind_structure_and_title(self) -> None:
        phases = (
            _epic_phase("core", "Core"),
            _epic_phase("docs", "Docs"),
            _epic_phase("render", "Render", depends_on=("core", "docs")),
        )
        preview = agent_family_plan_preview_from_plan(_plan(phases=phases))

        assert agent_family_plan_preview_detail(preview) == (
            "epic · 3 phases · 2 waves · Plan-aware agent-family completion previews"
        )

    def test_tale_detail_has_no_structure_segment(self) -> None:
        preview = agent_family_plan_preview_from_plan(
            _plan(
                authored_tier="tale",
                effective_tier="tale",
                phase_availability="not-applicable",
                title="Complete common words from the middle of a word",
            )
        )

        assert agent_family_plan_preview_detail(preview) == (
            "tale · Complete common words from the middle of a word"
        )

    def test_missing_title_uses_fallback(self) -> None:
        preview = agent_family_plan_preview_from_plan(
            _plan(
                title=None,
                authored_tier=None,
                effective_tier="epic",
                phase_availability="unavailable",
            )
        )

        assert (
            agent_family_plan_preview_detail(
                preview, fallback_title="Fix the flaky test"
            )
            == "epic · Fix the flaky test"
        )

    def test_missing_title_without_fallback_is_blank(self) -> None:
        preview = agent_family_plan_preview_from_plan(
            _plan(
                title=None,
                authored_tier=None,
                effective_tier="epic",
                phase_availability="unavailable",
            )
        )

        assert agent_family_plan_preview_detail(preview) == ""

    def test_empty_preview_is_blank(self) -> None:
        assert agent_family_plan_preview_detail(EMPTY_AGENT_FAMILY_PLAN_PREVIEW) == ""


class TestAgentFamilyPlanPreviewDocumentation:
    def test_epic_documentation_lists_bounded_phases(self) -> None:
        phases = (
            _epic_phase("preview", "Shared family plan-preview value", size="medium"),
            _epic_phase("rows", "Prompt-input completion rows", size="medium"),
        )
        preview = agent_family_plan_preview_from_plan(
            _plan(
                title="Plan-aware agent-family completion previews",
                goal="Lead with the tale or epic a family belongs to.",
                phases=phases,
            )
        )

        documentation = agent_family_plan_preview_documentation(preview)

        assert documentation.startswith("**Epic** · 2 phases · 1 wave")
        assert "## Plan-aware agent-family completion previews" in documentation
        assert "Lead with the tale or epic a family belongs to." in documentation
        assert (
            "- `preview` — Shared family plan-preview value (medium)" in documentation
        )
        assert "- `rows` — Prompt-input completion rows (medium)" in documentation

    def test_bead_documentation_notes_parent_title(self) -> None:
        preview = agent_family_plan_preview_from_bead(
            bead_type="phase",
            title="Prompt-input completion rows and panel subtitle",
            parent_title="Plan-aware agent-family completion previews",
            size="medium",
        )

        documentation = agent_family_plan_preview_documentation(preview)

        assert documentation.startswith("**Phase**")
        assert "## Prompt-input completion rows and panel subtitle" in documentation
        assert "_Part of Plan-aware agent-family completion previews_" in documentation

    def test_empty_preview_is_blank(self) -> None:
        assert (
            agent_family_plan_preview_documentation(EMPTY_AGENT_FAMILY_PLAN_PREVIEW)
            == ""
        )

    def test_goal_is_clipped(self) -> None:
        preview = agent_family_plan_preview_from_plan(
            _plan(
                authored_tier="tale",
                effective_tier="tale",
                phase_availability="not-applicable",
                goal="x" * 400,
            )
        )

        documentation = agent_family_plan_preview_documentation(preview)
        goal_line = documentation.splitlines()[-1]

        assert len(goal_line) <= 240
        assert goal_line.endswith("…")


def test_empty_singleton_reports_empty() -> None:
    assert EMPTY_AGENT_FAMILY_PLAN_PREVIEW.is_empty
    assert isinstance(EMPTY_AGENT_FAMILY_PLAN_PREVIEW, AgentFamilyPlanPreview)
