"""Agents-tab BEAD lane field value, wrapping, and quiet-state tests."""

from __future__ import annotations

import pytest
from rich.cells import cell_len

from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_bead_section import (
    BEAD_FIELD_LABEL_WIDTH,
    BEAD_PLAN_STATE_STYLE,
    BEAD_SECTION_MAX_WIDTH,
)
from sase.ace.tui.widgets.prompt_panel._agent_context_common import (
    COLOR_EMPTY,
    COLOR_REASON,
)
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
from tests.ace.tui.widgets._agent_display_bead_section_helpers import (
    bead_field_lines,
    bead_header,
    bead_summary,
    pin_bead_created_clock,  # noqa: F401 (registers the autouse fixture)
    reconstruct_field_value,
    render_bead_header,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import assert_span_covers


def test_bead_notes_render_literal_multiline_and_wrap_losslessly() -> None:
    notes = (
        "[2026-08-01T14:03:00Z · alice] [ready] first note\n"
        "Second line keeps unicode 界終 and plain [brackets].\n\n"
        "[2026-08-01T14:07:00Z · bob] This follow-up line is long enough "
        "to fold through the existing responsive table without losing words."
    )
    header = bead_header(bead_summary(notes=notes), lane_fold_level=FoldLevel.EXPANDED)

    assert notes in header.plain
    assert header.plain.index("Description:") < header.plain.index("Notes:")
    assert header.plain.index("[ready]") < header.plain.index("界終")
    assert header.plain.index("界終") < header.plain.index("follow-up line")
    assert_span_covers(header, "[ready]", COLOR_REASON)
    assert_span_covers(header, "plain [brackets]", COLOR_REASON)

    for width in (120, 28):
        lines = bead_field_lines(header, "Notes", width=width)
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
    baseline = bead_header(bead_summary(notes=None))
    blank = bead_header(bead_summary(notes=" \n\t "))

    assert BEAD_FIELD_LABEL_WIDTH == cell_len("  Phase Title: ")
    assert blank.plain == baseline.plain
    for width in (120, 28):
        assert render_bead_header(blank, width=width) == render_bead_header(
            baseline, width=width
        )


@pytest.mark.parametrize("size", PHASE_SIZE_VALUES)
def test_bead_size_uses_shared_accessible_chip_palette(
    size: PhaseSizeValue,
) -> None:
    header = bead_header(bead_summary(size=size))

    assert f"Size:  {size} " in header.plain
    assert_span_covers(header, size, PHASE_SIZE_STYLES[size])


def test_bead_size_unavailable_is_quiet_and_visible_to_logical_consumers() -> None:
    header = bead_header(bead_summary(size=None))

    assert "Size: unavailable\n" in header.plain
    assert_span_covers(header, "unavailable", COLOR_EMPTY)


def test_phase_title_unavailable_is_quiet_and_visible() -> None:
    header = bead_header(bead_summary(phase_title=None))

    assert "Phase Title: unavailable\n" in header.plain
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
    header = bead_header(bead_summary(**kwargs))  # type: ignore[arg-type]
    assert value in header.plain

    for width in (120, 28):
        lines = bead_field_lines(header, field, width=width)
        reconstructed = reconstruct_field_value(lines, spaced=" " in value)
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
            phase_bead=bead_summary(actual_path=actual_path),
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
    header = bead_header(
        bead_summary(
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


def test_unknown_plan_path_renders_unavailable_without_hint() -> None:
    hint_state = HeaderHintState(1, {}, "/tmp/workspace", {})
    header, _ = build_header_text(
        make_agent(
            agent_name="sase-42.3",
            phase_bead_id="sase-42.3",
            epic_bead_id="sase-42",
        ),
        summary=DetailHeaderSummary(
            phase_bead=bead_summary(actual_path=None, display_path=None),
        ),
        hint_state=hint_state,
    )

    assert "Epic Plan: unavailable" in header.plain
    assert hint_state.hint_mappings == {}
    assert hint_state.hint_counter == 1
