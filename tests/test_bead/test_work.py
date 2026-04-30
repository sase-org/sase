"""Unit tests for the DAG → wave plan → multi-prompt builder."""

from __future__ import annotations

import sqlite3

import pytest

from sase.bead import db
from sase.bead.model import Issue, IssueType, Status
from sase.bead.work import (
    CrossEpicBlockerError,
    CycleError,
    EpicPlanError,
    EpicWorkPlan,
    PhaseAssignment,
    build_epic_work_plan,
    render_multi_prompt,
)
from sase.xprompt.workflow_models import Workflow

NOW = "2026-04-25T00:00:00Z"


@pytest.fixture
def conn() -> sqlite3.Connection:
    return db.create_memory_db()


def _epic(epic_id: str = "e1") -> Issue:
    return Issue(
        id=epic_id,
        title=f"Epic {epic_id}",
        issue_type=IssueType.PLAN,
        parent_id=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _phase(
    phase_id: str,
    parent_id: str = "e1",
    *,
    status: Status = Status.OPEN,
    created_at: str = NOW,
) -> Issue:
    return Issue(
        id=phase_id,
        title=f"Phase {phase_id}",
        issue_type=IssueType.PHASE,
        parent_id=parent_id,
        status=status,
        created_at=created_at,
        updated_at=created_at,
    )


def _seed(conn: sqlite3.Connection, issues: list[Issue]) -> None:
    for issue in issues:
        db.create_issue(conn, issue)


def _depends(conn: sqlite3.Connection, child: str, blocker: str) -> None:
    db.add_dependency(conn, child, blocker, NOW)


def _wave_bead_ids(plan: EpicWorkPlan, wave_index: int) -> list[str]:
    assignments: tuple[PhaseAssignment, ...] = plan.waves[wave_index]
    return [a.bead_id for a in assignments]


class TestLinearChain:
    def test_three_waves_land_on_p3(self, conn: sqlite3.Connection) -> None:
        _seed(
            conn,
            [
                _epic("e1"),
                _phase("p1"),
                _phase("p2"),
                _phase("p3"),
            ],
        )
        _depends(conn, "p2", "p1")
        _depends(conn, "p3", "p2")

        plan = build_epic_work_plan(conn, "e1")

        assert len(plan.waves) == 3
        assert _wave_bead_ids(plan, 0) == ["p1"]
        assert _wave_bead_ids(plan, 1) == ["p2"]
        assert _wave_bead_ids(plan, 2) == ["p3"]
        # P1 has no waits; P2 waits on P1; P3 waits on P2.
        assert plan.waves[0][0].waits_on == ()
        assert plan.waves[1][0].waits_on == ("p1",)
        assert plan.waves[2][0].waits_on == ("p2",)
        # Land waits on the leaf (P3).
        assert plan.land_waits_on == ("p3",)
        assert plan.land_agent_name == "e1.land"


class TestDiamond:
    def _seed_diamond(self, conn: sqlite3.Connection) -> None:
        _seed(
            conn,
            [
                _epic("e1"),
                _phase("p1"),
                _phase("p2"),
                _phase("p3"),
                _phase("p4"),
            ],
        )
        _depends(conn, "p2", "p1")
        _depends(conn, "p3", "p1")
        _depends(conn, "p4", "p2")
        _depends(conn, "p4", "p3")

    def test_three_waves_land_on_p4(self, conn: sqlite3.Connection) -> None:
        self._seed_diamond(conn)
        plan = build_epic_work_plan(conn, "e1")

        assert len(plan.waves) == 3
        assert _wave_bead_ids(plan, 0) == ["p1"]
        assert _wave_bead_ids(plan, 1) == ["p2", "p3"]
        assert _wave_bead_ids(plan, 2) == ["p4"]
        assert plan.waves[1][0].waits_on == ("p1",)
        assert plan.waves[1][1].waits_on == ("p1",)
        assert plan.waves[2][0].waits_on == ("p2", "p3")
        assert plan.land_waits_on == ("p4",)

    def test_diamond_render_snapshot(self, conn: sqlite3.Connection) -> None:
        self._seed_diamond(conn)
        plan = build_epic_work_plan(conn, "e1")

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )

        expected = (
            "%name:p1\n"
            "%approve\n"
            "#bd/work_phase_bead:p1\n"
            "---\n"
            "%name:p2\n"
            "%approve\n"
            "%w:p1\n"
            "#bd/work_phase_bead:p2\n"
            "---\n"
            "%name:p3\n"
            "%approve\n"
            "%w:p1\n"
            "#bd/work_phase_bead:p3\n"
            "---\n"
            "%name:p4\n"
            "%approve\n"
            "%w:p2,p3\n"
            "#bd/work_phase_bead:p4\n"
            "---\n"
            "%name:e1.land\n"
            "%approve\n"
            "%w:p4\n"
            "#bd/land_epic:e1"
        )
        assert rendered == expected


class TestIndependentFanOut:
    def test_single_wave_land_waits_on_all(self, conn: sqlite3.Connection) -> None:
        _seed(
            conn,
            [
                _epic("e1"),
                _phase("p1"),
                _phase("p2"),
                _phase("p3"),
            ],
        )
        plan = build_epic_work_plan(conn, "e1")

        assert len(plan.waves) == 1
        assert _wave_bead_ids(plan, 0) == ["p1", "p2", "p3"]
        assert all(a.waits_on == () for a in plan.waves[0])
        assert plan.land_waits_on == ("p1", "p2", "p3")


