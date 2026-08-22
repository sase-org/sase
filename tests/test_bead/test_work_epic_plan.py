"""Epic work-plan tests for ``sase bead work``."""

from __future__ import annotations

import sqlite3

import pytest

from sase.agent.launch_validation import INTERNAL_AGENT_NAME_BYPASS_ENV
from sase.bead.model import PhaseSize, Status
from sase.bead.work import (
    _CrossEpicBlockerError,
    _CycleError,
    EPIC_CLAN_SUMMARY_SCRIPT,
    EpicPlanError,
    SASE_BEAD_ID_ENV,
    SASE_EPIC_BEAD_ID_ENV,
    SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV,
    SASE_EPIC_CLAN_TRIBE_ENV,
    SASE_EPIC_PLAN_REF_ENV,
    SASE_PHASE_BEAD_ID_ENV,
    _build_epic_work_plan,
    epic_work_segment_env,
    _plan_from_payload,
    render_multi_prompt,
)
from sase.xprompt.directives import extract_prompt_directives
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

        plan = _build_epic_work_plan(conn, "e1")

        assert len(plan.waves) == 3
        assert wave_bead_ids(plan, 0) == ["p1"]
        assert wave_bead_ids(plan, 1) == ["p2"]
        assert wave_bead_ids(plan, 2) == ["p3"]
        # P1 has no waits; P2 waits on P1; P3 waits on P2.
        assert plan.waves[0][0].waits_on == ()
        assert plan.waves[1][0].waits_on == ("e1.p1",)
        assert plan.waves[2][0].waits_on == ("e1.p2",)
        assert plan.waves[0][0].blocker_bead_ids == ()
        assert plan.waves[1][0].blocker_bead_ids == ("p1",)
        assert plan.waves[2][0].blocker_bead_ids == ("p2",)
        assert plan.phase_bead_ids == ("p1", "p2", "p3")
        assert plan.land_waits_on == ("e1.p1", "e1.p2", "e1.p3")
        assert plan.land_agent_name == "e1.land"
        assert plan.launch_tag_id == "e1"

    def test_parent_plan_does_not_change_epic_launch_tag(
        self, conn: sqlite3.Connection
    ) -> None:
        parent = epic("p0")
        seed(
            conn,
            [
                parent,
                epic("e1", parent_id="p0"),
                phase("p1", parent_id="e1"),
            ],
        )

        plan = _build_epic_work_plan(conn, "e1")

        assert plan.launch_tag_id == "e1"


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
        plan = _build_epic_work_plan(conn, "e1")

        assert len(plan.waves) == 3
        assert wave_bead_ids(plan, 0) == ["p1"]
        assert wave_bead_ids(plan, 1) == ["p2", "p3"]
        assert wave_bead_ids(plan, 2) == ["p4"]
        assert plan.waves[1][0].waits_on == ("e1.p1",)
        assert plan.waves[1][1].waits_on == ("e1.p1",)
        assert plan.waves[2][0].waits_on == ("e1.p2", "e1.p3")
        assert plan.waves[2][0].blocker_bead_ids == ("p2", "p3")
        assert plan.phase_bead_ids == ("p1", "p2", "p3", "p4")
        assert plan.land_waits_on == ("e1.p1", "e1.p2", "e1.p3", "e1.p4")

    def test_diamond_render_snapshot(self, conn: sqlite3.Connection) -> None:
        self._seed_diamond(conn)
        plan = _build_epic_work_plan(conn, "e1")

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )

        expected = (
            "%id(!e1.p1, bead=p1)\n"
            "%clan(e1, tribe=epic, summary_script=sase_clan_summary_epic)\n"
            "%model:@small\n"
            "%auto\n"
            "#bd/work_phase_bead:p1\n"
            "---\n"
            "%id(!p2, clan=e1, bead=p2)\n"
            "%model:@small\n"
            "%auto\n"
            "%w:e1.p1\n"
            "%w(bead=p1)\n"
            "#bd/work_phase_bead:p2\n"
            "---\n"
            "%id(!p3, clan=e1, bead=p3)\n"
            "%model:@small\n"
            "%auto\n"
            "%w:e1.p1\n"
            "%w(bead=p1)\n"
            "#bd/work_phase_bead:p3\n"
            "---\n"
            "%id(!p4, clan=e1, bead=p4)\n"
            "%model:@small\n"
            "%auto\n"
            "%w:e1.p2,e1.p3\n"
            "%w(bead=p2)\n"
            "%w(bead=p3)\n"
            "#bd/work_phase_bead:p4\n"
            "---\n"
            "%id(!land, clan=e1, bead=e1)\n"
            "%model:@large\n"
            "%auto\n"
            "%w:e1.p1,e1.p2,e1.p3,e1.p4\n"
            "%w(bead=p1)\n"
            "%w(bead=p2)\n"
            "%w(bead=p3)\n"
            "%w(bead=p4)\n"
            "#bd/land_epic:e1"
        )
        assert rendered == expected
        segments = rendered.split("\n---\n")
        assert (
            "%clan(e1, tribe=epic, summary_script=sase_clan_summary_epic)"
            in segments[0]
        )
        assert all("%clan" not in segment for segment in segments[1:])
        assert all("%family" not in segment for segment in segments)
        assert all("%group:" not in segment for segment in segments)
        assert all("%auto" in segment.splitlines() for segment in segments)
        assert all("%auto:tale" not in segment for segment in segments)
        for segment in segments:
            _, directives = extract_prompt_directives(segment)
            assert directives.auto_enabled is True
            assert directives.auto_argument is None


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

        plan = _build_epic_work_plan(conn, "e1")

        assert [wave_bead_ids(plan, i) for i in range(len(plan.waves))] == [
            ["p1", "p4"],
            ["p2"],
            ["p3"],
        ]
        assert plan.waves[1][0].waits_on == ("e1.p1",)
        assert plan.waves[2][0].waits_on == ("e1.p2",)
        assert plan.land_waits_on == ("e1.p1", "e1.p4", "e1.p2", "e1.p3")


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
        plan = _build_epic_work_plan(conn, "e1")

        assert len(plan.waves) == 1
        assert wave_bead_ids(plan, 0) == ["p1", "p2", "p3"]
        assert all(a.waits_on == () for a in plan.waves[0])
        assert all(a.blocker_bead_ids == () for a in plan.waves[0])
        assert plan.phase_bead_ids == ("p1", "p2", "p3")
        assert plan.land_waits_on == ("e1.p1", "e1.p2", "e1.p3")


