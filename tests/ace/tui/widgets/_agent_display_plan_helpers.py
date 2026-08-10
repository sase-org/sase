"""Shared builders and render helpers for agent plan display tests."""

from __future__ import annotations

from io import StringIO

from rich.console import Console
from rich.style import Style

from sase.ace.tui.models.agent_associated_plan import (
    AssociatedPlanPhaseSummary,
    AssociatedPlanSummary,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_header import AgentHeader
from sase.ace.tui.widgets.prompt_panel._agent_plan_section import (
    PLAN_FIELD_LABEL_WIDTH,
)


def plan_summary(
    *,
    title: str | None = "Required plan titles",
    goal: str | None = "Make agent intent immediately legible.",
    tier: str | None = "plan",
    size: str | None = "medium",
    size_defaulted: bool = False,
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
        size=None if tier == "epic" else size,  # type: ignore[arg-type]
        size_defaulted=tier != "epic" and size_defaulted,
    )


def epic_summary(
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
                size="small",
                model=None,
            ),
            AssociatedPlanPhaseSummary(
                id="render",
                title="Responsive phase renderer",
                depends_on=("core",),
                description="Render every phase without truncation.",
                size="medium",
                model="codex/gpt-5.6-sol",
            ),
            AssociatedPlanPhaseSummary(
                id="verify",
                title="Responsive verification",
                depends_on=("core", "render"),
                description=None,
                size="large",
                model=None,
            ),
        )
    return plan_summary(
        tier="epic",
        phase_availability=phase_availability,
        phases=phases,
    )


def render_header(header: AgentHeader, *, width: int) -> list[str]:
    output = StringIO()
    console = Console(file=output, width=width, color_system=None)
    console.print(header, end="")
    return output.getvalue().splitlines()


def rendered_text_with_style(
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


def rendered_goal_lines(header: AgentHeader, *, width: int) -> list[str]:
    return _rendered_field_lines(header, width=width, label="Goal:")


def rendered_title_lines(header: AgentHeader, *, width: int) -> list[str]:
    return _rendered_field_lines(header, width=width, label="Title:")


def _rendered_field_lines(
    header: AgentHeader,
    *,
    width: int,
    label: str,
) -> list[str]:
    lines = render_header(header, width=width)
    start = next(
        index
        for index, line in enumerate(lines)
        if line[:PLAN_FIELD_LABEL_WIDTH].strip() == label
    )
    field_lines = [lines[start]]
    continuation_prefix = " " * PLAN_FIELD_LABEL_WIDTH
    for line in lines[start + 1 :]:
        if not line.startswith(continuation_prefix):
            break
        field_lines.append(line)
    return field_lines


def reconstruct_word_wrapped_field(lines: list[str]) -> str:
    return " ".join(line[PLAN_FIELD_LABEL_WIDTH:].rstrip() for line in lines)


def reconstruct_folded_token(lines: list[str]) -> str:
    return "".join(line[PLAN_FIELD_LABEL_WIDTH:].rstrip() for line in lines)


def covering_style(header: AgentHeader, needle: str) -> Style:
    start = header.plain.index(needle)
    end = start + len(needle)
    styles = [
        Style.parse(str(span.style))
        for span in header.spans
        if span.start <= start and span.end >= end
    ]
    assert len(styles) == 1
    return styles[0]


def style_color(style: str):  # type: ignore[no-untyped-def]
    color = Style.parse(style).color
    assert color is not None
    return color.get_truecolor()
