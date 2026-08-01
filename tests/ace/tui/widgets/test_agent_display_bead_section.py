"""Agents-tab SASE CONTEXT phase BEAD lane rendering tests."""

from __future__ import annotations

from io import StringIO

import pytest
from rich.cells import cell_len
from rich.console import Console

from sase.ace.tui.models.agent_associated_plan import BeadSummary, PhaseBeadSummary
from sase.bead.model import TaskPlusOneEvidence
from sase.ace.tui.widgets.prompt_panel._agent_bead_section import (
    BEAD_FIELD_LABEL_WIDTH,
    BEAD_PLAN_STATE_STYLE,
    BEAD_SECTION_MAX_WIDTH,
)
from sase.ace.tui.widgets.prompt_panel._agent_context_common import (
    COLOR_ARTIFACT_FILE_BASENAME,
    COLOR_BEAD_PRIMARY,
    COLOR_BEAD_SUBHEADER,
    COLOR_EMPTY,
    COLOR_REASON,
    COLOR_SUMMARY,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_header import AgentHeader
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    DetailHeaderSummary,
    HeaderHintState,
    build_header_text,
)
from sase.phase_size_presentation import (
    PHASE_SIZE_STYLES,
    PHASE_SIZE_VALUES,
    PhaseSizeValue,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import assert_span_covers


def _bead_summary(
    *,
    bead_id: str = "sase-42.3",
    description: str | None = "Render only this selected phase.",
    actual_path: str | None = "/tmp/workspace/sase/repos/plans/202607/epic plan.md",
    display_path: str | None = "sase/repos/plans/202607/epic plan.md",
    exists: bool = True,
    readable: bool = True,
    phase_title: str | None = "Responsive BEAD lane",
    epic_title: str | None = "Phase bead context lane",
    size: PhaseSizeValue | None = "medium",
    notes: str | None = None,
) -> PhaseBeadSummary:
    return PhaseBeadSummary(
        id=bead_id,
        phase_title=phase_title,
        description=description,
        actual_plan_path=actual_path,
        display_plan_path=display_path,
        plan_exists=exists,
        plan_readable=readable,
        epic_title=epic_title,
        size=size,
        notes=notes,
    )


def _header(summary: PhaseBeadSummary) -> AgentHeader:
    header, _ = build_header_text(
        make_agent(
            agent_name="worker",
            phase_bead_id=summary.id,
            epic_bead_id=summary.id.rsplit(".", maxsplit=1)[0],
        ),
        summary=DetailHeaderSummary(phase_bead=summary),
    )
    return header


def _render(header: AgentHeader, *, width: int) -> list[str]:
    output = StringIO()
    console = Console(file=output, width=width, color_system=None)
    console.print(header, end="")
    return output.getvalue().splitlines()


def _field_lines(header: AgentHeader, label: str, *, width: int) -> list[str]:
    lines = _render(header, width=width)
    start = next(
        index
        for index, line in enumerate(lines)
        if line[:BEAD_FIELD_LABEL_WIDTH].strip() == f"{label}:"
    )
    result = [lines[start]]
    prefix = " " * BEAD_FIELD_LABEL_WIDTH
    for line in lines[start + 1 :]:
        if not line.startswith(prefix):
            break
        result.append(line)
    return result


def _reconstruct(lines: list[str], *, spaced: bool) -> str:
    values = [line[BEAD_FIELD_LABEL_WIDTH:].rstrip() for line in lines]
    return (" " if spaced else "").join(values)


def test_bead_lane_has_exact_field_order_alignment_palette_and_no_old_row() -> None:
    header = _header(_bead_summary())
    plain = header.plain

    assert "Bead:" not in plain
    assert "▸ BEAD · ↳ phase sase-42.3\n" in plain
    assert "ID:" not in plain
    assert "Notes:" not in plain
    assert plain.count("sase-42.3") == 1
    assert (
        plain.index("▸ BEAD · ↳ phase sase-42.3")
        < plain.index("Phase Title:")
        < plain.index("Description:")
    )
    assert plain.index("Description:") < plain.index("Size:")
    assert plain.index("Size:") < plain.index("Epic Plan:")
    assert plain.index("Epic Plan:") < plain.index("Epic Title:")
    field_lines = [
        line
        for line in plain.splitlines()
        if any(
            label in line
            for label in (
                "Phase Title:",
                "Description:",
                "Size:",
                "Epic Plan:",
                "Epic Title:",
            )
        )
    ]
    assert {line.index(":") for line in field_lines} == {13}
    assert_span_covers(header, "▸ BEAD", COLOR_BEAD_SUBHEADER)
    assert_span_covers(header, "phase", COLOR_SUMMARY)
    assert_span_covers(header, "sase-42.3", COLOR_BEAD_PRIMARY)
    assert_span_covers(header, "Responsive BEAD lane", COLOR_BEAD_PRIMARY)
    assert_span_covers(header, "Render only this selected phase.", COLOR_REASON)
    assert_span_covers(header, "medium", PHASE_SIZE_STYLES["medium"])
    assert_span_covers(header, "epic plan.md", COLOR_ARTIFACT_FILE_BASENAME)
    assert_span_covers(header, "Phase bead context lane", COLOR_BEAD_PRIMARY)

    for width in (120, 28):
        rendered = "".join(_render(header, width=width))
        assert rendered.count("sase-42.3") == 1
        assert "…" not in rendered


def test_task_and_phase_notes_follow_description() -> None:
    notes = "[2026-08-01T14:09:00Z · bryan] ready for implementation"
    phase = _header(_bead_summary(notes=notes))
    phase_plain = phase.plain

    assert (
        phase_plain.index("Description:")
        < phase_plain.index("Notes:")
        < phase_plain.index("Size:")
    )

    task_summary = BeadSummary(
        id="sase-task.4",
        phase_title="Task lane",
        description="Show only task-owned metadata.",
        actual_plan_path=None,
        display_plan_path=None,
        plan_exists=False,
        plan_readable=False,
        epic_title=None,
        size="medium",
        bead_type="task",
        notes=notes,
    )
    task_header, _ = build_header_text(
        make_agent(agent_name=task_summary.id),
        summary=DetailHeaderSummary(phase_bead=task_summary),
    )
    task_plain = task_header.plain

    assert (
        task_plain.index("Description:")
        < task_plain.index("Notes:")
        < task_plain.index("Size:")
    )
    assert "Task Title:" in task_plain
    assert "Epic Plan:" not in task_plain


def test_task_bead_lane_renders_plus_one_count_and_evidence() -> None:
    evidence = TaskPlusOneEvidence(
        timestamp="2026-08-01T15:00:00Z",
        reporter="agent.beta",
        note="Independent reproduction.",
        refs=("research:202608/cache.md",),
    )
    task_summary = BeadSummary(
        id="sase-task.5",
        phase_title="Corroborated task",
        description="Carry evidence into the Agents tab.",
        actual_plan_path=None,
        display_plan_path=None,
        plan_exists=False,
        plan_readable=False,
        epic_title=None,
        size="medium",
        bead_type="task",
        plus_one_evidence=(evidence,),
    )

    header, _ = build_header_text(
        make_agent(agent_name=task_summary.id),
        summary=DetailHeaderSummary(phase_bead=task_summary),
    )

    assert "[+1]" in header.plain
    assert "+1 Reports:" in header.plain
    assert "1 +1 report" in header.plain
    assert "+1 Evidence:" in header.plain
    assert "+1 agent.beta · 2026-08-01T15:00:00Z" in header.plain
    assert "research:202608/cache.md" in header.plain


def test_bead_notes_render_literal_multiline_and_wrap_losslessly() -> None:
    notes = (
        "[2026-08-01T14:03:00Z · alice] [ready] first note\n"
        "Second line keeps unicode 界終 and plain [brackets].\n\n"
        "[2026-08-01T14:07:00Z · bob] This follow-up line is long enough "
        "to fold through the existing responsive table without losing words."
    )
    header = _header(_bead_summary(notes=notes))

    assert notes in header.plain
    assert header.plain.index("Description:") < header.plain.index("Notes:")
    assert header.plain.index("[ready]") < header.plain.index("界終")
    assert header.plain.index("界終") < header.plain.index("follow-up line")
    assert_span_covers(header, "[ready]", COLOR_REASON)
    assert_span_covers(header, "plain [brackets]", COLOR_REASON)

    for width in (120, 28):
        lines = _field_lines(header, "Notes", width=width)
        rendered = "\n".join(lines)
        assert all(
            cell_len(line) <= min(width, BEAD_SECTION_MAX_WIDTH) for line in lines
        )
        assert all(line.startswith(" " * BEAD_FIELD_LABEL_WIDTH) for line in lines[1:])
        assert "…" not in rendered
        normalized = " ".join(rendered.split())
        for token in ("[ready]", "unicode", "界終", "follow-up"):
            assert token in rendered
        for token in ("plain [brackets]", "responsive table"):
            assert token in normalized


def test_blank_notes_omit_row_and_keep_note_free_shape() -> None:
    baseline = _header(_bead_summary(notes=None))
    blank = _header(_bead_summary(notes=" \n\t "))

    assert BEAD_FIELD_LABEL_WIDTH == cell_len("  Phase Title: ")
    assert blank.plain == baseline.plain
    for width in (120, 28):
        assert _render(blank, width=width) == _render(baseline, width=width)


def test_phase_and_epic_titles_render_distinct_values() -> None:
    header = _header(
        _bead_summary(
            phase_title="Selected phase title",
            epic_title="Parent epic title",
        )
    )

    assert "Phase Title: Selected phase title\n" in header.plain
    assert "Epic Title: Parent epic title\n" in header.plain


@pytest.mark.parametrize("size", PHASE_SIZE_VALUES)
def test_bead_size_uses_shared_accessible_chip_palette(
    size: PhaseSizeValue,
) -> None:
    header = _header(_bead_summary(size=size))

    assert f"Size:  {size} " in header.plain
    assert_span_covers(header, size, PHASE_SIZE_STYLES[size])


def test_bead_size_unavailable_is_quiet_and_visible_to_logical_consumers() -> None:
    header = _header(_bead_summary(size=None))

    assert "Size: unavailable\n" in header.plain
    assert_span_covers(header, "unavailable", COLOR_EMPTY)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("Description", " ".join(f"description{index}" for index in range(32))),
        ("Description", "description_token_that_must_retain_the_complete_suffix"),
        ("Description", "界" * 24 + "終"),
        ("Phase Title", " ".join(f"phase{index}" for index in range(32))),
        ("Phase Title", "phase_title_token_that_must_retain_the_complete_suffix"),
        ("Phase Title", "相" * 24 + "終"),
        ("Epic Title", " ".join(f"title{index}" for index in range(32))),
        ("Epic Title", "epic_title_token_that_must_retain_the_complete_suffix"),
        ("Epic Title", "題" * 24 + "終"),
        ("Epic Plan", "sase/repos/plans/202607/path with complete spaces.md"),
        ("Epic Plan", "sase/repos/plans/202607/" + "界" * 18 + "終.md"),
    ],
)
def test_bead_values_wrap_losslessly_with_hanging_indent(
    field: str,
    value: str,
) -> None:
    kwargs: dict[str, str] = {}
    if field == "Description":
        kwargs["description"] = value
    elif field == "Phase Title":
        kwargs["phase_title"] = value
    elif field == "Epic Title":
        kwargs["epic_title"] = value
    else:
        kwargs["display_path"] = value
        kwargs["actual_path"] = f"/tmp/workspace/{value}"
    header = _header(_bead_summary(**kwargs))  # type: ignore[arg-type]
    assert value in header.plain

    for width in (120, 28):
        lines = _field_lines(header, field, width=width)
        reconstructed = _reconstruct(lines, spaced=" " in value)
        if field == "Epic Plan" and " " in value:
            assert reconstructed.replace(" ", "") == value.replace(" ", "")
        else:
            assert reconstructed == value
        assert all(
            cell_len(line) <= min(width, BEAD_SECTION_MAX_WIDTH) for line in lines
        )
        assert all(line.startswith(" " * BEAD_FIELD_LABEL_WIDTH) for line in lines[1:])
        assert "…" not in "".join(lines)


