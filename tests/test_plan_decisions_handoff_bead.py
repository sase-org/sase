"""Bead-read tests for Plan Decisions handoff.

Split from ``tests.test_plan_decisions_handoff``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tests._plan_decisions_handoff_helpers import STAMPED_EPIC

__all__ = [
    "test_bead_read_decisions_wire_and_lines",
    "test_bead_read_epic_audience_differs_from_phase",
    "test_bead_read_epic_lens_and_task_empty",
    "test_bead_read_json_envelope_carries_decisions",
    "test_bead_read_json_envelope_uses_roots_and_empty_roots_absent",
    "test_bead_read_plan_ref_resolves_through_roots",
]


def _write_epic_plan(tmp_path: Path, name: str = "epic.md") -> tuple[Path, Path]:
    plans_root = tmp_path / "plans"
    (plans_root / "202610").mkdir(parents=True, exist_ok=True)
    plan_path = plans_root / "202610" / name
    plan_path.write_text(STAMPED_EPIC, encoding="utf-8")
    return plans_root, plan_path


def test_bead_read_decisions_wire_and_lines(tmp_path: Path) -> None:
    from sase.bead.cli_detail_decisions import (
        decisions_wire_for_detail,
        render_decisions_content_lines,
    )
    from sase.bead.cli_detail_resolution import PlanLink
    from sase.bead.model import Issue, IssueType

    epic_path = tmp_path / "epic.md"
    epic_path.write_text(STAMPED_EPIC, encoding="utf-8")
    phase = Issue(
        id="sase-1hi.4", title="Handoff", issue_type=IssueType.PHASE, design=""
    )
    detail = SimpleNamespace(
        issue=phase,
        plan=PlanLink(
            section="PLAN", source="self", path=str(epic_path), from_ref=None
        ),
    )
    wire = decisions_wire_for_detail(detail)
    assert wire is not None
    assert wire["decided_by"] == "reviewer"
    assert wire["audience"] == "epic_phase"
    assert wire["sheet"]["changed_count"] == 1
    lines = render_decisions_content_lines(wire)
    assert any("Reviewer decisions" in line for line in lines)
    assert any("grouping = mode" in line for line in lines)


def test_bead_read_epic_lens_and_task_empty(tmp_path: Path) -> None:
    from sase.bead.cli_detail_decisions import decisions_wire_for_detail
    from sase.bead.cli_detail_resolution import PlanLink
    from sase.bead.model import BeadTier, Issue, IssueType

    epic_path = tmp_path / "epic.md"
    epic_path.write_text(STAMPED_EPIC, encoding="utf-8")
    epic = Issue(
        id="sase-1hi",
        title="Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        design="",
    )
    epic_detail = SimpleNamespace(
        issue=epic,
        plan=PlanLink(
            section="EPIC PLAN", source="self", path=str(epic_path), from_ref=None
        ),
    )
    task = Issue(id="sase-1", title="Task", issue_type=IssueType.TASK, design="")
    task_detail = SimpleNamespace(issue=task, plan=None)
    epic_wire = decisions_wire_for_detail(epic_detail)
    assert epic_wire is not None
    assert epic_wire["audience"] == "epic_land"
    assert decisions_wire_for_detail(task_detail) is None


def test_bead_read_json_envelope_carries_decisions(tmp_path: Path) -> None:
    from sase.bead.cli_detail_json import issue_detail_wire_dict
    from sase.bead.cli_detail_resolution import IssueDetail, PlanLink
    from sase.bead.model import Issue, IssueType

    epic_path = tmp_path / "epic.md"
    epic_path.write_text(STAMPED_EPIC, encoding="utf-8")
    issue = Issue(
        id="sase-1hi.4",
        title="Handoff",
        issue_type=IssueType.PHASE,
        design=str(epic_path),
    )
    detail = IssueDetail(
        issue=issue,
        ancestors=(),
        phases=(),
        child_epics=(),
        depends_on=(),
        blocks=(),
        plan=PlanLink(
            section="PLAN", source="self", path=str(epic_path), from_ref=None
        ),
    )
    envelope = issue_detail_wire_dict(detail)
    decisions = envelope["decisions"]
    assert isinstance(decisions, dict)
    assert decisions["decided_by"] == "reviewer"
    assert decisions["sheet"]["count"] == 1


def test_bead_read_plan_ref_resolves_through_roots(tmp_path: Path) -> None:
    from types import SimpleNamespace as _NS

    from sase.bead.cli_detail_decisions import (
        decisions_wire_for_detail,
        render_decisions_content_lines,
    )
    from sase.bead.cli_detail_resolution import PlanLink
    from sase.bead.model import Issue, IssueType
    from sase.sdd.plan_decisions import prompt_block_binding

    plans_root, _plan_path = _write_epic_plan(tmp_path)
    ref = "plan:202610/epic.md"
    phase = Issue(
        id="sase-1hi.10.2", title="Phase", issue_type=IssueType.PHASE, design=""
    )
    detail = _NS(
        issue=phase,
        plan=PlanLink(section="PLAN", source="self", path=ref, from_ref=None),
    )
    wire = decisions_wire_for_detail(
        detail, plan_roots=(plans_root,), design_cwd=tmp_path
    )
    assert wire is not None
    assert wire["audience"] == "epic_phase"
    assert wire["decided_by"] == "reviewer"
    expected = prompt_block_binding(
        wire["sheet"], wire["decided_by"], wire["decided_via"], "epic_phase"
    )
    assert render_decisions_content_lines(wire) == [
        f"  {line}" for line in expected.splitlines()
    ]


def test_bead_read_epic_audience_differs_from_phase(tmp_path: Path) -> None:
    from types import SimpleNamespace as _NS

    from sase.bead.cli_detail_decisions import decisions_wire_for_detail
    from sase.bead.cli_detail_resolution import PlanLink
    from sase.bead.model import BeadTier, Issue, IssueType
    from sase.sdd.plan_decisions import prompt_block_binding

    plans_root, _plan_path = _write_epic_plan(tmp_path)
    ref = "plan:202610/epic.md"
    phase = Issue(
        id="sase-1hi.10.2", title="Phase", issue_type=IssueType.PHASE, design=""
    )
    epic = Issue(
        id="sase-1hi.10",
        title="Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        design="",
    )
    phase_wire = decisions_wire_for_detail(
        _NS(
            issue=phase,
            plan=PlanLink(section="PLAN", source="self", path=ref, from_ref=None),
        ),
        plan_roots=(plans_root,),
        design_cwd=tmp_path,
    )
    epic_wire = decisions_wire_for_detail(
        _NS(
            issue=epic,
            plan=PlanLink(section="EPIC PLAN", source="self", path=ref, from_ref=None),
        ),
        plan_roots=(plans_root,),
        design_cwd=tmp_path,
    )
    assert phase_wire is not None and epic_wire is not None
    from sase.bead.cli_detail_decisions import render_decisions_content_lines as _lines2

    assert phase_wire["audience"] == "epic_phase"
    assert epic_wire["audience"] == "epic_land"
    assert phase_wire["sheet"] == epic_wire["sheet"]
    assert _lines2(phase_wire) == [
        f"  {line}"
        for line in prompt_block_binding(
            phase_wire["sheet"],
            phase_wire["decided_by"],
            phase_wire["decided_via"],
            "epic_phase",
        ).splitlines()
    ]
    assert _lines2(epic_wire) == [
        f"  {line}"
        for line in prompt_block_binding(
            epic_wire["sheet"],
            epic_wire["decided_by"],
            epic_wire["decided_via"],
            "epic_land",
        ).splitlines()
    ]


def test_bead_read_json_envelope_uses_roots_and_empty_roots_absent(
    tmp_path: Path,
) -> None:
    from sase.bead.cli_detail_json import issue_detail_wire_dict
    from sase.bead.cli_detail_resolution import IssueDetail, PlanLink
    from sase.bead.model import Issue, IssueType

    plans_root, _plan_path = _write_epic_plan(tmp_path)
    ref = "plan:202610/epic.md"
    issue = Issue(
        id="sase-1hi.10.2", title="Phase", issue_type=IssueType.PHASE, design=ref
    )
    detail = IssueDetail(
        issue=issue,
        ancestors=(),
        phases=(),
        child_epics=(),
        depends_on=(),
        blocks=(),
        plan=PlanLink(section="PLAN", source="self", path=ref, from_ref=None),
    )
    envelope = issue_detail_wire_dict(
        detail, plan_roots=(plans_root,), design_cwd=tmp_path
    )
    assert isinstance(envelope["decisions"], dict)
    assert envelope["decisions"]["audience"] == "epic_phase"
    empty = issue_detail_wire_dict(detail, plan_roots=(), design_cwd=tmp_path)
    assert empty["decisions"] is None
