"""Cross-surface regression coverage for bead creation-time rendering.

Every surface listed here was brought under ``sase.bead_time_presentation`` by
the ``sase-fc`` epic. Each test below drives the real (often module-private)
rendering entry point for one surface with a fixture bead and asserts the
creation time is present, so a future change to any of these call sites that
silently drops the creation-time call is caught here rather than by
happenstance elsewhere.

Two surfaces are deliberate, documented exceptions and are intentionally not
covered by a "shows creation time" assertion here; see ``docs/beads.md`` for
why:

- The dependency-edge ``added <ts> by <who>`` line in
  ``cli_dep_list``/``cli_dep_tree`` (the edge's own timestamp, not the bead's;
  already regression-tested by
  ``test_dep_list_rows_carry_the_bead_created_cell_separate_from_edge_provenance``
  and its ``cli_dep_tree`` sibling).
- The artifact-reference completion menu's shared age column, which renders
  ``updated_at`` for both bead and agent rows.
- The bead pages Mermaid lineage graph (``rendering_graph.py``), whose node
  labels stay minimal for diagram readability; the full instant is one click
  away in the same page's identity block.
"""

from __future__ import annotations

from types import MappingProxyType

import pytest

from sase.ace.tui.models.agent_associated_plan import BeadSummary, _task_bead_summary
from sase.ace.tui.widgets._artifact_ref_entity_catalogs import _bead_candidate
from sase.ace.tui.widgets.artifacts.beads_detail import bead_preview_markdown
from sase.ace.tui.widgets.artifacts.beads_rendering import _bead_text
from sase.ace.tui.widgets.prompt_panel._agent_bead_section import ResponsiveBeadSection
from sase.bead.cli_dep_list import print_bead_dep_list
from sase.bead.cli_dep_tree import print_bead_dep_tree
from sase.bead.cli_detail import render_issue_detail
from sase.bead.cli_detail_resolution import IssueDetail, IssueRef
from sase.bead.cli_query import _render_list_compact, _render_search_compact
from sase.bead.dep_graph import DepGraph
from sase.bead.model import (
    BeadSearchMatch,
    BeadTier,
    Dependency,
    Issue,
    IssueType,
)
from sase.bead.task_gate import (
    render_task_triage_preview,
    task_triage_presentation_note,
)
from sase.bead_pages.associations import BeadAssociationIndex
from sase.bead_pages.rendering_identity import _lifecycle_facts
from sase.bead_pages.rendering_tables import render_dependencies, render_phases
from sase.bead_pages.roster import render_bead_pages_roster_bytes
from sase.bead_time_presentation import BEAD_CREATED_GLYPH
from sase.integrations._mobile_helper_beads import _bead_summary_wire
from sase.scripts.sase_clan_summary_epic import _header_line, _phase_lines

# The store's canonical shape, matching the fixtures in
# tests/test_bead_time_presentation.py so the expected local rendering here
# stays consistent with the presentation module's own tests.
CREATED_AT = "2026-04-28T01:34:17Z"
CREATED_LOCAL = "2026-04-27 21:34:17 EDT"
CREATED_DATE = "2026-04-27"

EPIC = Issue(
    "sase-time",
    "Present bead pages",
    issue_type=IssueType.PLAN,
    tier=BeadTier.EPIC,
    created_at=CREATED_AT,
)
PHASE = Issue(
    "sase-time.1",
    "Ship it",
    issue_type=IssueType.PHASE,
    parent_id=EPIC.id,
    created_at=CREATED_AT,
)
TASK = Issue(
    "sase-time-task",
    "Fix the flaky linter",
    issue_type=IssueType.TASK,
    created_at=CREATED_AT,
)

_EMPTY_ASSOCIATIONS = BeadAssociationIndex(MappingProxyType({}))


def _detail(issue: Issue, **overrides: object) -> IssueDetail:
    fields: dict[str, object] = {
        "issue": issue,
        "ancestors": (),
        "phases": (),
        "child_epics": (),
        "depends_on": (),
        "blocks": (),
        "plan": None,
    }
    fields.update(overrides)
    return IssueDetail(**fields)  # type: ignore[arg-type]


def test_cli_show_full_detail_renders_created_section() -> None:
    rendered = render_issue_detail(_detail(TASK), relativize_design=False)

    assert "\nCREATED\n" in rendered
    assert CREATED_LOCAL in rendered


def test_cli_list_compact_row_carries_created_cell() -> None:
    rendered = _render_list_compact([TASK], use_color=False)

    assert BEAD_CREATED_GLYPH in rendered


def test_cli_search_compact_row_carries_created_cell() -> None:
    match = BeadSearchMatch(issue=TASK, matched_fields=["title"])
    rendered = _render_search_compact([match], "linter", use_color=False)

    assert BEAD_CREATED_GLYPH in rendered


