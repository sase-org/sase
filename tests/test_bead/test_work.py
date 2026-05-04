"""Unit tests for the DAG → wave plan → multi-prompt builder."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from sase.bead import db
from sase.bead.model import BeadTier, Issue, IssueType, Status
from sase.bead.project import BeadProject
from sase.bead.work import (
    ChangeSpecLaunchContext,
    CrossEpicBlockerError,
    CycleError,
    EpicPlanError,
    EpicWorkPlan,
    LegendEpicAssignment,
    LegendPlanError,
    LegendWorkPlan,
    PhaseAssignment,
    VCSLaunchContext,
    build_epic_work_plan,
    build_legend_work_plan,
    build_legend_work_plan_from_beads_dir,
    render_legend_multi_prompt,
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


def _legend(
    legend_id: str = "l1",
    *,
    epic_count: int | None = 3,
    design: str = "sdd/legends/202605/roadmap.md",
) -> Issue:
    return Issue(
        id=legend_id,
        title=f"Legend {legend_id}",
        issue_type=IssueType.PLAN,
        tier=BeadTier.LEGEND,
        epic_count=epic_count,
        design=design,
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
        assert plan.land_agent_name == "e1"


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
            "%name:e1\n"
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


class TestLegendWorkPlan:
    def test_builds_linear_epic_assignments(self, conn: sqlite3.Connection) -> None:
        _seed(conn, [_legend("l1", epic_count=3)])

        plan = build_legend_work_plan(conn, "l1")

        assert isinstance(plan, LegendWorkPlan)
        assert plan.legend_id == "l1"
        assert plan.plan_file == "sdd/legends/202605/roadmap.md"
        assert all(isinstance(a, LegendEpicAssignment) for a in plan.assignments)
        assert [a.epic_number for a in plan.assignments] == [1, 2, 3]
        assert [a.agent_name for a in plan.assignments] == [
            "l1.1.0",
            "l1.2.0",
            "l1.3.0",
        ]
        assert [a.waits_on for a in plan.assignments] == [
            (),
            ("l1.1",),
            ("l1.2",),
        ]

    def test_missing_epic_count_raises(self, conn: sqlite3.Connection) -> None:
        _seed(conn, [_legend("l1", epic_count=None)])

        with pytest.raises(LegendPlanError, match="missing epic_count"):
            build_legend_work_plan(conn, "l1")

    def test_missing_design_path_raises(self, conn: sqlite3.Connection) -> None:
        _seed(conn, [_legend("l1", design="")])

        with pytest.raises(LegendPlanError, match="missing a design/plan file"):
            build_legend_work_plan(conn, "l1")

    def test_non_legend_plan_raises(self, conn: sqlite3.Connection) -> None:
        _seed(conn, [_epic("e1")])

        with pytest.raises(LegendPlanError, match="not a legend bead"):
            build_legend_work_plan(conn, "e1")

    def test_phase_target_raises(self, conn: sqlite3.Connection) -> None:
        _seed(conn, [_epic("e1"), _phase("p1")])

        with pytest.raises(LegendPlanError, match="not a plan/legend bead"):
            build_legend_work_plan(conn, "p1")

    def test_builds_from_beads_dir(self, tmp_path: Path) -> None:
        with BeadProject.init(tmp_path) as proj:
            legend = proj.create(
                "Legend l1",
                IssueType.PLAN,
                tier=BeadTier.LEGEND,
                epic_count=2,
                design="sdd/legends/202605/roadmap.md",
            )
            plan = build_legend_work_plan_from_beads_dir(proj.beads_dir, legend.id)

        assert plan.legend_id == legend.id
        assert [a.agent_name for a in plan.assignments] == [
            f"{legend.id}.1.0",
            f"{legend.id}.2.0",
        ]


class TestLegendRendering:
    def test_renders_snapshot_without_vcs(self, conn: sqlite3.Connection) -> None:
        _seed(conn, [_legend("l1", epic_count=2)])
        plan = build_legend_work_plan(conn, "l1")

        rendered = render_legend_multi_prompt(plan)

        expected = (
            "%name:l1.1.0\n"
            "%approve\n"
            "%epic\n"
            "Can you help me implement epic #1 from the legend plan in the "
            "sdd/legends/202605/roadmap.md file? #epic Keep in mind that "
            "this epic will be split into phases and worked by separate "
            "agents after approval.\n"
            "---\n"
            "%name:l1.2.0\n"
            "%approve\n"
            "%epic\n"
            "%w:l1.1\n"
            "Can you help me implement epic #2 from the legend plan in the "
            "sdd/legends/202605/roadmap.md file? #epic Keep in mind that "
            "this epic will be split into phases and worked by separate "
            "agents after approval."
        )
        assert rendered == expected

    def test_vcs_context_prefixes_every_legend_segment(
        self, conn: sqlite3.Connection
    ) -> None:
        _seed(conn, [_legend("l1", epic_count=2)])
        plan = build_legend_work_plan(conn, "l1")

        rendered = render_legend_multi_prompt(
            plan,
            vcs_context=VCSLaunchContext(vcs_workflow="git", project_name="sase"),
        )

        segments = rendered.split("\n---\n")
        assert len(segments) == 2
        assert all(segment.startswith("#git:sase\n") for segment in segments)
        assert "%name:l1.1.0" in rendered
        assert "%name:l1.2.0" in rendered
        assert "%epic" in rendered
        assert "%approve" in rendered
        assert "%w:l1.1" in rendered


class TestRenderEdgeCases:
    def test_vcs_context_prefixes_every_regular_epic_segment(
        self, conn: sqlite3.Connection
    ) -> None:
        _seed(conn, [_epic("e1"), _phase("p1"), _phase("p2")])
        plan = build_epic_work_plan(conn, "e1")

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
            vcs_context=VCSLaunchContext(vcs_workflow="git", project_name="sase"),
        )

        segments = rendered.split("\n---\n")
        assert len(segments) == 3
        assert all(segment.startswith("#git:sase\n") for segment in segments)
        assert "#bd/work_phase_bead:p1" in rendered
        assert "#bd/work_phase_bead:p2" in rendered
        assert "#bd/land_epic:e1" in rendered

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
        assert plan.land_agent_name == "sase-r"


class TestChangeSpecRendering:
    def test_single_phase_wraps_phase_and_land(self, conn: sqlite3.Connection) -> None:
        _seed(conn, [_epic("e1"), _phase("p1")])
        plan = build_epic_work_plan(conn, "e1")

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
            changespec_context=ChangeSpecLaunchContext(
                changespec_name="feature_epic",
                vcs_workflow="git",
                project_name="sase",
            ),
        )

        expected = (
            "#git:sase #pr:feature_epic\n"
            "%name:p1\n"
            "%approve\n"
            "#bd/work_phase_bead:p1\n"
            "---\n"
            "#git:feature_epic\n"
            "%name:e1\n"
            "%approve\n"
            "%w:p1\n"
            "#bd/land_epic:e1"
        )
        assert rendered == expected

    def test_dependency_chain_wraps_only_first_phase_with_pr(
        self, conn: sqlite3.Connection
    ) -> None:
        _seed(conn, [_epic("e1"), _phase("p1"), _phase("p2"), _phase("p3")])
        _depends(conn, "p2", "p1")
        _depends(conn, "p3", "p2")
        plan = build_epic_work_plan(conn, "e1")

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="custom/work"),
            land_epic_xprompt=Workflow(name="custom/land"),
            changespec_context=ChangeSpecLaunchContext(
                changespec_name="feature_epic",
                vcs_workflow="gh",
                project_name="sase",
            ),
        )

        expected = (
            "#gh:sase #pr:feature_epic\n"
            "%name:p1\n"
            "%approve\n"
            "#custom/work:p1\n"
            "---\n"
            "#gh:feature_epic\n"
            "%name:p2\n"
            "%approve\n"
            "%w:p1\n"
            "#custom/work:p2\n"
            "---\n"
            "#gh:feature_epic\n"
            "%name:p3\n"
            "%approve\n"
            "%w:p2\n"
            "#custom/work:p3\n"
            "---\n"
            "#gh:feature_epic\n"
            "%name:e1\n"
            "%approve\n"
            "%w:p3\n"
            "#custom/land:e1"
        )
        assert rendered == expected

    def test_independent_phases_only_first_gets_pr(
        self, conn: sqlite3.Connection
    ) -> None:
        _seed(conn, [_epic("e1"), _phase("p1"), _phase("p2")])
        plan = build_epic_work_plan(conn, "e1")

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
            changespec_context=ChangeSpecLaunchContext(
                changespec_name="feature_epic",
                vcs_workflow="git",
                project_name="sase",
            ),
        )

        assert rendered.count("#pr:feature_epic") == 1
        assert "#git:sase #pr:feature_epic\n%name:p1" in rendered
        assert "#git:feature_epic\n%name:p2" in rendered
        assert "#git:feature_epic\n%name:e1" in rendered

    def test_bug_id_uses_keyword_pr_syntax(self, conn: sqlite3.Connection) -> None:
        _seed(conn, [_epic("e1"), _phase("p1")])
        plan = build_epic_work_plan(conn, "e1")

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
            changespec_context=ChangeSpecLaunchContext(
                changespec_name="feature_epic",
                bug_id="12345",
                vcs_workflow="git",
                project_name="sase",
            ),
        )

        assert rendered.startswith("#git:sase #pr(name=feature_epic, bug_id=12345)")
        assert "#pr:" not in rendered