class TestClosedBlockers:
    def test_in_progress_phase_is_included(self, conn: sqlite3.Connection) -> None:
        _seed(
            conn,
            [
                _epic("e1"),
                _phase("p1", status=Status.IN_PROGRESS),
            ],
        )

        plan = build_epic_work_plan(conn, "e1")

        assert len(plan.waves) == 1
        assert _wave_bead_ids(plan, 0) == ["p1"]
        assert plan.land_waits_on == ("p1",)

    def test_in_epic_closed_blocker_does_not_gate(
        self, conn: sqlite3.Connection
    ) -> None:
        _seed(
            conn,
            [
                _epic("e1"),
                _phase("p1", status=Status.CLOSED),
                _phase("p2"),
            ],
        )
        _depends(conn, "p2", "p1")

        plan = build_epic_work_plan(conn, "e1")

        assert len(plan.waves) == 1
        assert _wave_bead_ids(plan, 0) == ["p2"]
        assert plan.waves[0][0].waits_on == ()
        assert plan.land_waits_on == ("p2",)

    def test_closed_blocker_is_omitted_from_rendered_waits(
        self, conn: sqlite3.Connection
    ) -> None:
        _seed(
            conn,
            [
                _epic("e1"),
                _phase("p1", status=Status.CLOSED),
                _phase("p2"),
            ],
        )
        _depends(conn, "p2", "p1")

        plan = build_epic_work_plan(conn, "e1")
        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )

        assert "#bd/work_phase_bead:p1" not in rendered
        assert "%w:p1" not in rendered
        assert "#bd/work_phase_bead:p2" in rendered

    def test_mixed_closed_and_non_closed_phases_render_only_remaining(
        self, conn: sqlite3.Connection
    ) -> None:
        _seed(
            conn,
            [
                _epic("e1"),
                _phase("p1", status=Status.CLOSED),
                _phase("p2", status=Status.IN_PROGRESS),
                _phase("p3"),
            ],
        )
        _depends(conn, "p2", "p1")
        _depends(conn, "p3", "p2")

        plan = build_epic_work_plan(conn, "e1")
        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )

        assert "#bd/work_phase_bead:p1" not in rendered
        assert "#bd/work_phase_bead:p2" in rendered
        assert "#bd/work_phase_bead:p3" in rendered
        assert "%w:p2" in rendered
        assert "#bd/land_epic:e1" in rendered

    def test_out_of_epic_closed_blocker_is_accepted(
        self, conn: sqlite3.Connection
    ) -> None:
        _seed(
            conn,
            [
                _epic("e1"),
                _epic("e2"),
                _phase("ext", parent_id="e2", status=Status.CLOSED),
                _phase("p1"),
            ],
        )
        _depends(conn, "p1", "ext")

        plan = build_epic_work_plan(conn, "e1")

        assert len(plan.waves) == 1
        assert _wave_bead_ids(plan, 0) == ["p1"]
        assert plan.waves[0][0].waits_on == ()


class TestCrossEpicBlockerRejected:
    def test_open_out_of_epic_blocker_raises(self, conn: sqlite3.Connection) -> None:
        _seed(
            conn,
            [
                _epic("e1"),
                _epic("e2"),
                _phase("ext", parent_id="e2"),
                _phase("p1"),
            ],
        )
        _depends(conn, "p1", "ext")

        with pytest.raises(CrossEpicBlockerError):
            build_epic_work_plan(conn, "e1")


class TestCycleDetection:
    def test_cycle_raises(self, conn: sqlite3.Connection) -> None:
        _seed(
            conn,
            [
                _epic("e1"),
                _phase("p1"),
                _phase("p2"),
            ],
        )
        _depends(conn, "p1", "p2")
        _depends(conn, "p2", "p1")

        with pytest.raises(CycleError):
            build_epic_work_plan(conn, "e1")


class TestEpicValidation:
    def test_missing_epic_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(EpicPlanError):
            build_epic_work_plan(conn, "missing")

    def test_phase_target_raises(self, conn: sqlite3.Connection) -> None:
        _seed(conn, [_epic("e1"), _phase("p1")])
        with pytest.raises(EpicPlanError):
            build_epic_work_plan(conn, "p1")

    def test_no_open_phases_raises(self, conn: sqlite3.Connection) -> None:
        _seed(
            conn,
            [
                _epic("e1"),
                _phase("p1", status=Status.CLOSED),
            ],
        )
        with pytest.raises(EpicPlanError, match="no non-closed phase children"):
            build_epic_work_plan(conn, "e1")


class TestRenderEdgeCases:
    def test_user_override_xprompt_names_propagate(
        self, conn: sqlite3.Connection
    ) -> None:
        _seed(conn, [_epic("e1"), _phase("p1")])
        plan = build_epic_work_plan(conn, "e1")

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="custom/work_phase"),
            land_epic_xprompt=Workflow(name="custom/land"),
        )

        assert "#custom/work_phase:p1" in rendered
        assert "#custom/land:e1" in rendered

    def test_phase_agent_name_uses_bead_id(self, conn: sqlite3.Connection) -> None:
        _seed(
            conn,
            [
                _epic("sase-r"),
                _phase("sase-r.1", parent_id="sase-r"),
            ],
        )
        plan = build_epic_work_plan(conn, "sase-r")
        assert plan.waves[0][0].agent_name == "sase-r.1"
        assert plan.land_agent_name == "sase-r.land"
