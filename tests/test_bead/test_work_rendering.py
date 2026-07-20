"""Prompt rendering edge-case tests for bead work plans."""

from __future__ import annotations

import sqlite3

from sase.bead.work import (
    ChangeSpecLaunchContext,
    EpicWorkPlan,
    _PhaseAssignment as PhaseAssignment,
    SASE_BEAD_ID_ENV,
    SASE_EPIC_BEAD_ID_ENV,
    SASE_EPIC_CLAN_TRIBE_ENV,
    SASE_EPIC_PLAN_REF_ENV,
    SASE_PHASE_BEAD_ID_ENV,
    VCSLaunchContext,
    _build_epic_work_plan,
    epic_work_segment_env,
    render_multi_prompt,
)
from sase.agent.launch_validation import INTERNAL_AGENT_NAME_BYPASS_ENV
from sase.xprompt.directives import extract_prompt_directives
from sase.xprompt.workflow_models import Workflow

from .work_test_helpers import depends, epic, phase, seed


def _bead_wait_lines(rendered: str) -> list[str]:
    return [line for line in rendered.splitlines() if line.startswith("%w(bead=")]


class TestRenderEdgeCases:
    def test_vcs_context_prefixes_every_regular_epic_segment(
        self, conn: sqlite3.Connection
    ) -> None:
        seed(conn, [epic("e1"), phase("p1"), phase("p2")])
        plan = _build_epic_work_plan(conn, "e1")

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

    def test_vcs_and_changespec_wrappers_preserve_identical_bead_waits(
        self, conn: sqlite3.Connection
    ) -> None:
        seed(conn, [epic("e1"), phase("p1"), phase("p2")])
        depends(conn, "p2", "p1")
        plan = _build_epic_work_plan(conn, "e1")

        vcs_rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
            vcs_context=VCSLaunchContext(vcs_workflow="git", project_name="sase"),
        )
        changespec_rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
            changespec_context=ChangeSpecLaunchContext(
                changespec_name="feature_epic",
                vcs_workflow="git",
                project_name="sase",
            ),
        )

        expected = ["%w(bead=p1)", "%w(bead=p1)", "%w(bead=p2)"]
        assert _bead_wait_lines(vcs_rendered) == expected
        assert _bead_wait_lines(changespec_rendered) == expected

    def test_user_override_xprompt_names_propagate(
        self, conn: sqlite3.Connection
    ) -> None:
        seed(conn, [epic("e1"), phase("p1")])
        plan = _build_epic_work_plan(conn, "e1")

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
        plan = _build_epic_work_plan(conn, "sase-r")
        assert plan.waves[0][0].agent_name == "sase-r.1"
        assert plan.land_agent_name == "sase-r.land"

    def test_nested_epic_declares_once_and_joins_land_segment(self) -> None:
        plan = EpicWorkPlan(
            epic_id="sase-42.3",
            launch_tag_id="sase-42.3",
            total_phase_count=1,
            phase_bead_ids=("sase-42.3.1",),
            waves=(
                (
                    PhaseAssignment(
                        bead_id="sase-42.3.1",
                        agent_name="sase-42.3.1",
                        waits_on=(),
                        blocker_bead_ids=(),
                        wave=0,
                    ),
                ),
            ),
            land_agent_name="sase-42.3.land",
            land_waits_on=("sase-42.3.1",),
        )

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )

        phase_segment, land_segment = rendered.split("\n---\n")
        _, phase_directives = extract_prompt_directives(phase_segment)
        _, land_directives = extract_prompt_directives(land_segment)
        assert phase_directives.clan == "sase-42.3"
        assert land_directives.clan == "sase-42.3"
        assert phase_directives.tribe is None
        assert land_directives.tribe is None
        assert phase_directives.clan_tribe == "epic"
        assert land_directives.clan_tribe is None

        assert "%family" not in rendered
        assert (
            "%clan(sase-42.3, tribe=epic, "
            "summary_script=sase_clan_summary_epic)" in phase_segment
        )
        assert "%id:!sase-42.3.1" in phase_segment
        assert "#bd/work_phase_bead:sase-42.3.1" in phase_segment
        assert "%id(!land, clan=sase-42.3)" in land_segment
        assert "%clan" not in land_segment
        assert "%w:sase-42.3.1" in land_segment
        assert "#bd/land_epic:sase-42.3" in land_segment

    def test_existing_epic_clan_uses_join_form_for_every_segment(self) -> None:
        plan = EpicWorkPlan(
            epic_id="sase-42",
            launch_tag_id="sase-42",
            total_phase_count=1,
            phase_bead_ids=("sase-42.1",),
            waves=(
                (
                    PhaseAssignment(
                        bead_id="sase-42.1",
                        agent_name="sase-42.1",
                        waits_on=(),
                        blocker_bead_ids=(),
                        wave=0,
                    ),
                ),
            ),
            land_agent_name="sase-42.land",
            land_waits_on=("sase-42.1",),
        )

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
            declare_clan=False,
        )

        phase_segment, land_segment = rendered.split("\n---\n")
        assert "%clan" not in rendered
        assert "%id(!1, clan=sase-42)" in phase_segment
        assert "%id(!land, clan=sase-42)" in land_segment

    def test_epic_work_segment_env_tracks_phase_then_land_bead_ids(
        self,
        conn: sqlite3.Connection,
    ) -> None:
        seed(conn, [epic("e1"), phase("p1"), phase("p2")])
        plan = _build_epic_work_plan(conn, "e1")

        plan_ref = "sdd/plans/202607/epic.md"
        assert epic_work_segment_env(plan, plan_ref=plan_ref) == (
            {
                SASE_BEAD_ID_ENV: "p1",
                SASE_EPIC_BEAD_ID_ENV: "e1",
                SASE_EPIC_CLAN_TRIBE_ENV: "epic",
                SASE_EPIC_PLAN_REF_ENV: plan_ref,
                SASE_PHASE_BEAD_ID_ENV: "p1",
                INTERNAL_AGENT_NAME_BYPASS_ENV: "1",
            },
            {
                SASE_BEAD_ID_ENV: "p2",
                SASE_EPIC_BEAD_ID_ENV: "e1",
                SASE_EPIC_CLAN_TRIBE_ENV: "epic",
                SASE_EPIC_PLAN_REF_ENV: plan_ref,
                SASE_PHASE_BEAD_ID_ENV: "p2",
                INTERNAL_AGENT_NAME_BYPASS_ENV: "1",
            },
            {
                SASE_BEAD_ID_ENV: "e1",
                SASE_EPIC_BEAD_ID_ENV: "e1",
                SASE_EPIC_CLAN_TRIBE_ENV: "epic",
                SASE_EPIC_PLAN_REF_ENV: plan_ref,
                INTERNAL_AGENT_NAME_BYPASS_ENV: "1",
            },
        )

    def test_nested_epic_segment_env_uses_child_scoped_ids(self) -> None:
        plan = EpicWorkPlan(
            epic_id="sase-7z.5.1",
            launch_tag_id="sase-7z.5.1",
            total_phase_count=1,
            phase_bead_ids=("sase-7z.5.1.1",),
            waves=(
                (
                    PhaseAssignment(
                        bead_id="sase-7z.5.1.1",
                        agent_name="sase-7z.5.1.1",
                        waits_on=(),
                        blocker_bead_ids=(),
                        wave=0,
                    ),
                ),
            ),
            land_agent_name="sase-7z.5.1.land",
            land_waits_on=("sase-7z.5.1.1",),
        )

        phase_env, land_env = epic_work_segment_env(
            plan,
            plan_ref="sdd/plans/202607/nested.md",
        )

        assert phase_env[SASE_PHASE_BEAD_ID_ENV] == "sase-7z.5.1.1"
        assert phase_env[SASE_EPIC_BEAD_ID_ENV] == "sase-7z.5.1"
        assert land_env[SASE_EPIC_BEAD_ID_ENV] == "sase-7z.5.1"
        assert SASE_PHASE_BEAD_ID_ENV not in land_env
