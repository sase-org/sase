"""Prompt target completion rendering for agent-family plan previews."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.agent_completion import AgentCompletionCandidate
from sase.ace.tui.widgets._prompt_input_bar_completion_panel_labels import (
    agent_completion_subtitle,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_rows_agents import (
    append_agent_completion_row,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.agent_family_plan_preview import AgentFamilyPlanPreview


def _preview(
    kind: str,
    title: str | None,
    *,
    goal: str | None = None,
    parent_title: str | None = None,
    description: str | None = None,
    phase_count: int | None = None,
    wave_count: int | None = None,
    phase_titles: tuple[str, ...] = (),
) -> AgentFamilyPlanPreview:
    return AgentFamilyPlanPreview(
        kind=kind,  # type: ignore[arg-type]
        title=title,
        goal=goal,
        parent_title=parent_title,
        phase_count=phase_count,
        wave_count=wave_count,
        phase_titles=phase_titles,
        phase_ids=tuple(str(index) for index, _title in enumerate(phase_titles)),
        phase_sizes=tuple("small" for _title in phase_titles),
        size=None,
        description=description,
    )


def _candidate(
    *,
    plan_preview: AgentFamilyPlanPreview | None,
    prompt_snippet: str = "Launch prompt snippet",
    member_names: tuple[str, ...] = ("ship--plan", "ship--code"),
) -> AgentCompletionCandidate:
    return AgentCompletionCandidate(
        name="ship",
        label="ship",
        status="RUNNING",
        kind="family",
        member_count=len(member_names),
        aggregate_status="RUNNING",
        member_names=member_names,
        plan_preview=plan_preview,
        prompt_snippet=prompt_snippet,
    )


def _completion(candidate: AgentCompletionCandidate) -> CompletionCandidate:
    return CompletionCandidate(
        display=candidate.name,
        insertion=candidate.name,
        is_dir=False,
        name=candidate.name,
        metadata=candidate,
    )


def _render(candidate: AgentCompletionCandidate, *, budget: int = 80) -> str:
    text = Text()
    append_agent_completion_row(
        text,
        _completion(candidate),
        False,
        inner_width=budget + 50,
    )
    return text.plain


def test_family_row_renders_epic_preview_instead_of_member_names() -> None:
    rendered = _render(
        _candidate(
            plan_preview=_preview(
                "epic",
                "Plan-aware agent-family completion previews",
                phase_count=6,
                wave_count=3,
            )
        )
    )

    assert "Epic" in rendered
    assert "6 phases" in rendered
    assert "3 waves" in rendered
    assert "Plan-aware agent-family completion previews" in rendered
    assert "ship--plan" not in rendered


def test_family_row_renders_tale_phase_and_prompt_rungs() -> None:
    assert "Tale" in _render(
        _candidate(plan_preview=_preview("tale", "Complete common words"))
    )
    assert "Phase" in _render(
        _candidate(plan_preview=_preview("phase", "Prompt-input rows"))
    )

    snippet_row = _render(_candidate(plan_preview=None))
    assert "Launch prompt snippet" in snippet_row
    assert "ship--plan" not in snippet_row


def test_family_row_degrades_structure_before_ellipsizing_title() -> None:
    candidate = _candidate(
        plan_preview=_preview(
            "epic",
            "Plan-aware completion previews",
            phase_count=6,
            wave_count=3,
        )
    )

    assert "6 phases · 3 waves" in _render(candidate, budget=80)
    no_waves = _render(candidate, budget=55)
    assert "6 phases" in no_waves
    assert "waves" not in no_waves
    compact = _render(candidate, budget=47)
    assert "6ph" in compact
    assert "6 phases" not in compact
    no_structure = _render(candidate, budget=40)
    assert "Epic · Plan-aware completion previews" in no_structure
    ellipsized = _render(candidate, budget=24)
    assert "Epic · Plan-aware compl…" in ellipsized


def test_clan_and_tribe_rows_keep_member_preview() -> None:
    for kind in ("clan", "tribe"):
        candidate = AgentCompletionCandidate(
            name="review" if kind == "clan" else "@builders",
            label="review",
            status="RUNNING",
            kind=kind,  # type: ignore[arg-type]
            member_count=2,
            aggregate_status="RUNNING",
            member_names=("review.alpha", "review.beta"),
        )
        rendered = _render(candidate)

        assert "review.alpha, review.beta" in rendered


def test_family_subtitle_uses_epic_phase_titles_with_overflow_count() -> None:
    candidate = _candidate(
        plan_preview=_preview(
            "epic",
            "Epic title",
            phase_count=4,
            phase_titles=("Preview", "Rows", "Editor", "LSP"),
        )
    )

    subtitle = agent_completion_subtitle([_completion(candidate)], 0, 80)

    assert subtitle.plain == "◆ Preview · Rows · Editor +1"


def test_family_subtitle_uses_goal_parent_description_or_members() -> None:
    tale = _candidate(
        plan_preview=_preview("tale", "Tale title", goal="Write the tale")
    )
    phase = _candidate(
        plan_preview=_preview(
            "phase",
            "Phase title",
            parent_title="Parent epic",
            description="Phase detail",
        )
    )
    task = _candidate(
        plan_preview=_preview("task", "Task title", description="Task detail")
    )
    snippet = _candidate(
        plan_preview=None,
        member_names=("ship--plan", "ship--code", "ship--verify", "ship--land"),
    )
    plain_agent = AgentCompletionCandidate("coder", "coder", "RUNNING")

    rows = [
        _completion(tale),
        _completion(phase),
        _completion(task),
        _completion(snippet),
        _completion(plain_agent),
    ]

    assert agent_completion_subtitle(rows, 0, 80).plain == "Write the tale"
    assert agent_completion_subtitle(rows, 1, 80).plain == "Parent epic"
    assert agent_completion_subtitle(rows, 2, 80).plain == "Task detail"
    assert (
        agent_completion_subtitle(rows, 3, 80).plain
        == "ship--plan, ship--code, ship--verify +1"
    )
    assert agent_completion_subtitle(rows, 4, 80).plain == ""
