"""Tests for approved plan follow-up actions."""

from unittest.mock import call, patch

import pytest

from sase.axe import run_agent_exec_plan_accept as accept_mod
from sase.axe.run_agent_exec_plan import handle_plan_marker
from sase.llm_provider._plan_utils import PlanApprovalResult
from sase.plan_approval_actions import PlanApprovalValidationError
from sase.sdd.store import SddStore
from sase.sdd._store_types import SddMaterializationError
from tests._axe_run_agent_exec_plan_helpers import (
    make_ctx,
    make_state,
    patched_plan_deps,
)
from tests.plan_validation_helpers import VALID_EPIC_PLAN


@pytest.fixture
def patch_plan_deps():
    with patched_plan_deps() as mocks:
        yield mocks


@pytest.mark.usefixtures("patch_plan_deps")
class TestPlanFollowupApprovals:
    """Verify plan approval follow-up actions and metadata."""

    def test_accepted_plan_persists_epic_action(self, tmp_path) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_artifacts_dir = state.current_artifacts_dir
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text(VALID_EPIC_PLAN)

        approval = PlanApprovalResult(action="epic", plan_file=plan_file)
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
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
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch("sase.sdd.files.write_sdd_spec") as write_sdd,
            pytest.raises(PlanApprovalValidationError),
        ):
            handle_plan_marker({"plan_file": str(plan)}, ctx, state)

        write_sdd.assert_not_called()
        accept_mod.update_meta_field.assert_not_called()

    def test_plan_approval_initializes_sdd_before_writing_files(self, tmp_path) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text(VALID_EPIC_PLAN)
        order: list[str] = []

        def ensure_sdd(*_args, **_kwargs):
            order.append("ensure")

        def write_sdd(*_args, **_kwargs):
            order.append("write")
            return tmp_path / "spec.md", tmp_path / "plan.md"

        approval = PlanApprovalResult(action="approve", plan_file=plan_file)
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.ensure_bare_git_sdd_initialized",
                side_effect=ensure_sdd,
            ),
            patch("sase.sdd.files.write_sdd_files", side_effect=write_sdd),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        assert order[:2] == ["ensure", "write"]

    def test_separate_repo_plan_commit_pushes_synchronously(self, tmp_path) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")
        store_root = tmp_path / ".sase" / "sdd"
        store_root.mkdir(parents=True)
        sdd_store = SddStore(
            storage="separate_repo",
            sdd_dir=store_root,
            repo_root=store_root,
            provider="github",
            remote_url="git@example.com:owner/repo-sdd.git",
        )
        commit_kwargs: list[dict[str, object]] = []

        def commit_sdd_store_files(*_args: object, **kwargs: object) -> bool:
            commit_kwargs.append(kwargs)
            return True

        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            run_coder=True,
            commit_plan=True,
        )
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch("sase.sdd.store.materialize_sdd_store", return_value=sdd_store),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(tmp_path / "spec.md", tmp_path / "plan.md"),
            ),
            patch(
                "sase.sdd.files.commit_sdd_store_files",
                side_effect=commit_sdd_store_files,
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        assert commit_kwargs
        assert all(kwargs["push_after_commit"] is True for kwargs in commit_kwargs)

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
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
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
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_spec",
                return_value=(tmp_path / "spec.md", tmp_path / "plan.md"),
            ),
        ):
            outcome = handle_plan_marker({"plan_file": plan_file}, ctx, state)

        assert outcome == "epic_approved"

    def test_unusable_epic_store_stops_before_launcher_with_home_resume(
        self, tmp_path
    ) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        home_plan = tmp_path / "home" / "approved.md"
        home_plan.parent.mkdir()
        home_plan.write_text(VALID_EPIC_PLAN)
        approval = PlanApprovalResult(action="epic", plan_file=str(home_plan))

        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
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

    def test_approve_no_coder_commit_true_returns_plan_committed(
        self, tmp_path
    ) -> None:
        """run_coder=False, commit_plan=True -> outcome 'plan_committed', SDD committed."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

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
            ),
            patch(
                "sase.axe.run_agent_exec_plan_accept._commit_sdd_files"
            ) as mock_commit,
        ):
            outcome = handle_plan_marker({"plan_file": plan_file}, ctx, state)
        assert outcome == "plan_committed"
        mock_commit.assert_called_once()
        assert call(state.current_artifacts_dir, "plan_committed", True) in (
            accept_mod.update_meta_field.call_args_list
        )

    def test_approve_no_coder_commit_false_skips_commit(self, tmp_path) -> None:
        """run_coder=False, commit_plan=False -> outcome 'plan_committed', no SDD commit."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            run_coder=False,
            commit_plan=False,
        )
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(tmp_path / "spec.md", tmp_path / "plan.md"),
            ),
            patch(
                "sase.axe.run_agent_exec_plan_accept._commit_sdd_files"
            ) as mock_commit,
        ):
            outcome = handle_plan_marker({"plan_file": plan_file}, ctx, state)
        assert outcome == "plan_committed"
        mock_commit.assert_not_called()
        assert call(state.current_artifacts_dir, "plan_committed", False) in (
            accept_mod.update_meta_field.call_args_list
        )

    @pytest.mark.parametrize(
        (
            "auto_action",
            "commit_plan",
            "expected_plan_action",
            "expected_committed",
        ),
        [
            ("approve", False, "approve", False),
            ("tale", True, "tale", True),
        ],
    )
    def test_auto_plan_result_classifies_and_commits_by_action(
        self,
        tmp_path,
        auto_action: str,
        commit_plan: bool,
        expected_plan_action: str,
        expected_committed: bool,
    ) -> None:
        """Auto plan approval stays plain; auto tale still commits as a tale."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_artifacts_dir = state.current_artifacts_dir
        plan_file = str(tmp_path / f"{auto_action}.md")
        sdd_plan = tmp_path / "sdd" / "plans" / "202606" / f"{auto_action}.md"
        (tmp_path / f"{auto_action}.md").write_text("# Plan")
        sdd_plan.parent.mkdir(parents=True)
        sdd_plan.write_text("# Saved Plan")

        approval = PlanApprovalResult(
            action=auto_action,
            plan_file=plan_file,
            commit_plan=commit_plan,
            run_coder=True,
        )
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(tmp_path / "spec.md", sdd_plan),
            ),
            patch(
                "sase.axe.run_agent_exec_plan_accept._commit_sdd_files",
                return_value=True,
            ) as mock_commit,
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        meta_calls = accept_mod.update_meta_field.call_args_list
        assert (
            call(plan_artifacts_dir, "plan_action", expected_plan_action) in meta_calls
        )
        assert (
            call(plan_artifacts_dir, "plan_committed", expected_committed) in meta_calls
        )
        relationships = accept_mod.create_followup_artifacts.call_args.kwargs[
            "relationships"
        ]
        assert relationships["plan_committed"] is expected_committed
        if expected_committed:
            mock_commit.assert_called_once()
            assert mock_commit.call_args.kwargs["plan_tier"] == "tale"
        else:
            mock_commit.assert_not_called()

    def test_approve_followup_propagates_plan_committed_flag(self, tmp_path) -> None:
        """Coder follow-up metadata records whether the SDD plan was committed."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        sdd_plan = tmp_path / "sdd" / "plans" / "202605" / "plan.md"
        (tmp_path / "plan.md").write_text("# Plan")
        sdd_plan.parent.mkdir(parents=True)
        sdd_plan.write_text("# SDD")

        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            run_coder=True,
            commit_plan=True,
        )
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(tmp_path / "spec.md", sdd_plan),
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        relationships = accept_mod.create_followup_artifacts.call_args.kwargs[
            "relationships"
        ]
        assert relationships["plan_committed"] is True
