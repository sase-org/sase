"""Tests for bead preview card render helpers."""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

from rich.console import Console

from sase.ace.tui.modals.bead_preview_render import (
    _abbreviate_home,
    _bead_identity,
    _build_bead_chips,
    bead_card_palette,
    build_bead_loading_title,
    build_bead_meta,
    build_bead_title,
)
from sase.ace.tui.models.bead_preview import BeadPreview, BeadStoreRef
from sase.bead.model import (
    BeadNote,
    BeadTier,
    Issue,
    IssueType,
    Resolution,
    Status,
)


def _render_text(renderable: object) -> str:
    console = Console(file=io.StringIO(), width=100, record=True)
    console.print(renderable)
    return console.export_text()


def _store() -> BeadStoreRef:
    return BeadStoreRef(
        project_key="sase",
        project_label="sase",
        beads_dir=Path("/tmp/beads"),
        primary_workspace=Path("/tmp"),
    )


def _issue(**overrides: object) -> Issue:
    values: dict[str, object] = {
        "id": "sase-1aa",
        "title": "Bead title",
        "status": Status.OPEN,
        "issue_type": IssueType.TASK,
        "description": "A description.",
    }
    values.update(overrides)
    return Issue(**values)  # type: ignore[arg-type]


def _palette() -> object:
    return bead_card_palette(
        SimpleNamespace(background="#1a1a1a", foreground="#f0f0f0")
    )


def test_identity_for_epic_phase_task_flag_and_closed() -> None:
    epic = _issue(issue_type=IssueType.PLAN, tier=BeadTier.EPIC)
    tale = _issue(issue_type=IssueType.PLAN, tier=BeadTier.PLAN)
    plan = _issue(issue_type=IssueType.PLAN, tier=None)
    phase = _issue(issue_type=IssueType.PHASE, parent_id="sase-1aa")
    task = _issue(issue_type=IssueType.TASK, task_type="bug")
    flag = _issue(
        issue_type=IssueType.TASK,
        task_type="flag",
        task_type_fields={
            "key": "plugins_enabled",
            "remove_by_date": "2027-01-01",
            "remove_by_release": "1.0.0",
        },
    )
    assert _bead_identity(epic)[1] == "EPIC"
    assert _bead_identity(tale)[1] == "TALE"
    assert _bead_identity(plan)[1] == "PLAN"
    assert _bead_identity(phase)[1] == "PHASE"
    assert _bead_identity(task)[1] == "TASK · bug"
    assert _bead_identity(flag)[1] == "FLAG"


def test_title_and_chips_for_epic_phase_task_flag_and_closed() -> None:
    palette = _palette()
    epic = _issue(
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        status=Status.IN_PROGRESS,
        title="Epic title",
    )
    title = _render_text(build_bead_title(epic, project_label="sase", palette=palette))
    assert "EPIC" in title
    assert "sase-1aa" in title
    assert "Epic title" in title
    assert "sase" in title
    chips = _render_text(_build_bead_chips(epic, palette=palette))
    assert "in progress" in chips.lower() or "◐" in chips

    phase = _issue(
        issue_type=IssueType.PHASE,
        parent_id="sase-1aa",
        size="medium",
        id="sase-1aa.1",
    )
    phase_title = _render_text(
        build_bead_title(phase, project_label="sase", palette=palette)
    )
    assert "PHASE" in phase_title
    phase_chips = _render_text(_build_bead_chips(phase, palette=palette))
    assert "medium" in phase_chips

    flag = _issue(
        issue_type=IssueType.TASK,
        task_type="flag",
        task_type_fields={
            "key": "plugins_enabled",
            "remove_by_date": "2027-01-01",
            "remove_by_release": "1.0.0",
        },
    )
    flag_title = _render_text(
        build_bead_title(flag, project_label="sase", palette=palette)
    )
    assert "FLAG" in flag_title
    flag_chips = _render_text(_build_bead_chips(flag, palette=palette))
    assert "plugins_enabled" in flag_chips

    closed = _issue(
        status=Status.CLOSED,
        resolution=Resolution.DONE,
        close_reason="shipped",
        closed_at="2026-11-01T00:00:00-04:00",
    )
    closed_chips = _render_text(_build_bead_chips(closed, palette=palette))
    assert "done" in closed_chips.lower() or "closed" in closed_chips.lower()


def test_light_theme_colors_differ_from_dark() -> None:
    dark = bead_card_palette(
        SimpleNamespace(background="#1a1a1a", foreground="#f5f5f5")
    )
    light = bead_card_palette(
        SimpleNamespace(background="#f5f5f5", foreground="#1a1a1a")
    )
    assert dark.plan != light.plan
    assert dark.phase != light.phase
    assert dark.task != light.task


def test_loading_title_and_meta_plan_notes() -> None:
    loading = _render_text(
        build_bead_loading_title(
            "sase-1aa",
            project_label="sase",
            accent="#FFD700",
        )
    )
    assert "sase-1aa" in loading
    assert "sase" in loading

    preview = BeadPreview(
        issue=_issue(
            issue_type=IssueType.PHASE,
            parent_id="sase-1",
            created_at="2026-11-01T00:00:00-04:00",
            updated_at="2026-11-14T00:00:00-04:00",
            notes=[
                BeadNote(
                    id="n1",
                    timestamp="2026-11-14T00:00:00-04:00",
                    author="bryan",
                    text="first line\nsecond line\nthird line\nfourth",
                )
            ],
        ),
        ancestors=(),
        children=(),
        depends_on=(),
        blocks=(),
        store=_store(),
        plan_reference="gmail_archive.md",
        plan_source="parent",
        plan_path=None,
    )
    meta = _render_text(build_bead_meta(preview))
    assert "Plan (epic)" in meta
    assert "cannot resolve" in meta
    assert "Notes" in meta
    assert "first line" in meta
    assert "fourth" not in meta


def test_abbreviate_home() -> None:
    home = str(Path.home())
    assert _abbreviate_home(f"{home}/plans/x.md") == "~/plans/x.md"
    assert _abbreviate_home("/not-home/x.md") == "/not-home/x.md"