class TestClosedBlockers:
    def test_in_progress_phase_is_included(self, conn: sqlite3.Connection) -> None:
        seed(
            conn,
            [
                epic("e1"),
                phase("p1", status=Status.IN_PROGRESS),
            ],
        )

        plan = _build_epic_work_plan(conn, "e1")

        assert len(plan.waves) == 1
        assert wave_bead_ids(plan, 0) == ["p1"]
        assert plan.land_waits_on == ("e1.p1",)

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

        plan = _build_epic_work_plan(conn, "e1")

        assert len(plan.waves) == 1
        assert wave_bead_ids(plan, 0) == ["p2"]
        assert plan.total_phase_count == 2
        assert plan.phase_bead_ids == ("p1", "p2")
        assert plan.waves[0][0].waits_on == ()
        assert plan.waves[0][0].blocker_bead_ids == ("p1",)
        assert plan.land_waits_on == ("e1.p2",)

    def test_closed_blocker_is_rendered_as_a_bead_only_wait(
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

        plan = _build_epic_work_plan(conn, "e1")
        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )

        assert "#bd/work_phase_bead:p1" not in rendered
        assert "%w:e1.p1" not in rendered
        phase_segment, land_segment = rendered.split("\n---\n")
        assert "%w(bead=p1)" in phase_segment
        assert "%w(bead=p1)" in land_segment
        assert "%w(bead=p2)" in land_segment
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

        plan = _build_epic_work_plan(conn, "e1")
        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )

        assert "#bd/work_phase_bead:p1" not in rendered
        assert "#bd/work_phase_bead:p2" in rendered
        assert "#bd/work_phase_bead:p3" in rendered
        assert "%w:e1.p2" in rendered
        assert "#bd/land_epic:e1" in rendered

    def test_all_closed_phases_return_and_render_land_only_plan(
        self, conn: sqlite3.Connection
    ) -> None:
        seed(
            conn,
            [
                epic("e1"),
                phase("p1", status=Status.CLOSED),
                phase("p2", status=Status.CLOSED),
            ],
        )

        plan = _build_epic_work_plan(conn, "e1")

        assert plan.total_phase_count == 2
        assert plan.phase_bead_ids == ("p1", "p2")
        assert plan.waves == ()
        assert plan.land_waits_on == ()
        assert plan.land_agent_name == "e1.land"

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )
        assert rendered.count("\n---\n") == 0
        assert "%id(!e1.land, bead=e1)" in rendered
        assert (
            "%clan(e1, tribe=epic, summary_script=sase_clan_summary_epic)" in rendered
        )
        assert "%model:@large" in rendered
        assert "#bd/work_phase_bead" not in rendered
        assert "%w:" not in rendered
        assert "%w(bead=p1)" in rendered
        assert "%w(bead=p2)" in rendered
        assert rendered.splitlines()[-1] == "#bd/land_epic:e1"

        joined = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
            declare_clan=False,
        )
        assert "%clan" not in joined
        assert "%id(!land, clan=e1, bead=e1)" in joined

        envs = epic_work_segment_env(plan, plan_ref="sdd/plans/e1.md")
        assert envs == (
            {
                SASE_BEAD_ID_ENV: "e1",
                SASE_EPIC_BEAD_ID_ENV: "e1",
                SASE_EPIC_CLAN_TRIBE_ENV: "epic",
                SASE_EPIC_PLAN_REF_ENV: "sdd/plans/e1.md",
                SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV: EPIC_CLAN_SUMMARY_SCRIPT,
                INTERNAL_AGENT_NAME_BYPASS_ENV: "1",
            },
        )
        assert SASE_PHASE_BEAD_ID_ENV not in envs[0]

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

        plan = _build_epic_work_plan(conn, "e1")

        assert len(plan.waves) == 1
        assert wave_bead_ids(plan, 0) == ["p1"]
        assert plan.waves[0][0].waits_on == ()
        assert plan.waves[0][0].blocker_bead_ids == ()