def test_cli_dep_list_row_carries_the_beads_own_created_cell(
    capsys: pytest.CaptureFixture[str],
) -> None:
    dependent = Issue(
        PHASE.id,
        PHASE.title,
        issue_type=PHASE.issue_type,
        parent_id=PHASE.parent_id,
        created_at=PHASE.created_at,
        dependencies=[
            Dependency(
                issue_id=PHASE.id,
                depends_on_id=TASK.id,
                created_at="2026-05-01T00:00:00Z",
            )
        ],
    )
    graph = DepGraph.build([dependent, TASK])

    print_bead_dep_list(
        graph,
        scope=PHASE.id,
        direction="both",
        statuses=None,
        limit=0,
        output_format="compact",
        color="never",
    )
    output = capsys.readouterr().out

    assert BEAD_CREATED_GLYPH in output


def test_cli_dep_tree_row_carries_the_beads_own_created_cell(
    capsys: pytest.CaptureFixture[str],
) -> None:
    dependent = Issue(
        PHASE.id,
        PHASE.title,
        issue_type=PHASE.issue_type,
        parent_id=PHASE.parent_id,
        created_at=PHASE.created_at,
        dependencies=[
            Dependency(
                issue_id=PHASE.id,
                depends_on_id=TASK.id,
                created_at="2026-05-01T00:00:00Z",
            )
        ],
    )
    graph = DepGraph.build([dependent, TASK])

    print_bead_dep_tree(
        graph,
        scope=PHASE.id,
        direction="out",
        statuses=None,
        levels=0,
        output_format="compact",
        color="never",
    )
    output = capsys.readouterr().out

    assert BEAD_CREATED_GLYPH in output


def test_task_triage_gate_preview_shows_absolute_created() -> None:
    preview = render_task_triage_preview(
        bead_id=TASK.id,
        title=TASK.title,
        description="",
        notes="",
        created_at=CREATED_AT,
    )

    assert f"**Created:** {CREATED_LOCAL}" in preview


def test_task_triage_presentation_note_shows_immutable_created_date() -> None:
    note = task_triage_presentation_note(TASK.id, TASK.title, 0, created_at=CREATED_AT)

    assert f"{BEAD_CREATED_GLYPH} {CREATED_DATE}" in note


def test_context_lane_task_row_renders_created() -> None:
    text = ResponsiveBeadSection(summary=_task_bead_summary(TASK)).logical_text

    assert "Created" in text.plain
    assert CREATED_LOCAL in text.plain


def test_context_lane_phase_row_renders_created() -> None:
    summary = BeadSummary(
        id=PHASE.id,
        phase_title=PHASE.title,
        description=None,
        actual_plan_path=None,
        display_plan_path=None,
        plan_exists=False,
        plan_readable=False,
        epic_title=EPIC.title,
        size=None,
        created_at=PHASE.created_at,
        bead_type="phase",
    )
    text = ResponsiveBeadSection(summary=summary).logical_text

    assert "Created" in text.plain
    assert CREATED_LOCAL in text.plain


def test_ace_beads_pane_row_carries_created_chip() -> None:
    text = _bead_text(TASK, triage=False, plan_link=False, project_badge=None)

    assert BEAD_CREATED_GLYPH in text.plain


def test_ace_beads_detail_preview_includes_created_history_line() -> None:
    rendered = bead_preview_markdown(TASK, None, project="proj")

    assert f"- Created: {CREATED_LOCAL}" in rendered


def test_artifact_ref_bead_candidate_detail_includes_created_age() -> None:
    candidate = _bead_candidate(TASK)

    assert BEAD_CREATED_GLYPH in candidate.detail


def test_mobile_bead_summary_wire_carries_raw_created_at() -> None:
    wire = _bead_summary_wire(TASK, None, [TASK], None)

    assert wire["created_at"] == CREATED_AT


def test_bead_page_identity_lifecycle_facts_include_created() -> None:
    facts = _lifecycle_facts(TASK)

    assert f"**Created:** {CREATED_LOCAL}" in facts


def test_bead_page_phase_table_has_created_column() -> None:
    detail = _detail(EPIC, phases=(IssueRef(PHASE.id, PHASE),))

    rendered = "\n".join(render_phases(detail, _EMPTY_ASSOCIATIONS))

    assert "| Created |" in rendered
    assert CREATED_DATE in rendered


def test_bead_page_dependency_row_shows_created_suffix() -> None:
    detail = _detail(PHASE, depends_on=(IssueRef(TASK.id, TASK),))

    rendered = "\n".join(render_dependencies(detail))

    assert f"{BEAD_CREATED_GLYPH} {CREATED_DATE}" in rendered


def test_bead_page_roster_has_created_column() -> None:
    rendered = render_bead_pages_roster_bytes((EPIC,), _EMPTY_ASSOCIATIONS).decode()

    assert "| Created |" in rendered
    assert CREATED_DATE in rendered


def test_clan_summary_header_and_phase_lines_carry_created_chip() -> None:
    header = _header_line(EPIC)
    phase_lines = _phase_lines(1, PHASE)

    assert BEAD_CREATED_GLYPH in header.plain
    assert BEAD_CREATED_GLYPH in phase_lines[0].plain
