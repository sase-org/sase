"""Epic work-plan tests for ``sase bead work``."""

from __future__ import annotations

import sqlite3

import pytest

from sase.bead.model import Status
from sase.bead.work import (
    CrossEpicBlockerError,
    CycleError,
    EpicPlanError,
    build_epic_work_plan,
    render_multi_prompt,
)
from sase.xprompt.workflow_models import Workflow

from .work_test_helpers import depends, epic, phase, seed, wave_bead_ids


class TestLinearChain:
    def test_three_waves_land_on_all_phases(self, conn: sqlite3.Connection) -> None:
        seed(
            conn,
            [
                epic("e1"),
                phase("p1"),
                phase("p2"),
                phase("p3"),
            ],
        )
        depends(conn, "p2", "p1")
        depends(conn, "p3", "p2")

        plan = build_epic_work_plan(conn, "e1")

        assert len(plan.waves) == 3
        assert wave_bead_ids(plan, 0) == ["p1"]
        assert wave_bead_ids(plan, 1) == ["p2"]
        assert wave_bead_ids(plan, 2) == ["p3"]
        # P1 has no waits; P2 waits on P1; P3 waits on P2.
        assert plan.waves[0][0].waits_on == ()
        assert plan.waves[1][0].waits_on == ("p1",)
        assert plan.waves[2][0].waits_on == ("p2",)
        assert plan.land_waits_on == ("p1", "p2", "p3")
        assert plan.land_agent_name == "e1"


class TestDiamond:
    def _seed_diamond(self, conn: sqlite3.Connection) -> None:
        seed(
            conn,
            [
                epic("e1"),
                phase("p1"),
                phase("p2"),
                phase("p3"),
                phase("p4"),
            ],
        )
        depends(conn, "p2", "p1")
        depends(conn, "p3", "p1")
        depends(conn, "p4", "p2")
        depends(conn, "p4", "p3")

    def test_three_waves_land_on_all_phases(self, conn: sqlite3.Connection) -> None:
        self._seed_diamond(conn)
        plan = build_epic_work_plan(conn, "e1")

        assert len(plan.waves) == 3
        assert wave_bead_ids(plan, 0) == ["p1"]
        assert wave_bead_ids(plan, 1) == ["p2", "p3"]
        assert wave_bead_ids(plan, 2) == ["p4"]
        assert plan.waves[1][0].waits_on == ("p1",)
        assert plan.waves[1][1].waits_on == ("p1",)
        assert plan.waves[2][0].waits_on == ("p2", "p3")
        assert plan.land_waits_on == ("p1", "p2", "p3", "p4")

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
            "%tag:e1\n"
            "%approve\n"
            "#bd/work_phase_bead:p1\n"
            "---\n"
            "%name:p2\n"
            "%tag:e1\n"
            "%approve\n"
            "%w:p1\n"
            "#bd/work_phase_bead:p2\n"
            "---\n"
            "%name:p3\n"
            "%tag:e1\n"
            "%approve\n"
            "%w:p1\n"
            "#bd/work_phase_bead:p3\n"
            "---\n"
            "%name:p4\n"
            "%tag:e1\n"
            "%approve\n"
            "%w:p2,p3\n"
            "#bd/work_phase_bead:p4\n"
            "---\n"
            "%name:e1\n"
            "%tag:e1\n"
            "%w:p1,p2,p3,p4\n"
            "#bd/land_epic:e1"
        )
        assert rendered == expected
        segments = rendered.split("\n---\n")
        assert all("%tag:e1" in segment for segment in segments)
        assert all("%approve" in segment for segment in segments[:-1])
        assert "%approve" not in segments[-1]


class TestMixedDAG:
    def test_land_waits_on_earlier_parallel_phases_too(
        self, conn: sqlite3.Connection
    ) -> None:
        seed(
            conn,
            [
                epic("e1"),
                phase("p1"),
                phase("p2"),
                phase("p3"),
                phase("p4"),
            ],
        )
        depends(conn, "p2", "p1")
        depends(conn, "p3", "p2")

        plan = build_epic_work_plan(conn, "e1")

        assert [wave_bead_ids(plan, i) for i in range(len(plan.waves))] == [
            ["p1", "p4"],
            ["p2"],
            ["p3"],
        ]
        assert plan.waves[1][0].waits_on == ("p1",)
        assert plan.waves[2][0].waits_on == ("p2",)
        assert plan.land_waits_on == ("p1", "p4", "p2", "p3")


