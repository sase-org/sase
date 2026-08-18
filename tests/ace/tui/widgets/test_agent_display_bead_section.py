"""Agents-tab SASE CONTEXT phase BEAD lane shape and presence tests."""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets.prompt_panel._agent_context_common import (
    COLOR_ARTIFACT_FILE_BASENAME,
    COLOR_BEAD_PRIMARY,
    COLOR_BEAD_SUBHEADER,
    COLOR_REASON,
    COLOR_SUMMARY,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from sase.bead_time_presentation import BEAD_TIME_RICH_STYLE
from sase.phase_size_presentation import PHASE_SIZE_STYLES
from tests.ace.tui.widgets._agent_display_bead_section_helpers import (
    CREATED_LABEL,
    bead_header,
    bead_summary,
    pin_bead_created_clock,  # noqa: F401 (registers the autouse fixture)
    render_bead_header,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import assert_span_covers


def test_bead_lane_has_exact_field_order_alignment_palette_and_no_old_row() -> None:
    header = bead_header(bead_summary())
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
    assert plain.index("Epic Title:") < plain.index("Created:")
    assert f"Created: {CREATED_LABEL}\n" in plain
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
                "Created:",
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
    assert_span_covers(header, CREATED_LABEL, BEAD_TIME_RICH_STYLE)

    for width in (120, 28):
        rendered = "".join(render_bead_header(header, width=width))
        assert rendered.count("sase-42.3") == 1
        assert "…" not in rendered


def test_phase_and_epic_titles_render_distinct_values() -> None:
    header = bead_header(
        bead_summary(
            phase_title="Selected phase title",
            epic_title="Parent epic title",
        )
    )

    assert "Phase Title: Selected phase title\n" in header.plain
    assert "Epic Title: Parent epic title\n" in header.plain


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