def test_bead_plan_hint_uses_actual_path_with_spaces() -> None:
    actual_path = "/tmp/workspace/sase/repos/plans/202607/epic plan.md"
    hint_state = HeaderHintState(4, {}, "/tmp/workspace", {})
    header, _ = build_header_text(
        make_agent(
            agent_name="sase-42.3",
            phase_bead_id="sase-42.3",
            epic_bead_id="sase-42",
        ),
        summary=DetailHeaderSummary(
            phase_bead=_bead_summary(actual_path=actual_path),
        ),
        hint_state=hint_state,
    )

    assert "Epic Plan: [4] sase/repos/plans/202607/epic plan.md" in header.plain
    assert hint_state.hint_mappings == {4: actual_path}
    assert hint_state.hint_counter == 5


@pytest.mark.parametrize(
    ("exists", "readable", "suffix"),
    [(False, False, " (missing)"), (True, False, " (unreadable)")],
)
def test_known_unavailable_plan_keeps_path_and_quiet_state(
    exists: bool,
    readable: bool,
    suffix: str,
) -> None:
    header = _header(
        _bead_summary(
            phase_title=None,
            description=None,
            exists=exists,
            readable=readable,
            epic_title=None,
            size=None,
        )
    )

    assert f"Epic Plan: sase/repos/plans/202607/epic plan.md{suffix}" in header.plain
    assert header.plain.count("unavailable") == 4
    assert_span_covers(header, suffix.strip(), BEAD_PLAN_STATE_STYLE)
    assert_span_covers(header, "unavailable", COLOR_EMPTY)


