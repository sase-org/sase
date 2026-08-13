"""Public shared plan-display loading and rendering tests."""

from __future__ import annotations

from pathlib import Path

from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from sase.ace.tui.widgets.prompt_panel._agent_plan_section import (
    ResponsivePlanSection,
)
from sase.phase_size_presentation import PHASE_SIZE_DEFAULT_MARKER, PHASE_SIZE_STYLES
from sase.sdd.plan_display import (
    BEAD_PAGE_ROW_LABEL,
    COLOR_PLAN_EMPTY,
    COLOR_PLAN_PATH,
    COLOR_PLAN_PATH_BASENAME,
    COLOR_PLAN_PRIMARY,
    PLAN_FIELD_LABEL_WIDTH,
    PLAN_PROVENANCE_ENTRY_LIMIT,
    PLAN_SIZE_ROW_LABEL,
    PlanDisplay,
    PlanDisplayPhase,
    bead_page_url_text,
    load_plan_display,
    plan_field_rows,
    plan_logical_text,
    render_plan_document,
    render_plan_lines,
)
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN

_PROVENANCE_HEADER = """- **PROMPT:** [202607/prompts/tale.md](prompts/tale.md)
- **PARENT:** [202607/epic.md](https://example.invalid/plans/blob/main/202607/epic.md)
- **BEAD:** [sase-ai.8](https://example.invalid/beads/blob/main/pages/sase-ai/sase-ai.8.md)
- **AGENTS:**
  - [user.host.sase-1a.1](https://example.invalid/agents/blob/main/agents/user.host.sase-1a.1/README.md)
  - user.host.sase-1a.2
- **COMMITS:**
  - [1a67048](https://example.invalid/repo/commit/1a67048fbac199943e9798dd65f8af8901b2986b) — fix: dismiss stale
    buttons
"""


def _plan_with_header(header: str) -> str:
    frontmatter, body = VALID_TALE_PLAN.split("---\n", 2)[1:]
    return f"---\n{frontmatter}---\n\n{header}\n{body}"


def test_shared_loader_normalizes_valid_tale_and_reports_missing(
    tmp_path: Path,
) -> None:
    tale = tmp_path / "tale.md"
    tale.write_text(
        VALID_TALE_PLAN.replace(
            "Approved implementation",
            "Approved   implementation",
        ).replace(
            "Deliver the approved implementation",
            "Deliver   the\n  approved implementation",
        ),
        encoding="utf-8",
    )

    loaded = load_plan_display(tale, display_path="plans/tale.md")
    missing = load_plan_display(tmp_path / "missing.md")

    assert loaded.validation_ok
    assert loaded.title == "Approved implementation"
    assert loaded.goal == "Deliver the approved implementation"
    assert loaded.authored_tier == "tale"
    assert loaded.size == "small"
    assert not loaded.size_defaulted
    assert loaded.phase_availability == "not-applicable"
    assert loaded.display_path == "plans/tale.md"
    assert not missing.validation_ok
    assert not missing.exists
    assert not missing.readable


def test_shared_loader_converts_epic_phases_and_renderer_matches_tui_logical_text(
    tmp_path: Path,
) -> None:
    epic = tmp_path / "epic.md"
    epic.write_text(VALID_EPIC_PLAN, encoding="utf-8")

    loaded = load_plan_display(epic, display_path="plans/epic.md")
    shared = plan_logical_text(loaded)
    tui = ResponsivePlanSection(loaded).logical_text

    assert loaded.validation_ok
    assert loaded.phase_availability == "available"
    assert [phase.id for phase in loaded.phases] == ["implementation"]
    assert shared.plain == tui.plain
    assert shared.spans == tui.spans
    lines = render_plan_lines(loaded, width=32)
    assert all(cell_len(line.plain) <= 32 for line in lines)


