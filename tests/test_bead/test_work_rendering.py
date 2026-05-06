"""Prompt rendering tests for bead work plans."""

from __future__ import annotations

import sqlite3

from sase.bead.work import (
    ChangeSpecLaunchContext,
    EpicWorkPlan,
    PhaseAssignment,
    VCSLaunchContext,
    build_epic_work_plan,
    render_multi_prompt,
)
from sase.xprompt.directives import extract_prompt_directives
from sase.xprompt.workflow_models import Workflow

from .work_test_helpers import depends, epic, legend, phase, seed


class TestRenderEdgeCases:
    def test_vcs_context_prefixes_every_regular_epic_segment(
        self, conn: sqlite3.Connection
    ) -> None:
        seed(conn, [epic("e1"), phase("p1"), phase("p2")])
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
        seed(conn, [epic("e1"), phase("p1")])
        plan = build_epic_work_plan(conn, "e1")

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="custom/work_phase"),
            land_epic_xprompt=Workflow(name="custom/land"),
        )

        assert "#custom/work_phase:p1" in rendered
        assert "#custom/land:e1" in rendered

    def test_phase_agent_name_uses_bead_id(self, conn: sqlite3.Connection) -> None:
        seed(
            conn,
            [
                epic("sase-r"),
                phase("sase-r.1", parent_id="sase-r"),
            ],
        )
        plan = build_epic_work_plan(conn, "sase-r")
        assert plan.waves[0][0].agent_name == "sase-r.1"
        assert plan.land_agent_name == "sase-r"

    def test_legend_child_epic_uses_legend_tag_only(
        self, conn: sqlite3.Connection
    ) -> None:
        seed(
            conn,
            [
                legend("l1"),
                epic("e1", parent_id="l1"),
                phase("p1", parent_id="e1"),
            ],
        )
        plan = build_epic_work_plan(conn, "e1")

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )

        assert plan.launch_tag_id == "l1"
        assert rendered.count("%tag:l1") == 2
        assert "%tag:e1" not in rendered
        assert "#bd/work_phase_bead:p1" in rendered
        assert "#bd/land_epic:e1" in rendered

    def test_dotted_launch_tag_directives_extract_cleanly(self) -> None:
        plan = EpicWorkPlan(
            epic_id="sase-24.3",
            launch_tag_id="sase-24.3",
            waves=(
                (
                    PhaseAssignment(
                        bead_id="sase-24.3.1",
                        agent_name="sase-24.3.1",
                        waits_on=(),
                        wave=0,
                    ),
                ),
            ),
            land_agent_name="sase-24.3",
            land_waits_on=("sase-24.3.1",),
        )

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )

        phase_segment, land_segment = rendered.split("\n---\n")
        for segment in (phase_segment, land_segment):
            _, directives = extract_prompt_directives(segment)
            assert directives.tag == "sase-24.3"

        assert "%name:sase-24.3.1" in phase_segment
        assert "#bd/work_phase_bead:sase-24.3.1" in phase_segment
        assert "%name:sase-24.3" in land_segment
        assert "%w:sase-24.3.1" in land_segment
        assert "#bd/land_epic:sase-24.3" in land_segment


class TestChangeSpecRendering:
    def test_single_phase_wraps_phase_and_land(self, conn: sqlite3.Connection) -> None:
        seed(conn, [epic("e1"), phase("p1")])
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
            "%tag:e1\n"
            "%approve\n"
            "#bd/work_phase_bead:p1\n"
            "---\n"
            "#git:feature_epic\n"
            "%name:e1\n"
            "%tag:e1\n"
            "%approve\n"
            "%w:p1\n"
            "#bd/land_epic:e1"
        )
        assert rendered == expected
        phase_segment, land_segment = rendered.split("\n---\n")
        assert "%approve" in phase_segment
        assert "%approve" in land_segment

    def test_dependency_chain_wraps_only_first_phase_with_pr(
        self, conn: sqlite3.Connection
    ) -> None:
        seed(conn, [epic("e1"), phase("p1"), phase("p2"), phase("p3")])
        depends(conn, "p2", "p1")
        depends(conn, "p3", "p2")
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
            "%tag:e1\n"
            "%approve\n"
            "#custom/work:p1\n"
            "---\n"
            "#gh:feature_epic\n"
            "%name:p2\n"
            "%tag:e1\n"
            "%approve\n"
            "%w:p1\n"
            "#custom/work:p2\n"
            "---\n"
            "#gh:feature_epic\n"
            "%name:p3\n"
            "%tag:e1\n"
            "%approve\n"
            "%w:p2\n"
            "#custom/work:p3\n"
            "---\n"
            "#gh:feature_epic\n"
            "%name:e1\n"
            "%tag:e1\n"
            "%approve\n"
            "%w:p1,p2,p3\n"
            "#custom/land:e1"
        )
        assert rendered == expected
        segments = rendered.split("\n---\n")
        assert all("%approve" in segment for segment in segments)

    def test_independent_phases_only_first_gets_pr(
        self, conn: sqlite3.Connection
    ) -> None:
        seed(conn, [epic("e1"), phase("p1"), phase("p2")])
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
        assert "#git:sase #pr:feature_epic\n%name:p1\n%tag:e1" in rendered
        assert "#git:feature_epic\n%name:p2\n%tag:e1" in rendered
        assert "#git:feature_epic\n%name:e1\n%tag:e1" in rendered

    def test_bug_id_uses_keyword_pr_syntax(self, conn: sqlite3.Connection) -> None:
        seed(conn, [epic("e1"), phase("p1")])
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