class TestIndependentFanOut:
    def test_single_wave_land_waits_on_all(self, conn: sqlite3.Connection) -> None:
        seed(
            conn,
            [
                epic("e1"),
                phase("p1"),
                phase("p2"),
                phase("p3"),
            ],
        )
        plan = build_epic_work_plan(conn, "e1")

        assert len(plan.waves) == 1
        assert wave_bead_ids(plan, 0) == ["p1", "p2", "p3"]
        assert all(a.waits_on == () for a in plan.waves[0])
        assert plan.land_waits_on == ("p1", "p2", "p3")


class TestClosedBlockers:
    def test_in_progress_phase_is_included(self, conn: sqlite3.Connection) -> None:
        seed(
            conn,
            [
                epic("e1"),
                phase("p1", status=Status.IN_PROGRESS),
            ],
        )

        plan = build_epic_work_plan(conn, "e1")

        assert len(plan.waves) == 1
        assert wave_bead_ids(plan, 0) == ["p1"]
        assert plan.land_waits_on == ("p1",)

    def test_in_epic_closed_blocker_does_not_gate(
        self, conn: sqlite3.Connection
    ) -> None:
        seed(
            conn,
            [
                epic("e1"),
                phase("p1", status=Status.CLOSED),
                phase("p2"),
            ],
        )
        depends(conn, "p2", "p1")

        plan = build_epic_work_plan(conn, "e1")

        assert len(plan.waves) == 1
        assert wave_bead_ids(plan, 0) == ["p2"]
        assert plan.waves[0][0].waits_on == ()
        assert plan.land_waits_on == ("p2",)

    def test_closed_blocker_is_omitted_from_rendered_waits(
        self, conn: sqlite3.Connection
    ) -> None:
        seed(
            conn,
            [
                epic("e1"),
                phase("p1", status=Status.CLOSED),
                phase("p2"),
            ],
        )
        depends(conn, "p2", "p1")

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
        seed(
            conn,
            [
                epic("e1"),
                phase("p1", status=Status.CLOSED),
                phase("p2", status=Status.IN_PROGRESS),
                phase("p3"),
            ],
        )
        depends(conn, "p2", "p1")
        depends(conn, "p3", "p2")

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
        seed(
            conn,
            [
                epic("e1"),
                epic("e2"),
                phase("ext", parent_id="e2", status=Status.CLOSED),
                phase("p1"),
            ],
        )
        depends(conn, "p1", "ext")

        plan = build_epic_work_plan(conn, "e1")

        assert len(plan.waves) == 1
        assert wave_bead_ids(plan, 0) == ["p1"]
        assert plan.waves[0][0].waits_on == ()


class TestCrossEpicBlockerRejected:
    def test_open_out_of_epic_blocker_raises(self, conn: sqlite3.Connection) -> None:
        seed(
            conn,
            [
                epic("e1"),
                epic("e2"),
                phase("ext", parent_id="e2"),
                phase("p1"),
            ],
        )
        depends(conn, "p1", "ext")

        with pytest.raises(CrossEpicBlockerError):
            build_epic_work_plan(conn, "e1")


class TestCycleDetection:
    def test_cycle_raises(self, conn: sqlite3.Connection) -> None:
        seed(
            conn,
            [
                epic("e1"),
                phase("p1"),
                phase("p2"),
            ],
        )
        depends(conn, "p1", "p2")
        depends(conn, "p2", "p1")

        with pytest.raises(CycleError):
            build_epic_work_plan(conn, "e1")


class TestEpicValidation:
    def test_missing_epic_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(EpicPlanError):
            build_epic_work_plan(conn, "missing")

    def test_phase_target_raises(self, conn: sqlite3.Connection) -> None:
        seed(conn, [epic("e1"), phase("p1")])
        with pytest.raises(EpicPlanError):
            build_epic_work_plan(conn, "p1")

    def test_no_open_phases_raises(self, conn: sqlite3.Connection) -> None:
        seed(
            conn,
            [
                epic("e1"),
                phase("p1", status=Status.CLOSED),
            ],
        )
        with pytest.raises(EpicPlanError, match="no non-closed phase children"):
            build_epic_work_plan(conn, "e1")