def test_provenance_rows_follow_fields_and_match_tui_section(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "tale.md"
    plan.write_text(_plan_with_header(_PROVENANCE_HEADER), encoding="utf-8")

    loaded = load_plan_display(plan, display_path="plan:202607/tale.md")
    shared = plan_logical_text(loaded)
    tui = ResponsivePlanSection(loaded).logical_text
    rows = [line for line in shared.plain.splitlines() if line[:9].endswith(": ")]

    assert [section.kind.value for section in loaded.provenance] == [
        "PROMPT",
        "PARENT",
        "BEAD",
        "AGENTS",
        "COMMITS",
    ]
    assert [section.targets for section in loaded.provenance] == [
        ("prompts/tale.md",),
        ("https://example.invalid/plans/blob/main/202607/epic.md",),
        ("https://example.invalid/beads/blob/main/pages/sase-ai/sase-ai.8.md",),
        (
            "https://example.invalid/agents/blob/main/agents/"
            "user.host.sase-1a.1/README.md",
            None,
        ),
        (
            "https://example.invalid/repo/commit/"
            "1a67048fbac199943e9798dd65f8af8901b2986b",
        ),
    ]
    path_row_index = rows.index("   Path: plan:202607/tale.md")
    assert rows[path_row_index + 1 :] == [
        " Prompt: 202607/prompts/tale.md",
        " Parent: 202607/epic.md",
        "   Bead: sase-ai.8",
        " Agents: user.host.sase-1a.1, user.host.sase-1a.2",
        "Commits: 1a67048",
    ]
    assert shared.plain == tui.plain
    assert shared.spans == tui.spans


def test_provenance_rows_are_absent_without_a_header_block(tmp_path: Path) -> None:
    plan = tmp_path / "tale.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")

    loaded = load_plan_display(plan, display_path="plan:202607/tale.md")

    assert loaded.provenance == ()
    assert "Agents: " not in plan_logical_text(loaded).plain


def test_provenance_row_summarizes_entries_beyond_the_display_limit(
    tmp_path: Path,
) -> None:
    agents = "\n".join(
        f"  - user.host.sase-1a.{index}"
        for index in range(1, PLAN_PROVENANCE_ENTRY_LIMIT + 3)
    )
    plan = tmp_path / "tale.md"
    plan.write_text(
        _plan_with_header(f"- **AGENTS:**\n{agents}\n"),
        encoding="utf-8",
    )

    loaded = load_plan_display(plan, display_path="plan:202607/tale.md")
    agents_row = next(
        line
        for line in plan_logical_text(loaded).plain.splitlines()
        if line.startswith(" Agents: ")
    )

    assert agents_row.count(", ") == PLAN_PROVENANCE_ENTRY_LIMIT
    assert agents_row.endswith("+2 more")


