"""Public shared plan-display loading and rendering tests."""

from __future__ import annotations

from pathlib import Path

from rich.cells import cell_len

from sase.ace.tui.widgets.prompt_panel._agent_plan_section import (
    ResponsivePlanSection,
)
from sase.sdd.plan_display import (
    PLAN_FIELD_LABEL_WIDTH,
    PLAN_PROVENANCE_ENTRY_LIMIT,
    load_plan_display,
    plan_logical_text,
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

    loaded = load_plan_display(plan, display_path="plans:202607/tale.md")
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
    assert rows[3:] == [
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

    loaded = load_plan_display(plan, display_path="plans:202607/tale.md")

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

    loaded = load_plan_display(plan, display_path="plans:202607/tale.md")
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

    loaded = load_plan_display(plan, display_path="plans:202607/tale.md")

    assert loaded.validation_ok
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