class TestDelegatedPhases:
    def test_retry_keeps_delegated_phase_as_bead_only_blocker(
        self, conn: sqlite3.Connection
    ) -> None:
        seed(
            conn,
            [
                epic("e1"),
                phase("p1", status=Status.IN_PROGRESS),
                epic("child", parent_id="p1"),
                phase("p2"),
            ],
        )
        depends(conn, "p2", "p1")

        plan = _build_epic_work_plan(conn, "e1")

        assert wave_bead_ids(plan, 0) == ["p2"]
        assert plan.waves[0][0].waits_on == ()
        assert plan.waves[0][0].blocker_bead_ids == ("p1",)
        assert plan.phase_bead_ids == ("p1", "p2")
        assert plan.land_waits_on == ("e1.p2",)

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )
        phase_segment, land_segment = rendered.split("\n---\n")
        assert "#bd/work_phase_bead:p1" not in rendered
        assert "%w:e1.p1" not in rendered
        assert "%w(bead=p1)" in phase_segment
        assert "%w:e1.p2" in land_segment
        assert land_segment.splitlines()[-3:-1] == [
            "%w(bead=p1)",
            "%w(bead=p2)",
        ]

    def test_land_waits_on_closed_delegated_and_launched_phase_beads(
        self, conn: sqlite3.Connection
    ) -> None:
        seed(
            conn,
            [
                epic("e1"),
                phase("p1", status=Status.CLOSED),
                phase("p2", status=Status.IN_PROGRESS),
                epic("child", parent_id="p2"),
                phase("p3"),
            ],
        )
        depends(conn, "p3", "p1")
        depends(conn, "p3", "p2")

        plan = _build_epic_work_plan(conn, "e1")
        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )

        assert plan.phase_bead_ids == ("p1", "p2", "p3")
        assert plan.waves[0][0].blocker_bead_ids == ("p1", "p2")
        assert plan.land_waits_on == ("e1.p3",)
        land_segment = rendered.split("\n---\n")[-1]
        assert "%w:e1.p3" in land_segment
        assert [
            line for line in land_segment.splitlines() if line.startswith("%w(bead=")
        ] == ["%w(bead=p1)", "%w(bead=p2)", "%w(bead=p3)"]


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

        with pytest.raises(_CrossEpicBlockerError):
            _build_epic_work_plan(conn, "e1")


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

        with pytest.raises(_CycleError):
            _build_epic_work_plan(conn, "e1")


