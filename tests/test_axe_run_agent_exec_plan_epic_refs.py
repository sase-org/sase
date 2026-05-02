"""Tests for axe run_agent_exec_plan epic SDD plan references."""

import dataclasses
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_exec_plan import _build_epic_plan_ref, handle_plan_marker
from sase.llm_provider._plan_utils import PlanApprovalResult
from tests._axe_run_agent_exec_plan_helpers import (
    make_ctx,
    make_state,
    patched_plan_deps,
)


@pytest.fixture
def patch_plan_deps():
    with patched_plan_deps() as mocks:
        yield mocks


@pytest.mark.usefixtures("patch_plan_deps")
class TestEpicPlanRefs:
    """Verify epic prompts reference generated SDD plan files correctly."""

    def test_epic_prompt_infers_legend_id_from_linked_prompt(self, tmp_path) -> None:
        workspace_dir = tmp_path
        sdd_dir = workspace_dir / "sdd"
        prompt_path = sdd_dir / "prompts" / "202605" / "zorg_epic1_foundations.md"
        plan_path = sdd_dir / "epics" / "202605" / "zorg_epic1_foundations.md"
        legend_path = sdd_dir / "legends" / "202605" / "zorg_v1_mvp.md"
        prompt_path.parent.mkdir(parents=True)
        plan_path.parent.mkdir(parents=True)
        legend_path.parent.mkdir(parents=True)
        prompt_path.write_text(
            "Please create epic #1 from sdd/legends/202605/zorg_v1_mvp.md\n",
            encoding="utf-8",
        )
        plan_path.write_text(
            "---\n"
            "prompt: sdd/prompts/202605/zorg_epic1_foundations.md\n"
            "---\n"
            "# Foundations\n",
            encoding="utf-8",
        )
        legend_path.write_text(
            "---\nlegend_bead_id: zorg-1\n---\n# Zorg MVP\n",
            encoding="utf-8",
        )

        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "zorg_epic1_foundations.md")
        Path(plan_file).write_text("# Plan", encoding="utf-8")
        approval = PlanApprovalResult(action="epic", plan_file=plan_file)

        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(prompt_path, plan_path),
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        assert (
            "#bd/new_epic:sdd/epics/202605/zorg_epic1_foundations.md,zorg-1"
            in state.current_prompt
        )

    def test_epic_prompt_uses_plan_frontmatter_legend_id(self, tmp_path) -> None:
        workspace_dir = tmp_path
        sdd_dir = workspace_dir / "sdd"
        prompt_path = sdd_dir / "prompts" / "202605" / "my_feature.md"
        plan_path = sdd_dir / "epics" / "202605" / "my_feature.md"
        prompt_path.parent.mkdir(parents=True)
        plan_path.parent.mkdir(parents=True)
        plan_path.write_text(
            "---\n"
            "prompt: sdd/prompts/202605/my_feature.md\n"
            "legend_bead_id: zorg-1\n"
            "---\n"
            "# Feature\n",
            encoding="utf-8",
        )

        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "my_feature.md")
        Path(plan_file).write_text("# Plan", encoding="utf-8")
        approval = PlanApprovalResult(action="epic", plan_file=plan_file)

        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(prompt_path, plan_path),
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        assert "#bd/new_epic:sdd/epics/202605/my_feature.md,zorg-1" in (
            state.current_prompt
        )

    def test_epic_prompt_without_legend_metadata_stays_unlinked(self, tmp_path) -> None:
        workspace_dir = tmp_path
        sdd_dir = workspace_dir / "sdd"
        prompt_path = sdd_dir / "prompts" / "202605" / "my_feature.md"
        plan_path = sdd_dir / "epics" / "202605" / "my_feature.md"
        legend_path = sdd_dir / "legends" / "202605" / "roadmap.md"
        prompt_path.parent.mkdir(parents=True)
        plan_path.parent.mkdir(parents=True)
        legend_path.parent.mkdir(parents=True)
        prompt_path.write_text(
            "Please use sdd/legends/202605/roadmap.md\n",
            encoding="utf-8",
        )
        plan_path.write_text(
            "---\nprompt: sdd/prompts/202605/my_feature.md\n---\n# Feature\n",
            encoding="utf-8",
        )
        legend_path.write_text("# Roadmap\n", encoding="utf-8")

        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "my_feature.md")
        Path(plan_file).write_text("# Plan", encoding="utf-8")
        approval = PlanApprovalResult(action="epic", plan_file=plan_file)

        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(prompt_path, plan_path),
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        assert "#bd/new_epic:sdd/epics/202605/my_feature.md\n" in (state.current_prompt)
        assert "#bd/new_epic:sdd/epics/202605/my_feature.md," not in (
            state.current_prompt
        )

    def test_epic_prompt_with_multiple_legend_ids_stays_unlinked(
        self, tmp_path
    ) -> None:
        workspace_dir = tmp_path
        sdd_dir = workspace_dir / "sdd"
        prompt_path = sdd_dir / "prompts" / "202605" / "my_feature.md"
        plan_path = sdd_dir / "epics" / "202605" / "my_feature.md"
        legend_a = sdd_dir / "legends" / "202605" / "roadmap_a.md"
        legend_b = sdd_dir / "legends" / "202605" / "roadmap_b.md"
        prompt_path.parent.mkdir(parents=True)
        plan_path.parent.mkdir(parents=True)
        legend_a.parent.mkdir(parents=True)
        prompt_path.write_text(
            "Please use sdd/legends/202605/roadmap_a.md\n",
            encoding="utf-8",
        )
        plan_path.write_text(
            "---\n"
            "prompt: sdd/prompts/202605/my_feature.md\n"
            "---\n"
            "# Feature\n\n"
            "Related legend: sdd/legends/202605/roadmap_b.md\n",
            encoding="utf-8",
        )
        legend_a.write_text(
            "---\nlegend_bead_id: zorg-1\n---\n# Roadmap A\n",
            encoding="utf-8",
        )
        legend_b.write_text(
            "---\nlegend_bead_id: zorg-2\n---\n# Roadmap B\n",
            encoding="utf-8",
        )

        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "my_feature.md")
        Path(plan_file).write_text("# Plan", encoding="utf-8")
        approval = PlanApprovalResult(action="epic", plan_file=plan_file)

        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(prompt_path, plan_path),
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        assert "#bd/new_epic:sdd/epics/202605/my_feature.md\n" in (state.current_prompt)
        assert "#bd/new_epic:sdd/epics/202605/my_feature.md," not in (
            state.current_prompt
        )

    def test_epic_prompt_uses_non_vc_sdd_ref_from_google_sibling_workspace(
        self, tmp_path
    ) -> None:
        workspace_dir = (
            tmp_path / "google" / "src" / "cloud" / "bbugyi" / "bug_102" / "google3"
        )
        sdd_dir = (
            tmp_path
            / "google"
            / "src"
            / "cloud"
            / "bbugyi"
            / "bug"
            / "google3"
            / ".sase"
            / "sdd"
        )
        sdd_plan_path = sdd_dir / "epics" / "202604" / "missing_buyers_research.md"
        workspace_dir.mkdir(parents=True)
        sdd_plan_path.parent.mkdir(parents=True)
        sdd_plan_path.write_text("# Plan", encoding="utf-8")

        ctx = dataclasses.replace(
            make_ctx(tmp_path),
            workspace_dir=str(workspace_dir),
            workspace_num=102,
            vcs_tag="",
        )
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "missing_buyers_research.md")
        Path(plan_file).write_text("# Plan", encoding="utf-8")
        approval = PlanApprovalResult(action="epic", plan_file=plan_file)

        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch("sase.sdd.beads.get_sdd_config", return_value=False),
            patch("sase.sdd.files.get_sdd_dir", return_value=sdd_dir),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(
                    sdd_dir / "prompts" / "202604" / "missing_buyers_research.md",
                    sdd_plan_path,
                ),
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        assert (
            "#bd/new_epic:.sase/sdd/epics/202604/missing_buyers_research.md"
            in state.current_prompt
        )

    def test_epic_plan_ref_uses_workspace_relative_vc_path(self, tmp_path) -> None:
        workspace_dir = tmp_path / "repo"
        sdd_plan_path = workspace_dir / "sdd" / "epics" / "202604" / "my_feature.md"
        sdd_plan_path.parent.mkdir(parents=True)
        sdd_plan_path.write_text("# Plan", encoding="utf-8")

        assert (
            _build_epic_plan_ref(
                sdd_plan_path=sdd_plan_path,
                sdd_dir=workspace_dir,
                workspace_dir=str(workspace_dir),
                sdd_plan_name="my_feature",
                version_controlled=True,
                fallback_plan_file="/tmp/original.md",
            )
            == "sdd/epics/202604/my_feature.md"
        )

    def test_epic_plan_ref_fallback_uses_canonical_epic_path(self, tmp_path) -> None:
        workspace_dir = tmp_path / "repo"

        with patch("sase.sdd.files.get_yyyymm", return_value="202604"):
            assert (
                _build_epic_plan_ref(
                    sdd_plan_path=workspace_dir
                    / "sdd"
                    / "epics"
                    / "202604"
                    / "missing.md",
                    sdd_dir=workspace_dir / "sdd",
                    workspace_dir=str(workspace_dir),
                    sdd_plan_name="missing",
                    version_controlled=True,
                    fallback_plan_file="/tmp/original.md",
                )
                == "sdd/epics/202604/missing.md"
            )
