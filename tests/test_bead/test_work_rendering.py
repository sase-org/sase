"""Prompt rendering tests for bead work plans."""

from __future__ import annotations

import sqlite3

import pytest

from sase.bead.model import PhaseSize, Status
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
from sase.llm_provider.registry import resolve_model_provider
from sase.xprompt.directives import extract_prompt_directives
from sase.xprompt.workflow_models import Workflow

from .work_test_helpers import depends, epic, phase, seed


def _assert_bare_auto_directives(rendered: str) -> None:
    segments = rendered.split("\n---\n")
    for segment in segments:
        assert "%auto" in segment.splitlines()
        assert "%auto:tale" not in segment
        _, directives = extract_prompt_directives(segment)
        assert directives.auto_enabled is True
        assert directives.auto_argument is None


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
            waves=(
                (
                    PhaseAssignment(
                        bead_id="sase-42.3.1",
                        agent_name="sase-42.3.1",
                        waits_on=(),
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
            waves=(
                (
                    PhaseAssignment(
                        bead_id="sase-42.1",
                        agent_name="sase-42.1",
                        waits_on=(),
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
            waves=(
                (
                    PhaseAssignment(
                        bead_id="sase-7z.5.1.1",
                        agent_name="sase-7z.5.1.1",
                        waits_on=(),
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
            "%id:!e1.p1\n"
            "%clan(e1, tribe=epic, summary_script=sase_clan_summary_epic)\n"
            "%model:@phase_worker\n"
            "%auto\n"
            "#bd/work_phase_bead:p1\n"
            "---\n"
            "#git:feature_epic\n"
            "%id(!land, clan=e1)\n"
            "%model:@epic_lander\n"
            "%auto\n"
            "%w:e1.p1\n"
            "#bd/land_epic:e1"
        )
        assert rendered == expected
        _assert_bare_auto_directives(rendered)

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
            "%id:!e1.p1\n"
            "%clan(e1, tribe=epic, summary_script=sase_clan_summary_epic)\n"
            "%model:@phase_worker\n"
            "%auto\n"
            "#custom/work:p1\n"
            "---\n"
            "#gh:feature_epic\n"
            "%id(!p2, clan=e1)\n"
            "%model:@phase_worker\n"
            "%auto\n"
            "%w:e1.p1\n"
            "#custom/work:p2\n"
            "---\n"
            "#gh:feature_epic\n"
            "%id(!p3, clan=e1)\n"
            "%model:@phase_worker\n"
            "%auto\n"
            "%w:e1.p2\n"
            "#custom/work:p3\n"
            "---\n"
            "#gh:feature_epic\n"
            "%id(!land, clan=e1)\n"
            "%model:@epic_lander\n"
            "%auto\n"
            "%w:e1.p1,e1.p2,e1.p3\n"
            "#custom/land:e1"
        )
        assert rendered == expected
        _assert_bare_auto_directives(rendered)

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
        assert f"#git:sase #pr:feature_epic\n%id:!e1.p1\n{membership}" in rendered
        assert "#git:feature_epic\n%id(!p2, clan=e1)" in rendered
        assert "#git:feature_epic\n%id(!land, clan=e1)" in rendered
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


class TestModelDirective:
    @pytest.mark.parametrize(
        ("size", "expected_model", "expects_plan"),
        [
            (None, "@phase_worker", False),
            (PhaseSize.SMALL, "@phase_worker", False),
            (PhaseSize.MEDIUM, "@phase_worker", True),
            (PhaseSize.LARGE, "@smartest", True),
        ],
    )
    def test_phase_size_controls_model_and_plan_first_prompt(
        self,
        conn: sqlite3.Connection,
        size: PhaseSize | None,
        expected_model: str,
        expects_plan: bool,
    ) -> None:
        seed(conn, [epic("e1"), phase("p1", size=size)])
        plan = _build_epic_work_plan(conn, "e1")

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )

        phase_segment = rendered.split("\n---\n")[0]
        assert f"%model:{expected_model}" in phase_segment
        assert ("#plan" in phase_segment.splitlines()) is expects_plan
        if expects_plan:
            assert phase_segment.endswith("#bd/work_phase_bead:p1\n#plan")

    def test_explicit_model_wins_over_large_phase_smartest_alias(
        self, conn: sqlite3.Connection
    ) -> None:
        seed(
            conn,
            [
                epic("e1"),
                phase(
                    "p1",
                    model="codex/gpt-5.6-sol",
                    size=PhaseSize.LARGE,
                ),
            ],
        )
        plan = _build_epic_work_plan(conn, "e1")

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )

        phase_segment = rendered.split("\n---\n")[0]
        assert "%model:codex/gpt-5.6-sol" in phase_segment
        assert "@smartest" not in phase_segment
        assert phase_segment.endswith("#bd/work_phase_bead:p1\n#plan")

    @pytest.mark.parametrize(
        ("threshold", "phase_count", "expected_alias"),
        [
            pytest.param(5, 4, "@epic_lander", id="default-below"),
            pytest.param(5, 5, "@big_epic_lander", id="default-exact"),
            pytest.param(5, 6, "@big_epic_lander", id="default-above"),
            pytest.param(3, 2, "@epic_lander", id="custom-below"),
            pytest.param(3, 3, "@big_epic_lander", id="custom-exact"),
            pytest.param(3, 4, "@big_epic_lander", id="custom-above"),
        ],
    )
    def test_implicit_land_alias_uses_authored_phase_threshold(
        self,
        conn: sqlite3.Connection,
        monkeypatch: pytest.MonkeyPatch,
        threshold: int,
        phase_count: int,
        expected_alias: str,
    ) -> None:
        monkeypatch.setattr(
            "sase.bead.work.get_big_epic_phase_threshold",
            lambda: threshold,
        )
        seed(
            conn,
            [epic("e1"), *[phase(f"p{index}") for index in range(phase_count)]],
        )
        plan = _build_epic_work_plan(conn, "e1")

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )

        land_segment = rendered.split("\n---\n")[-1]
        assert f"%model:{expected_alias}" in land_segment

    def test_closed_phases_still_select_big_epic_lander_on_resume(
        self,
        conn: sqlite3.Connection,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "sase.bead.work.get_big_epic_phase_threshold",
            lambda: 5,
        )
        seed(
            conn,
            [
                epic("e1"),
                phase("p1", status=Status.CLOSED),
                phase("p2"),
                phase("p3"),
                phase("p4"),
                phase("p5"),
            ],
        )
        plan = _build_epic_work_plan(conn, "e1")

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )

        assert plan.total_phase_count == 5
        assert sum(len(wave) for wave in plan.waves) == 4
        assert "%model:@big_epic_lander" in rendered.split("\n---\n")[-1]

    def test_explicit_land_model_wins_for_large_epic(
        self,
        conn: sqlite3.Connection,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "sase.bead.work.get_big_epic_phase_threshold",
            lambda: 5,
        )
        seed(
            conn,
            [epic("e1", model="claude/opus"), *[phase(f"p{i}") for i in range(5)]],
        )
        plan = _build_epic_work_plan(conn, "e1")

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )

        land_segment = rendered.split("\n---\n")[-1]
        assert "%model:claude/opus" in land_segment
        assert "@big_epic_lander" not in land_segment

    def test_big_epic_directive_resolves_configured_target(
        self,
        conn: sqlite3.Connection,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "sase.bead.work.get_big_epic_phase_threshold",
            lambda: 2,
        )
        config = {
            "provider": "claude",
            "model_aliases": {
                "builtin": {"big_epic_lander": "codex/o3"},
            },
        }
        monkeypatch.setattr(
            "sase.llm_provider.config.get_llm_provider_config",
            lambda: config,
        )
        monkeypatch.setattr(
            "sase.llm_provider.registry.get_llm_provider_config",
            lambda: config,
        )
        seed(conn, [epic("e1"), phase("p1"), phase("p2")])
        plan = _build_epic_work_plan(conn, "e1")

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )

        assert "%model:@big_epic_lander" in rendered.split("\n---\n")[-1]
        assert resolve_model_provider("@big_epic_lander") == ("codex", "o3")

    def test_phase_model_emits_after_clan_and_tribe_before_plan(
        self, conn: sqlite3.Connection
    ) -> None:
        seed(conn, [epic("e1"), phase("p1", model="claude/opus")])
        plan = _build_epic_work_plan(conn, "e1")

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )

        phase_segment, land_segment = rendered.split("\n---\n")
        _assert_bare_auto_directives(rendered)
        assert phase_segment == (
            "%id:!e1.p1\n"
            "%clan(e1, tribe=epic, summary_script=sase_clan_summary_epic)\n"
            "%model:claude/opus\n"
            "%auto\n"
            "#bd/work_phase_bead:p1"
        )
        # The epic has no explicit land model, so the land agent defaults to the
        # epic-lander role alias.
        assert "%model:@epic_lander" in land_segment

    def test_phase_model_empty_renders_phase_worker_directive(
        self, conn: sqlite3.Connection
    ) -> None:
        seed(conn, [epic("e1"), phase("p1")])
        plan = _build_epic_work_plan(conn, "e1")

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )

        phase_segment, land_segment = rendered.split("\n---\n")
        assert "%model:@phase_worker" in phase_segment
        assert "%model:@epic_lander" in land_segment

    def test_mixed_phase_models_only_decorate_set_phases(
        self, conn: sqlite3.Connection
    ) -> None:
        seed(
            conn,
            [
                epic("e1"),
                phase("p1", model="codex/gpt-5.6-sol"),
                phase("p2"),
                phase("p3", model="#pro"),
            ],
        )
        plan = _build_epic_work_plan(conn, "e1")

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )

        segments = rendered.split("\n---\n")
        p1_seg = next(s for s in segments if "#bd/work_phase_bead:p1" in s)
        p2_seg = next(s for s in segments if "#bd/work_phase_bead:p2" in s)
        p3_seg = next(s for s in segments if "#bd/work_phase_bead:p3" in s)
        land_seg = segments[-1]
        assert "%model:codex/gpt-5.6-sol" in p1_seg
        assert "%model:@phase_worker" in p2_seg
        assert "%model:#pro" in p3_seg
        assert "%model:@epic_lander" in land_seg

    def test_epic_land_model_emits_on_land_segment(
        self, conn: sqlite3.Connection
    ) -> None:
        seed(conn, [epic("e1", model="claude/opus"), phase("p1")])
        plan = _build_epic_work_plan(conn, "e1")

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )

        segments = rendered.split("\n---\n")
        phase_segment, land_segment = segments
        _assert_bare_auto_directives(rendered)
        assert "%model:@phase_worker" in phase_segment
        # An explicit per-epic land model still wins over the epic-lander alias.
        assert land_segment == (
            "%id(!land, clan=e1)\n%model:claude/opus\n%auto\n%w:e1.p1\n#bd/land_epic:e1"
        )

    def test_no_model_only_adds_role_alias_directives_over_baseline(
        self, conn: sqlite3.Connection, monkeypatch
    ) -> None:
        seed(conn, [epic("e1"), phase("p1"), phase("p2")])
        plan = _build_epic_work_plan(conn, "e1")
        monkeypatch.setattr(
            "sase.llm_provider.config.get_llm_provider_config",
            lambda: {"provider": "claude"},
        )
        monkeypatch.setattr(
            "sase.llm_provider.registry.get_llm_provider_config",
            lambda: {"provider": "claude"},
        )

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )

        pre_model_baseline = (
            "%id:!e1.p1\n"
            "%clan(e1, tribe=epic, summary_script=sase_clan_summary_epic)\n"
            "%auto\n"
            "#bd/work_phase_bead:p1\n"
            "---\n"
            "%id(!p2, clan=e1)\n"
            "%auto\n"
            "#bd/work_phase_bead:p2\n"
            "---\n"
            "%id(!land, clan=e1)\n"
            "%auto\n"
            "%w:e1.p1,e1.p2\n"
            "#bd/land_epic:e1"
        )
        # The only additions over the baseline are the role-alias model
        # directives: @phase_worker on each phase and @epic_lander on land.
        stripped = rendered.replace("%model:@phase_worker\n", "").replace(
            "%model:@epic_lander\n", ""
        )
        assert stripped == pre_model_baseline
        _assert_bare_auto_directives(rendered)
        # The role aliases resolve through @default to the configured provider.
        assert resolve_model_provider("@phase_worker") == ("claude", "opus")
        assert resolve_model_provider("@epic_lander") == ("claude", "opus")

    def test_model_does_not_inject_extra_directives(
        self, conn: sqlite3.Connection
    ) -> None:
        # The Rust side validates model values on write; the renderer only
        # forwards them through. This test confirms the renderer doesn't
        # double-handle escaping (a literal value renders as one directive).
        seed(conn, [epic("e1"), phase("p1", model="provider/some-model")])
        plan = _build_epic_work_plan(conn, "e1")

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )

        phase_segment = rendered.split("\n---\n")[0]
        assert phase_segment.count("%model:") == 1
        assert "%model:provider/some-model" in phase_segment