class TestModelAndSizePropagationFromPayload:
    def test_phase_model_flows_into_assignment(self, conn: sqlite3.Connection) -> None:
        seed(
            conn,
            [
                epic("e1"),
                phase("p1", model="claude/opus"),
                phase("p2"),
            ],
        )
        plan = _build_epic_work_plan(conn, "e1")

        assignments = {a.bead_id: a for wave in plan.waves for a in wave}
        assert assignments["p1"].model == "claude/opus"
        assert assignments["p2"].model == ""
        assert plan.land_model == ""

    def test_phase_size_flows_into_assignment(self, conn: sqlite3.Connection) -> None:
        seed(
            conn,
            [
                epic("e1"),
                phase("p1", size=PhaseSize.MEDIUM),
                phase("p2", size=PhaseSize.LARGE),
                phase("p3"),
            ],
        )
        plan = _build_epic_work_plan(conn, "e1")

        assignments = {a.bead_id: a for wave in plan.waves for a in wave}
        assert assignments["p1"].size is PhaseSize.MEDIUM
        assert assignments["p2"].size is PhaseSize.LARGE
        assert assignments["p3"].size is None

    def test_epic_model_flows_into_land_model(self, conn: sqlite3.Connection) -> None:
        seed(
            conn,
            [
                epic("e1", model="codex/gpt-5.6-sol"),
                phase("p1"),
            ],
        )
        plan = _build_epic_work_plan(conn, "e1")

        assert plan.land_model == "codex/gpt-5.6-sol"
        assignments = [a for wave in plan.waves for a in wave]
        assert all(a.model == "" for a in assignments)


class TestPayloadHydration:
    def test_total_phase_count_falls_back_to_launched_assignments(self) -> None:
        plan = _plan_from_payload(
            {
                "epic_id": "e1",
                "launch_tag_id": "e1",
                "waves": [
                    [
                        {
                            "bead_id": "p1",
                            "agent_name": "p1",
                            "waits_on": [],
                            "blocker_bead_ids": [],
                            "wave": 0,
                        },
                        {
                            "bead_id": "p2",
                            "agent_name": "p2",
                            "waits_on": [],
                            "blocker_bead_ids": [],
                            "wave": 0,
                        },
                    ],
                    [
                        {
                            "bead_id": "p3",
                            "agent_name": "p3",
                            "waits_on": ["p1"],
                            "blocker_bead_ids": ["p1"],
                            "wave": 1,
                        }
                    ],
                ],
                "phase_bead_ids": ["p1", "p2", "p3"],
                "land_agent_name": "e1.land",
                "land_waits_on": ["p1", "p2", "p3"],
            }
        )

        assert plan.total_phase_count == 3
        assert plan.phase_bead_ids == ("p1", "p2", "p3")
        assert plan.waves[1][0].waits_on == ("e1.p1",)
        assert plan.waves[1][0].blocker_bead_ids == ("p1",)


class TestEpicValidation:
    def test_missing_epic_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(EpicPlanError):
            _build_epic_work_plan(conn, "missing")

    def test_phase_target_raises(self, conn: sqlite3.Connection) -> None:
        seed(conn, [epic("e1"), phase("p1")])
        with pytest.raises(EpicPlanError):
            _build_epic_work_plan(conn, "p1")

    def test_no_phase_children_raises(self, conn: sqlite3.Connection) -> None:
        seed(conn, [epic("e1")])
        with pytest.raises(EpicPlanError, match="no authored phase children"):
            _build_epic_work_plan(conn, "e1")
