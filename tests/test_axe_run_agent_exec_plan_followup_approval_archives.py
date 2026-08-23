"""Tests for approved plan archive follow-up behavior."""

import os
from unittest.mock import call, patch

import pytest

from sase.axe import run_agent_exec_plan_accept as accept_mod
from sase.axe.run_agent_exec_plan import handle_plan_marker
from sase.axe.run_agent_successor import SuccessorRequest
from sase.llm_provider._plan_utils import PlanApprovalResult
from sase.sdd.store import SddStore
from tests._axe_run_agent_exec_plan_helpers import (
    make_ctx,
    make_state,
    patched_plan_deps,
)
from tests.plan_validation_helpers import VALID_TALE_PLAN


@pytest.fixture
def patch_plan_deps():
    with patched_plan_deps() as mocks:
        yield mocks


pytestmark = pytest.mark.usefixtures(patch_plan_deps.__name__)


class TestPlanFollowupApprovalArchives:
    """Verify approved plan archive paths and refs."""

    def test_saved_plan_path_skips_runner_write_and_commit(self, tmp_path) -> None:
        """Approval archive is the only canonical tale-plan writer."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text(VALID_TALE_PLAN, encoding="utf-8")
        published = tmp_path / "sdd" / "plans" / "202608" / "plan.md"
        published.parent.mkdir(parents=True)
        published.write_text(VALID_TALE_PLAN, encoding="utf-8")
        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            run_coder=False,
            commit_plan=True,
            saved_plan_path=str(published),
        )
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch("sase.sdd.files.write_sdd_files") as write_plan,
            patch(
                "sase.axe.run_agent_exec_plan_accept._commit_sdd_files"
            ) as mock_commit,
            patch("sase.sdd.files.commit_sdd_store_files") as store_commit,
        ):
            outcome = handle_plan_marker({"plan_file": plan_file}, ctx, state)

        assert outcome == "plan_committed"
        write_plan.assert_not_called()
        mock_commit.assert_not_called()
        store_commit.assert_not_called()
        accept_mod._publish_planner_prompt_archive.assert_called_once()
        assert call(state.current_artifacts_dir, "plan_committed", True) in (
            accept_mod.update_meta_field.call_args_list
        )

    def test_saved_plan_path_recovery_is_idempotent(self, tmp_path) -> None:
        ctx = make_ctx(tmp_path)
        published = tmp_path / "sdd" / "plans" / "202608" / "plan.md"
        published.parent.mkdir(parents=True)
        published.write_text(VALID_TALE_PLAN, encoding="utf-8")
        approval = PlanApprovalResult(
            action="approve",
            plan_file=str(tmp_path / "plan.md"),
            run_coder=False,
            commit_plan=True,
            saved_plan_path=str(published),
        )
        (tmp_path / "plan.md").write_text(VALID_TALE_PLAN, encoding="utf-8")

        def _run() -> object:
            state = make_state(tmp_path)
            with (
                patch(
                    "sase.llm_provider._plan_utils.handle_plan_approval",
                    return_value=approval,
                ),
                patch("sase.sdd.files.write_sdd_files") as write_plan,
                patch(
                    "sase.axe.run_agent_exec_plan_accept._commit_sdd_files"
                ) as mock_commit,
            ):
                outcome = handle_plan_marker(
                    {"plan_file": str(tmp_path / "plan.md")}, ctx, state
                )
            return outcome, write_plan, mock_commit

        first_outcome, first_write, first_commit = _run()
        second_outcome, second_write, second_commit = _run()
        assert first_outcome == second_outcome == "plan_committed"
        first_write.assert_not_called()
        second_write.assert_not_called()
        first_commit.assert_not_called()
        second_commit.assert_not_called()

    def test_host_v2_archive_ref_skips_runner_write_and_uses_plan_ref(
        self,
        tmp_path,
    ) -> None:
        runner_workspace = tmp_path / "runner-workspace"
        runner_workspace.mkdir()
        ctx = make_ctx(runner_workspace)
        state = make_state(runner_workspace)
        plan_file = runner_workspace / "plan.md"
        plan_file.write_text(VALID_TALE_PLAN, encoding="utf-8")
        host_saved = (
            tmp_path
            / "host-checkout"
            / "sase"
            / "repos"
            / "plans"
            / "202608"
            / "plan.md"
        )
        host_saved.parent.mkdir(parents=True)
        host_saved.write_text(VALID_TALE_PLAN, encoding="utf-8")
        runner_plans = tmp_path / "runner-checkout" / "sase" / "repos" / "plans"
        runner_plans.mkdir(parents=True)
        runner_store = SddStore(
            storage="sidecar_repos",
            sdd_dir=runner_plans,
            repo_root=runner_plans,
            remote_url="git@example.com:owner/plans.git",
            sidecar_role="plans",
        )
        plan_ref = "plan:202608/plan.md"
        approval = PlanApprovalResult(
            action="approve",
            plan_file=str(plan_file),
            run_coder=True,
            commit_plan=True,
            saved_plan_path=str(host_saved),
            plan_archive_owner="host",
            plan_archive_state="archived",
            plan_archive_protocol="host_v2",
            plan_archive_ref=plan_ref,
        )
        successors: list[SuccessorRequest] = []

        def capture_successor(
            _ctx: object,
            _state: object,
            request: SuccessorRequest,
            **_kwargs: object,
        ) -> str:
            successors.append(request)
            return "planner.coder"

        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch("sase.sdd.store.materialize_sdd_store", return_value=runner_store),
            patch("sase.sdd.files.write_sdd_files") as write_plan,
            patch(
                "sase.axe.run_agent_exec_plan_accept._commit_sdd_files"
            ) as mock_commit,
            patch("sase.sdd.files.commit_sdd_store_files") as store_commit,
            patch(
                "sase.axe.run_agent_exec_plan_accept.continue_as_successor",
                side_effect=capture_successor,
            ),
        ):
            outcome = handle_plan_marker({"plan_file": str(plan_file)}, ctx, state)

        assert outcome is None
        write_plan.assert_not_called()
        mock_commit.assert_not_called()
        store_commit.assert_not_called()
        assert call(state.current_artifacts_dir, "plan_committed", True) in (
            accept_mod.update_meta_field.call_args_list
        )
        assert os.environ["SASE_PLAN"] == str(plan_file)
        assert len(successors) == 1
        request = successors[0]
        assert f"@{plan_ref}\n\n" in request.prompt
        assert str(host_saved) not in request.prompt
        assert str(runner_plans) not in request.prompt
        assert request.relationships["sdd_plan_path"] == plan_ref
        assert request.relationships["plan_archive_ref"] == plan_ref
        assert request.relationships["plan_committed"] is True

    @pytest.mark.parametrize(
        "archive_ref",
        [
            None,
            "",
            "/tmp/legacy-plan.md",
            "research:202608/plan.md",
            "plan:../escape.md",
        ],
    )
    def test_host_v2_archive_response_requires_canonical_plan_ref(
        self,
        tmp_path,
        archive_ref: str | None,
    ) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(VALID_TALE_PLAN, encoding="utf-8")
        host_saved = tmp_path / "host" / "202608" / "plan.md"
        host_saved.parent.mkdir(parents=True)
        host_saved.write_text(VALID_TALE_PLAN, encoding="utf-8")
        approval = PlanApprovalResult(
            action="approve",
            plan_file=str(plan_file),
            run_coder=False,
            commit_plan=True,
            saved_plan_path=str(host_saved),
            plan_archive_owner="host",
            plan_archive_state="archived",
            plan_archive_protocol="host_v2",
            plan_archive_ref=archive_ref,
        )

        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch("sase.sdd.files.write_sdd_files") as write_plan,
            pytest.raises(RuntimeError, match="plan_archive_ref"),
        ):
            handle_plan_marker({"plan_file": str(plan_file)}, ctx, state)

        write_plan.assert_not_called()

    @pytest.mark.parametrize("path_case", ["missing", "outside_store"])
    def test_current_host_archive_response_requires_valid_saved_plan_path(
        self,
        tmp_path,
        path_case: str,
    ) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(VALID_TALE_PLAN, encoding="utf-8")
        saved_plan_path = None
        if path_case == "outside_store":
            outside = tmp_path / "outside.md"
            outside.write_text(VALID_TALE_PLAN, encoding="utf-8")
            saved_plan_path = str(outside)
        approval = PlanApprovalResult(
            action="approve",
            plan_file=str(plan_file),
            run_coder=False,
            commit_plan=True,
            saved_plan_path=saved_plan_path,
            plan_archive_owner="host",
            plan_archive_state="archived",
            plan_archive_protocol="host_v1",
        )

        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch("sase.sdd.files.write_sdd_files") as write_plan,
            pytest.raises(RuntimeError, match="saved_plan_path"),
        ):
            handle_plan_marker({"plan_file": str(plan_file)}, ctx, state)

        write_plan.assert_not_called()

    def test_legacy_approval_without_saved_path_still_writes_plan(
        self, tmp_path
    ) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text(VALID_TALE_PLAN, encoding="utf-8")
        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            run_coder=False,
            commit_plan=True,
        )
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(tmp_path / "spec.md", tmp_path / "plan.md"),
            ) as write_plan,
            patch(
                "sase.axe.run_agent_exec_plan_accept._commit_sdd_files"
            ) as mock_commit,
        ):
            outcome = handle_plan_marker({"plan_file": plan_file}, ctx, state)

        assert outcome == "plan_committed"
        write_plan.assert_called_once()
        mock_commit.assert_called_once()