def test_malformed_header_block_leaves_authored_metadata_visible(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "tale.md"
    plan.write_text(
        _plan_with_header(
            "- **PROMPT:** [202607/prompts/tale.md](prompts/tale.md)\n"
            "- **PROMPT:** [202607/prompts/other.md](prompts/other.md)\n"
        ),
        encoding="utf-8",
    )

    loaded = load_plan_display(plan, display_path="plan:202607/tale.md")

    # A malformed header block is a validation error (``header-invalid``), but
    # the plan's authored title and goal stay visible for display purposes.
    assert not loaded.validation_ok
    assert any(
        "header block is invalid" in diagnostic
        for diagnostic in loaded.validation_diagnostics
    )
    assert loaded.title == "Approved implementation"
    assert loaded.provenance == ()


def test_shared_renderer_starts_fitting_basename_on_continuation_line(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "absolute.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    display_path = "/var/lib/sase/workspaces/very/long/checkout/absolute.md"
    loaded = load_plan_display(plan, display_path=display_path)

    width = 32
    lines = render_plan_lines(loaded, width=width)
    path_index = next(
        index for index, line in enumerate(lines) if line.plain.startswith("   Path: ")
    )
    path_fragments = [
        line.plain[PLAN_FIELD_LABEL_WIDTH:] for line in lines[path_index:]
    ]

    assert "".join(path_fragments) == display_path
    assert path_fragments[-1] == plan.name
    assert all(cell_len(line.plain) <= width for line in lines)


def test_shared_renderer_folds_overlong_basename_without_loss(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    basename = "absolute_plan_filename_that_exceeds_the_width.md"
    display_path = f"/var/lib/sase/{basename}"
    loaded = load_plan_display(plan, display_path=display_path)

    width = 24
    lines = render_plan_lines(loaded, width=width)
    path_index = next(
        index for index, line in enumerate(lines) if line.plain.startswith("   Path: ")
    )
    path_fragments = [
        line.plain[PLAN_FIELD_LABEL_WIDTH:] for line in lines[path_index:]
    ]

    assert "".join(path_fragments) == display_path
    assert all(cell_len(line.plain) <= width for line in lines)


def test_render_plan_document_omits_page_row_by_default(tmp_path: Path) -> None:
    plan = tmp_path / "tale.md"
    plan.write_text(_plan_with_header(_PROVENANCE_HEADER), encoding="utf-8")
    loaded = load_plan_display(plan, display_path="plan:202607/tale.md")

    rendered = render_plan_document(loaded, width=76)

    assert rendered.lines == render_plan_lines(loaded, width=76)
    assert all(BEAD_PAGE_ROW_LABEL not in line.plain for line in rendered.lines)


def test_render_plan_document_places_page_after_bead_row(tmp_path: Path) -> None:
    plan = tmp_path / "tale.md"
    plan.write_text(_plan_with_header(_PROVENANCE_HEADER), encoding="utf-8")
    loaded = load_plan_display(plan, display_path="plan:202607/tale.md")
    page_url = (
        "https://github.com/sase-org/sase--beads/blob/main/pages/sase-ai/sase-ai.8.md"
    )

    lines = render_plan_document(
        loaded,
        width=48,
        bead_page_url=page_url,
    ).lines
    bead_index = next(
        index for index, line in enumerate(lines) if line.plain.startswith("   Bead: ")
    )
    page_line = lines[bead_index + 1]

    assert page_line.plain == BEAD_PAGE_ROW_LABEL + page_url
    assert page_line.plain.startswith("   Page: https://")
    assert sum(line.plain.count(page_url) for line in lines) == 1
    assert cell_len(page_line.plain) > 48
    assert all(cell_len(line.plain) <= 48 for line in lines if line is not page_line)


def test_render_plan_document_places_page_after_final_non_bead_provenance(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "tale.md"
    plan.write_text(
        _plan_with_header(
            "- **PROMPT:** [202607/prompts/tale.md](prompts/tale.md)\n"
            "- **AGENTS:**\n"
            "  - user.host.sase-1a.1\n"
        ),
        encoding="utf-8",
    )
    loaded = load_plan_display(plan, display_path="plan:202607/tale.md")
    page_url = "https://example.invalid/pages/sase-ai/README.md"

    lines = render_plan_document(
        loaded,
        width=76,
        bead_page_url=page_url,
    ).lines

    assert lines[-2].plain.startswith(" Agents: ")
    assert lines[-1].plain == BEAD_PAGE_ROW_LABEL + page_url


def test_bead_page_line_reflows_without_inserting_url_whitespace(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "tale.md"
    plan.write_text(_plan_with_header(_PROVENANCE_HEADER), encoding="utf-8")
    loaded = load_plan_display(plan, display_path="plan:202607/tale.md")
    page_url = (
        "https://github.com/sase-org/sase--beads/blob/main/pages/sase-ar/README.md"
    )
    page_line = next(
        line
        for line in render_plan_document(
            loaded,
            width=48,
            bead_page_url=page_url,
        ).lines
        if page_url in line.plain
    )

    for width in (96, 82, 81, 52):
        console = Console(
            width=width,
            color_system=None,
            force_terminal=False,
            force_interactive=False,
            highlight=False,
            markup=False,
            emoji=False,
        )
        fragments = [
            line.plain
            for line in page_line.wrap(
                console,
                width,
                overflow="fold",
                no_wrap=False,
            )
        ]

        if width >= 82:
            assert len(fragments) == 1
        else:
            assert fragments[0] == BEAD_PAGE_ROW_LABEL
            assert all(
                fragment and not fragment[0].isspace() for fragment in fragments[1:]
            )
        assert "".join(fragments).removeprefix(BEAD_PAGE_ROW_LABEL) == page_url


def test_bead_page_url_text_handles_url_shapes() -> None:
    trailing = "https://example.invalid/pages/sase-ai/"
    bare = "README.md"
    multibyte = "https://example.invalid/pages/sase-ai/界.md"

    trailing_text = bead_page_url_text(trailing)
    bare_text = bead_page_url_text(bare)
    multibyte_text = bead_page_url_text(multibyte)

    assert trailing_text.plain == trailing
    assert len(trailing_text.spans) == 1
    assert (
        trailing_text.spans[0].start,
        trailing_text.spans[0].end,
        str(trailing_text.spans[0].style),
    ) == (0, len(trailing), COLOR_PLAN_PATH)

    assert bare_text.plain == bare
    assert str(bare_text.spans[0].style) == COLOR_PLAN_PATH_BASENAME

    assert multibyte_text.plain == multibyte
    assert [str(span.style) for span in multibyte_text.spans] == [
        COLOR_PLAN_PATH,
        COLOR_PLAN_PATH_BASENAME,
    ]
    assert all(
        text.overflow is None and text.no_wrap is None
        for text in (trailing_text, bare_text, multibyte_text)
    )


_INDEPENDENT_EPIC_PLAN = """---
tier: epic
title: Independent phases
goal: Exercise the wave-count renderer with fully parallel phases.
phases:
  - id: alpha
    title: Alpha
    depends_on: []
    size: small
  - id: beta
    title: Beta
    depends_on: []
    size: small
  - id: gamma
    title: Gamma
    depends_on: []
    size: small
---
# Plan
"""


def _counts_value(rows: tuple[tuple[str, Text], ...]) -> Text:
    return next(value for label, value in rows if label == " Counts: ")


def _size_value(rows: tuple[tuple[str, Text], ...]) -> Text:
    return next(value for label, value in rows if label == PLAN_SIZE_ROW_LABEL)


def test_plan_field_rows_omit_counts_by_default(tmp_path: Path) -> None:
    epic = tmp_path / "epic.md"
    epic.write_text(VALID_EPIC_PLAN, encoding="utf-8")
    loaded = load_plan_display(epic, display_path="plans/epic.md")

    rows = plan_field_rows(loaded)

    assert [label for label, _value in rows] == ["  Title: ", "   Goal: ", "   Path: "]


def test_plan_field_rows_place_counts_between_goal_and_path_when_opted_in(
    tmp_path: Path,
) -> None:
    epic = tmp_path / "epic.md"
    epic.write_text(VALID_EPIC_PLAN, encoding="utf-8")
    loaded = load_plan_display(epic, display_path="plans/epic.md")

    rows = plan_field_rows(loaded, include_counts=True)

    assert [label for label, _value in rows] == [
        "  Title: ",
        "   Goal: ",
        " Counts: ",
        "   Path: ",
    ]
    assert cell_len(" Counts: ") == PLAN_FIELD_LABEL_WIDTH
    counts_value = _counts_value(rows)
    assert counts_value.plain == "1 phase · 1 wave"
    numeral_span = next(
        span for span in counts_value.spans if span.start == 0 and span.end == 1
    )
    assert str(numeral_span.style) == COLOR_PLAN_PRIMARY


def test_plan_field_rows_keep_path_last_regardless_of_include_counts(
    tmp_path: Path,
) -> None:
    epic = tmp_path / "epic.md"
    epic.write_text(VALID_EPIC_PLAN, encoding="utf-8")
    loaded = load_plan_display(epic, display_path="plans/epic.md")

    for include_counts in (False, True):
        rows = plan_field_rows(loaded, include_counts=include_counts)
        assert rows[-1][0] == "   Path: "


def test_plan_field_rows_pluralize_counts_for_multiple_phases_and_one_wave(
    tmp_path: Path,
) -> None:
    epic = tmp_path / "epic.md"
    epic.write_text(_INDEPENDENT_EPIC_PLAN, encoding="utf-8")
    loaded = load_plan_display(epic, display_path="plans/epic.md")

    rows = plan_field_rows(loaded, include_counts=True)

    assert _counts_value(rows).plain == "3 phases · 1 wave"


def test_plan_field_rows_omit_counts_for_a_tale_even_when_opted_in(
    tmp_path: Path,
) -> None:
    tale = tmp_path / "tale.md"
    tale.write_text(VALID_TALE_PLAN, encoding="utf-8")
    loaded = load_plan_display(tale, display_path="plans/tale.md")

    rows = plan_field_rows(loaded, include_counts=True)

    assert [label for label, _value in rows] == [
        "  Title: ",
        "   Goal: ",
        PLAN_SIZE_ROW_LABEL,
        "   Path: ",
    ]


def test_plan_field_rows_render_authored_tale_size_chip(tmp_path: Path) -> None:
    tale = tmp_path / "tale.md"
    tale.write_text(VALID_TALE_PLAN, encoding="utf-8")
    loaded = load_plan_display(tale, display_path="plans/tale.md")

    rows = plan_field_rows(loaded)
    size_value = _size_value(rows)

    assert loaded.size == "small"
    assert not loaded.size_defaulted
    assert [label for label, _value in rows] == [
        "  Title: ",
        "   Goal: ",
        PLAN_SIZE_ROW_LABEL,
        "   Path: ",
    ]
    assert cell_len(PLAN_SIZE_ROW_LABEL) == PLAN_FIELD_LABEL_WIDTH
    assert size_value.plain == " small "
    assert str(size_value.style) == PHASE_SIZE_STYLES["small"]


def test_plan_field_rows_render_legacy_tale_size_as_defaulted(
    tmp_path: Path,
) -> None:
    tale = tmp_path / "legacy.md"
    tale.write_text(VALID_TALE_PLAN.replace("size: small\n", ""), encoding="utf-8")
    loaded = load_plan_display(tale, display_path="plans/legacy.md")

    size_value = _size_value(plan_field_rows(loaded))

    assert loaded.validation_ok
    assert loaded.size == "medium"
    assert loaded.size_defaulted
    assert size_value.plain == f" medium  {PHASE_SIZE_DEFAULT_MARKER}"
    assert str(size_value.style) == PHASE_SIZE_STYLES["medium"]
    marker_span = size_value.spans[-1]
    assert size_value.plain[marker_span.start : marker_span.end] == (
        f" {PHASE_SIZE_DEFAULT_MARKER}"
    )
    assert str(marker_span.style) == COLOR_PLAN_EMPTY


def test_plan_field_rows_render_legacy_over_sized_tale_as_defaulted(
    tmp_path: Path,
) -> None:
    tale = tmp_path / "oversized.md"
    tale.write_text(
        VALID_TALE_PLAN.replace("size: small\n", "size: large\n"), encoding="utf-8"
    )
    loaded = load_plan_display(tale, display_path="plans/oversized.md")

    size_value = _size_value(plan_field_rows(loaded))

    assert loaded.validation_ok
    assert loaded.size == "medium"
    assert loaded.size_defaulted
    assert size_value.plain == f" medium  {PHASE_SIZE_DEFAULT_MARKER}"


def test_plan_field_rows_omit_plan_level_size_for_epics(tmp_path: Path) -> None:
    epic = tmp_path / "epic.md"
    epic.write_text(VALID_EPIC_PLAN, encoding="utf-8")
    loaded = load_plan_display(epic, display_path="plans/epic.md")

    rows = plan_field_rows(loaded)

    assert loaded.size is None
    assert not loaded.size_defaulted
    assert PLAN_SIZE_ROW_LABEL not in [label for label, _value in rows]


def test_plan_field_rows_render_invalid_tale_size_as_unavailable(
    tmp_path: Path,
) -> None:
    tale = tmp_path / "invalid.md"
    tale.write_text(VALID_TALE_PLAN.replace("size: small", "size: nonsense"), "utf-8")
    loaded = load_plan_display(tale, display_path="plans/invalid.md")

    size_value = _size_value(plan_field_rows(loaded))

    assert not loaded.validation_ok
    assert loaded.size is None
    assert not loaded.size_defaulted
    assert size_value.plain == "unavailable"
    assert str(size_value.style) == COLOR_PLAN_EMPTY


def test_unavailable_plan_metadata_has_no_plan_level_size(tmp_path: Path) -> None:
    metadata = load_plan_display(tmp_path / "missing.md")

    assert metadata.size is None
    assert not metadata.size_defaulted


def test_plan_field_rows_report_unavailable_counts_when_phase_data_is_unavailable(
    tmp_path: Path,
) -> None:
    broken = tmp_path / "broken.md"
    broken.write_text(
        "---\ntier: epic\ntitle: Broken\n---\n# Plan\n",
        encoding="utf-8",
    )
    loaded = load_plan_display(broken, display_path="plans/broken.md")
    assert loaded.phase_availability == "unavailable"

    rows = plan_field_rows(loaded, include_counts=True)
    counts_value = _counts_value(rows)

    assert counts_value.plain == "unavailable"
    assert str(counts_value.style) == COLOR_PLAN_EMPTY


def test_plan_field_rows_keep_phase_count_and_flag_waves_unavailable_for_a_cycle() -> (
    None
):
    phases = (
        PlanDisplayPhase(
            id="a",
            title="A",
            depends_on=("b",),
            description=None,
            size="small",
            model=None,
        ),
        PlanDisplayPhase(
            id="b",
            title="B",
            depends_on=("a",),
            description=None,
            size="small",
            model=None,
        ),
    )
    summary = PlanDisplay(
        title="Cyclic epic",
        goal="Exercise the defensive renderer boundary.",
        authored_tier="epic",
        effective_tier="epic",
        actual_path="/tmp/cyclic.md",
        display_path="plans/cyclic.md",
        committed=True,
        exists=True,
        readable=True,
        frontmatter_readable=True,
        phase_availability="available",
        phases=phases,
        validation_ok=True,
    )

    rows = plan_field_rows(summary, include_counts=True)
    counts_value = _counts_value(rows)

    assert counts_value.plain == "2 phases · waves unavailable"
