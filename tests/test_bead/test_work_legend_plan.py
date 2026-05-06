"""Legend work-plan and rendering tests for ``sase bead work``."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from sase.bead.model import BeadTier, IssueType
from sase.bead.project import BeadProject
from sase.bead.work import (
    LegendEpicAssignment,
    LegendPlanError,
    LegendWorkPlan,
    VCSLaunchContext,
    build_legend_work_plan,
    build_legend_work_plan_from_beads_dir,
    render_legend_multi_prompt,
)
from sase.xprompt.workflow_models import Workflow

from .work_test_helpers import epic, legend, phase, seed


class TestLegendWorkPlan:
    def test_builds_linear_epic_assignments(self, conn: sqlite3.Connection) -> None:
        seed(conn, [legend("l1", epic_count=3)])

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
        assert plan.land_agent_name == "l1"
        assert plan.land_waits_on == ("l1.3",)

    def test_missing_epic_count_raises(self, conn: sqlite3.Connection) -> None:
        seed(conn, [legend("l1", epic_count=None)])

        with pytest.raises(LegendPlanError, match="missing epic_count"):
            build_legend_work_plan(conn, "l1")

    def test_missing_design_path_raises(self, conn: sqlite3.Connection) -> None:
        seed(conn, [legend("l1", design="")])

        with pytest.raises(LegendPlanError, match="missing a design/plan file"):
            build_legend_work_plan(conn, "l1")

    def test_non_legend_plan_raises(self, conn: sqlite3.Connection) -> None:
        seed(conn, [epic("e1")])

        with pytest.raises(LegendPlanError, match="not a legend bead"):
            build_legend_work_plan(conn, "e1")

    def test_phase_target_raises(self, conn: sqlite3.Connection) -> None:
        seed(conn, [epic("e1"), phase("p1")])

        with pytest.raises(LegendPlanError, match="not a plan/legend bead"):
            build_legend_work_plan(conn, "p1")

    def test_builds_from_beads_dir(self, tmp_path: Path) -> None:
        with BeadProject.init(tmp_path) as proj:
            legend_bead = proj.create(
                "Legend l1",
                IssueType.PLAN,
                tier=BeadTier.LEGEND,
                epic_count=2,
                design="sdd/legends/202605/roadmap.md",
            )
            plan = build_legend_work_plan_from_beads_dir(proj.beads_dir, legend_bead.id)

        assert plan.legend_id == legend_bead.id
        assert [a.agent_name for a in plan.assignments] == [
            f"{legend_bead.id}.1.0",
            f"{legend_bead.id}.2.0",
        ]
        assert plan.land_agent_name == legend_bead.id
        assert plan.land_waits_on == (f"{legend_bead.id}.2",)


class TestLegendRendering:
    def test_renders_snapshot_without_vcs(self, conn: sqlite3.Connection) -> None:
        seed(conn, [legend("l1", epic_count=2)])
        plan = build_legend_work_plan(conn, "l1")

        rendered = render_legend_multi_prompt(
            plan,
            land_legend_xprompt=Workflow(name="bd/land_legend"),
        )

        expected = (
            "%name:l1.1.0\n"
            "%epic\n"
            "Can you help me implement epic #1 from the legend plan in the "
            "sdd/legends/202605/roadmap.md file? #epic Keep in mind that "
            "this epic will be split into phases and worked by separate "
            "agents after approval.\n"
            "---\n"
            "%name:l1.2.0\n"
            "%epic\n"
            "%w:l1.1\n"
            "Can you help me implement epic #2 from the legend plan in the "
            "sdd/legends/202605/roadmap.md file? #epic Keep in mind that "
            "this epic will be split into phases and worked by separate "
            "agents after approval.\n"
            "---\n"
            "%name:l1\n"
            "%w:l1.2\n"
            "#bd/land_legend:l1"
        )
        assert rendered == expected
        segments = rendered.split("\n---\n")
        assert all("%epic" in segment for segment in segments[:-1])
        assert all("%approve" not in segment for segment in segments)

    def test_vcs_context_prefixes_every_legend_segment(
        self, conn: sqlite3.Connection
    ) -> None:
        seed(conn, [legend("l1", epic_count=2)])
        plan = build_legend_work_plan(conn, "l1")

        rendered = render_legend_multi_prompt(
            plan,
            land_legend_xprompt=Workflow(name="bd/land_legend"),
            vcs_context=VCSLaunchContext(vcs_workflow="git", project_name="sase"),
        )

        segments = rendered.split("\n---\n")
        assert len(segments) == 3
        assert all(segment.startswith("#git:sase\n") for segment in segments)
        assert "%name:l1.1.0" in rendered
        assert "%name:l1.2.0" in rendered
        assert "%name:l1" in rendered
        for segment in segments[:2]:
            assert "%epic" in segment
            assert "%approve" not in segment
        assert "%w:l1.1" in rendered
        assert "%w:l1.2" in rendered
        assert "#bd/land_legend:l1" in rendered
        assert "%epic" not in segments[-1]
        assert "%approve" not in segments[-1]

    def test_user_override_land_legend_xprompt_name_propagates(
        self, conn: sqlite3.Connection
    ) -> None:
        seed(conn, [legend("l1", epic_count=1)])
        plan = build_legend_work_plan(conn, "l1")

        rendered = render_legend_multi_prompt(
            plan,
            land_legend_xprompt=Workflow(name="custom/land_legend"),
        )

        assert "#custom/land_legend:l1" in rendered
