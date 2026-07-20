"""Public shared plan-display loading and rendering tests."""

from __future__ import annotations

from pathlib import Path

from rich.cells import cell_len

from sase.ace.tui.widgets.prompt_panel._agent_plan_section import (
    ResponsivePlanSection,
)
from sase.sdd.plan_display import (
    load_plan_display,
    plan_logical_text,
    render_plan_lines,
)
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN


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
