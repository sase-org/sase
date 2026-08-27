"""Tests for epic plan follow-up approval behavior."""

from unittest.mock import call, patch

import pytest

from sase.axe import run_agent_exec_plan_accept as accept_mod
from sase.axe.run_agent_exec_plan import handle_plan_marker
from sase.llm_provider._plan_utils import PlanApprovalResult
from sase.plan_approval_actions import PlanApprovalValidationError
from sase.sdd._store_types import SddMaterializationError
from tests._axe_run_agent_exec_plan_helpers import (
    make_ctx,
    make_state,
    patch_plan_gate_shell_result,
    patched_plan_deps,
)
from tests.plan_validation_helpers import VALID_EPIC_PLAN


@pytest.fixture
def patch_plan_deps():
    with patched_plan_deps() as mocks:
        yield mocks


pytestmark = pytest.mark.usefixtures(patch_plan_deps.__name__)


class TestPlanFollowupEpicApprovals:
    """Verify epic plan approval follow-up actions and metadata."""

    def test_accepted_plan_persists_epic_action(self, tmp_path) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_artifacts_dir = state.current_artifacts_dir
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text(VALID_EPIC_PLAN)

        approval = PlanApprovalResult(action="epic", plan_file=plan_file)
        with (
            patch_plan_gate_shell_result(approval),
            patch(
                "sase.sdd.files.write_sdd_spec",
                return_value=(tmp_path / "spec.md", tmp_path / "plan.md"),
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        assert call(plan_artifacts_dir, "plan_approved", True) in (
            accept_mod.update_meta_field.call_args_list
        )
        assert call(plan_artifacts_dir, "plan_action", "epic") in (
            accept_mod.update_meta_field.call_args_list
        )

    def test_runner_epic_gate_precedes_all_sdd_side_effects(self, tmp_path) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan = tmp_path / "invalid.md"
        plan.write_text("# Invalid epic\n", encoding="utf-8")
        approval = PlanApprovalResult(action="epic", plan_file=str(plan))

        with (
            patch_plan_gate_shell_result(approval),
            patch("sase.sdd.files.write_sdd_spec") as write_sdd,
            pytest.raises(PlanApprovalValidationError),
        ):
            handle_plan_marker({"plan_file": str(plan)}, ctx, state)

        write_sdd.assert_not_called()
        accept_mod.update_meta_field.assert_not_called()

    def test_epic_commits_only_spec_even_with_stale_false_flags(self, tmp_path) -> None:
        """Epic approvals publish the prompt archive, never a plans snapshot."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text(VALID_EPIC_PLAN)

        approval = PlanApprovalResult(
            action="epic",
            plan_file=plan_file,
            commit_plan=False,
            run_coder=False,
        )
        with (
            patch_plan_gate_shell_result(approval),
            patch(
                "sase.sdd.files.write_sdd_spec",
                return_value=(tmp_path / "spec.md", tmp_path / "plan.md"),
            ),
            patch("sase.sdd.files.write_sdd_files") as write_plan,
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        write_plan.assert_not_called()
        accept_mod._publish_planner_prompt_archive.assert_called_once()

    def test_epic_without_owner_marker_still_has_no_agent_side_launch(
        self, tmp_path
    ) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text(VALID_EPIC_PLAN)
        approval = PlanApprovalResult(action="epic", plan_file=plan_file)

        with (
            patch_plan_gate_shell_result(approval),
            patch(
                "sase.sdd.files.write_sdd_spec",
                return_value=(tmp_path / "spec.md", tmp_path / "plan.md"),
            ),
        ):
            outcome = handle_plan_marker({"plan_file": plan_file}, ctx, state)

        assert outcome == "epic_approved"

    def test_host_owned_unusable_store_degrades_to_epic_approved(
        self, tmp_path
    ) -> None:
        """The host already owns the launch, so the planner only records its own failure."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_artifacts_dir = state.current_artifacts_dir
        home_plan = tmp_path / "home" / "approved.md"
        home_plan.parent.mkdir()
        home_plan.write_text(VALID_EPIC_PLAN)
        approval = PlanApprovalResult(
            action="epic",
            plan_file=str(home_plan),
            epic_launch_owner="host",
        )

        with (
            patch_plan_gate_shell_result(approval),
            patch(
                "sase.sdd.store.materialize_sdd_store",
                side_effect=SddMaterializationError("plans store is mid-rebase"),
            ),
            patch("sase.sdd.files.write_sdd_spec") as write_sdd,
            patch(
                "sase.axe.run_agent_exec_plan_accept._notify_epic_launch_failure"
            ) as notify_failure,
        ):
            outcome = handle_plan_marker(
                {"plan_file": str(home_plan)},
                ctx,
                state,
            )

        assert outcome == "epic_approved"
        write_sdd.assert_not_called()
        notify_failure.assert_not_called()
        meta_calls = accept_mod.update_meta_field.call_args_list
        assert (
            call(
                plan_artifacts_dir, "sdd_publication_error", "plans store is mid-rebase"
            )
            in meta_calls
        )
        assert not any(c.args[1] == "epic_launch_error" for c in meta_calls)

    def test_unowned_unusable_epic_store_stops_before_launcher_with_home_resume(
        self, tmp_path
    ) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_artifacts_dir = state.current_artifacts_dir
        home_plan = tmp_path / "home" / "approved.md"
        home_plan.parent.mkdir()
        home_plan.write_text(VALID_EPIC_PLAN)
        approval = PlanApprovalResult(action="epic", plan_file=str(home_plan))

        with (
            patch_plan_gate_shell_result(approval),
            patch(
                "sase.sdd.store.materialize_sdd_store",
                side_effect=SddMaterializationError("plans store is mid-rebase"),
            ),
            patch("sase.sdd.files.write_sdd_spec") as write_sdd,
            patch(
                "sase.axe.run_agent_exec_plan_accept._notify_epic_launch_failure"
            ) as notify_failure,
        ):
            outcome = handle_plan_marker(
                {"plan_file": str(home_plan)},
                ctx,
                state,
            )

        assert outcome == "epic_launch_failed"
        write_sdd.assert_not_called()
        notify_failure.assert_called_once_with(
            ctx,
            str(home_plan),
            ("plans store is mid-rebase",),
        )
        assert (
            call(plan_artifacts_dir, "epic_launch_error", "plans store is mid-rebase")
            in accept_mod.update_meta_field.call_args_list
        )