def test_phase_title_unavailable_is_quiet_and_visible() -> None:
    header = _header(_bead_summary(phase_title=None))

    assert "Phase Title: unavailable\n" in header.plain
    assert_span_covers(header, "unavailable", COLOR_EMPTY)


def test_task_bead_lane_uses_type_identity_without_epic_fields() -> None:
    summary = BeadSummary(
        id="sase-task.4",
        phase_title="Task lane",
        description="Show only task-owned metadata.",
        actual_plan_path=None,
        display_plan_path=None,
        plan_exists=False,
        plan_readable=False,
        epic_title=None,
        size="medium",
        bead_type="task",
    )
    header, _ = build_header_text(
        make_agent(agent_name=summary.id),
        summary=DetailHeaderSummary(phase_bead=summary),
    )

    assert "▸ BEAD · ◆ task sase-task.4\n" in header.plain
    assert "Task Title: Task lane\n" in header.plain
    assert "Description: Show only task-owned metadata.\n" in header.plain
    assert "Size:  medium " in header.plain
    assert "Phase Title:" not in header.plain
    assert "Epic Plan:" not in header.plain
    assert "Epic Title:" not in header.plain
    assert_span_covers(header, "◆", "bold #D787FF")


def test_unknown_plan_path_renders_unavailable_without_hint() -> None:
    hint_state = HeaderHintState(1, {}, "/tmp/workspace", {})
    header, _ = build_header_text(
        make_agent(
            agent_name="sase-42.3",
            phase_bead_id="sase-42.3",
            epic_bead_id="sase-42",
        ),
        summary=DetailHeaderSummary(
            phase_bead=_bead_summary(actual_path=None, display_path=None),
        ),
        hint_state=hint_state,
    )

    assert "Epic Plan: unavailable" in header.plain
    assert hint_state.hint_mappings == {}
    assert hint_state.hint_counter == 1


def test_cheap_phase_header_does_no_enrichment_or_bead_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("cheap header must stay memory-only")

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_associated_plan.resolve_agent_plan_enrichment",
        fail,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_header.cached_bead_display",
        fail,
    )
    header, _ = build_header_text(
        make_agent(
            agent_name="sase-42.3",
            phase_bead_id="sase-42.3",
            epic_bead_id="sase-42",
        ),
        cheap=True,
    )

    assert "Bead:" not in header.plain
    assert "▸ BEAD" not in header.plain
    assert "SASE CONTEXT" not in header.plain
