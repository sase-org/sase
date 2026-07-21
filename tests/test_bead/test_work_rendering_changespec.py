"""ChangeSpec prompt rendering tests for bead work plans."""

from __future__ import annotations

import sqlite3

from sase.bead.work import (
    ChangeSpecLaunchContext,
    _build_epic_work_plan,
    render_multi_prompt,
)
from sase.xprompt.workflow_models import Workflow

from .work_test_helpers import (
    assert_bare_auto_directives,
    depends,
    epic,
    phase,
    seed,
)


class TestChangeSpecRendering:
    def test_single_phase_wraps_phase_and_land(self, conn: sqlite3.Connection) -> None:
        seed(conn, [epic("e1"), phase("p1")])
        plan = _build_epic_work_plan(conn, "e1")

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
            "%id(!e1.p1, bead=p1)\n"
            "%clan(e1, tribe=epic, summary_script=sase_clan_summary_epic)\n"
            "%model:@small_phase_worker\n"
            "%auto\n"
            "#bd/work_phase_bead:p1\n"
            "---\n"
            "#git:feature_epic\n"
            "%id(!land, clan=e1, bead=e1)\n"
            "%model:@epic_lander\n"
            "%auto\n"
            "%w:e1.p1\n"
            "%w(bead=p1)\n"
            "#bd/land_epic:e1"
        )
        assert rendered == expected
        assert_bare_auto_directives(rendered)

    def test_dependency_chain_wraps_only_first_phase_with_pr(
        self, conn: sqlite3.Connection
    ) -> None:
        seed(conn, [epic("e1"), phase("p1"), phase("p2"), phase("p3")])
        depends(conn, "p2", "p1")
        depends(conn, "p3", "p2")
        plan = _build_epic_work_plan(conn, "e1")

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
            "%id(!e1.p1, bead=p1)\n"
            "%clan(e1, tribe=epic, summary_script=sase_clan_summary_epic)\n"
            "%model:@small_phase_worker\n"
            "%auto\n"
            "#custom/work:p1\n"
            "---\n"
            "#gh:feature_epic\n"
            "%id(!p2, clan=e1, bead=p2)\n"
            "%model:@small_phase_worker\n"
            "%auto\n"
            "%w:e1.p1\n"
            "%w(bead=p1)\n"
            "#custom/work:p2\n"
            "---\n"
            "#gh:feature_epic\n"
            "%id(!p3, clan=e1, bead=p3)\n"
            "%model:@small_phase_worker\n"
            "%auto\n"
            "%w:e1.p2\n"
            "%w(bead=p2)\n"
            "#custom/work:p3\n"
            "---\n"
            "#gh:feature_epic\n"
            "%id(!land, clan=e1, bead=e1)\n"
            "%model:@epic_lander\n"
            "%auto\n"
            "%w:e1.p1,e1.p2,e1.p3\n"
            "%w(bead=p1)\n"
            "%w(bead=p2)\n"
            "%w(bead=p3)\n"
            "#custom/land:e1"
        )
        assert rendered == expected
        assert_bare_auto_directives(rendered)

    def test_independent_phases_only_first_gets_pr(
        self, conn: sqlite3.Connection
    ) -> None:
        seed(conn, [epic("e1"), phase("p1"), phase("p2")])
        plan = _build_epic_work_plan(conn, "e1")

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
        membership = "%clan(e1, tribe=epic, summary_script=sase_clan_summary_epic)"
        assert (
            f"#git:sase #pr:feature_epic\n%id(!e1.p1, bead=p1)\n{membership}"
            in rendered
        )
        assert "#git:feature_epic\n%id(!p2, clan=e1, bead=p2)" in rendered
        assert "#git:feature_epic\n%id(!land, clan=e1, bead=e1)" in rendered
        assert rendered.count(membership) == 1
        assert "%family" not in rendered
        assert "%group:" not in rendered

    def test_bug_id_uses_keyword_pr_syntax(self, conn: sqlite3.Connection) -> None:
        seed(conn, [epic("e1"), phase("p1")])
        plan = _build_epic_work_plan(conn, "e1")

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
