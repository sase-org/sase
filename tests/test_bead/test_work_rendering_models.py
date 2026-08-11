"""Model-directive prompt rendering tests for bead work plans."""

from __future__ import annotations

import sqlite3

import pytest

from sase.bead.model import PhaseSize, Status
from sase.bead.work import _build_epic_work_plan, render_multi_prompt
from sase.llm_provider.config import resolve_model_alias_with_effort
from sase.llm_provider.model_alias_policy import (
    CHEAP_MODEL_ALIAS_NAME,
    SMARTER_MODEL_ALIAS_NAME,
)
from sase.llm_provider.registry import resolve_model_provider
from tests._model_alias_defaults_fixture import frozen_selector_member
from sase.xprompt.workflow_models import Workflow

from .work_test_helpers import assert_bare_auto_directives, epic, phase, seed


class TestModelDirective:
    @pytest.mark.parametrize(
        ("size", "expected_model", "expects_plan"),
        [
            (None, "@small_worker", False),
            (PhaseSize.XSMALL, "@xsmall_worker", False),
            (PhaseSize.SMALL, "@small_worker", False),
            (PhaseSize.MEDIUM, "@medium_worker", False),
            (PhaseSize.LARGE, "@large_worker", True),
            (PhaseSize.XLARGE, "@xlarge_worker", True),
        ],
    )
    def test_phase_size_controls_model_and_planning_handoff(
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

    @pytest.mark.parametrize(
        ("size", "model", "expects_plan"),
        [
            pytest.param(None, "claude/sonnet", False, id="legacy"),
            pytest.param(PhaseSize.XSMALL, "claude/haiku", False, id="xsmall"),
            pytest.param(PhaseSize.SMALL, "claude/sonnet", False, id="small"),
            pytest.param(PhaseSize.MEDIUM, "@smart", False, id="medium"),
            pytest.param(
                PhaseSize.LARGE,
                "codex/gpt-5.6-sol",
                True,
                id="large",
            ),
            pytest.param(
                PhaseSize.XLARGE,
                "claude/claude-fable-5",
                True,
                id="xlarge",
            ),
        ],
    )
    def test_explicit_model_wins_for_every_phase_size(
        self,
        conn: sqlite3.Connection,
        size: PhaseSize | None,
        model: str,
        expects_plan: bool,
    ) -> None:
        seed(
            conn,
            [
                epic("e1"),
                phase(
                    "p1",
                    model=model,
                    size=size,
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
        assert f"%model:{model}" in phase_segment
        assert "_worker" not in phase_segment
        assert ("#plan" in phase_segment.splitlines()) is expects_plan
        if expects_plan:
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
        assert_bare_auto_directives(rendered)
        assert phase_segment == (
            "%id(!e1.p1, bead=p1)\n"
            "%clan(e1, tribe=epic, summary_script=sase_clan_summary_epic)\n"
            "%model:claude/opus\n"
            "%auto\n"
            "#bd/work_phase_bead:p1"
        )
        # The epic has no explicit land model, so the land agent defaults to the
        # epic-lander role alias.
        assert "%model:@epic_lander" in land_segment

    def test_phase_model_empty_renders_small_worker_directive(
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
        assert "%model:@small_worker" in phase_segment
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
        assert "%model:@small_worker" in p2_seg
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
        assert_bare_auto_directives(rendered)
        assert "%model:@small_worker" in phase_segment
        # An explicit per-epic land model still wins over the epic-lander alias.
        assert land_segment == (
            "%id(!land, clan=e1, bead=e1)\n"
            "%model:claude/opus\n"
            "%auto\n"
            "%w:e1.p1\n"
            "%w(bead=p1)\n"
            "#bd/land_epic:e1"
        )

    def test_no_model_only_adds_role_alias_directives_over_baseline(
        self, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
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
        monkeypatch.setattr(
            "sase.llm_provider.config._resolved_target_is_available",
            lambda _target: True,
        )

        rendered = render_multi_prompt(
            plan,
            work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
            land_epic_xprompt=Workflow(name="bd/land_epic"),
        )

        pre_model_baseline = (
            "%id(!e1.p1, bead=p1)\n"
            "%clan(e1, tribe=epic, summary_script=sase_clan_summary_epic)\n"
            "%auto\n"
            "#bd/work_phase_bead:p1\n"
            "---\n"
            "%id(!p2, clan=e1, bead=p2)\n"
            "%auto\n"
            "#bd/work_phase_bead:p2\n"
            "---\n"
            "%id(!land, clan=e1, bead=e1)\n"
            "%auto\n"
            "%w:e1.p1,e1.p2\n"
            "%w(bead=p1)\n"
            "%w(bead=p2)\n"
            "#bd/land_epic:e1"
        )
        # The only additions over the baseline are the role-alias model
        # directives: @small_worker on each phase and @epic_lander on land.
        stripped = rendered.replace("%model:@small_worker\n", "").replace(
            "%model:@epic_lander\n", ""
        )
        assert stripped == pre_model_baseline
        assert_bare_auto_directives(rendered)
        # The selector-backed phase role preserves its pool member's effort.
        small = resolve_model_alias_with_effort("@small_worker")
        assert (small.target, small.effort) == frozen_selector_member(
            CHEAP_MODEL_ALIAS_NAME, 0
        )
        # The lander role resolves through @default, which delegates to @smarter.
        lander = resolve_model_alias_with_effort("@epic_lander")
        assert (lander.target, lander.effort) == frozen_selector_member(
            SMARTER_MODEL_ALIAS_NAME, 0
        )

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
