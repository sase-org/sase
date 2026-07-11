"""Tests for approved plan follow-up actions."""

import os
from unittest.mock import call, patch

import pytest

from sase.axe import run_agent_exec_plan_accept as accept_mod
from sase.axe.run_agent_exec_plan import handle_plan_marker
from sase.llm_provider._plan_utils import PlanApprovalResult
from sase.sdd.store import SddStore
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
class TestPlanFollowupApprovals:
    """Verify plan approval follow-up actions and metadata."""

    def test_accepted_plan_persists_epic_action(self, tmp_path) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_artifacts_dir = state.current_artifacts_dir
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        approval = PlanApprovalResult(action="epic", plan_file=plan_file)
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
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

    def test_plan_approval_initializes_sdd_before_writing_files(self, tmp_path) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")
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

    def test_epic_force_sdd_commit(self, tmp_path) -> None:
        """Epic approvals commit SDD files even with stale false flags."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

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
                "sase.sdd.files.write_sdd_files",
                return_value=(tmp_path / "spec.md", tmp_path / "plan.md"),
            ),
            patch(
                "sase.axe.run_agent_exec_plan_accept._commit_sdd_files"
            ) as mock_commit,
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        mock_commit.assert_called_once()
        assert mock_commit.call_args.kwargs["plan_tier"] == "epic"

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

    def test_approve_followup_records_default_effort(
        self, tmp_path, monkeypatch
    ) -> None:
        """Coder follow-up metadata records llm_provider.default_effort."""
        monkeypatch.setattr(
            "sase.llm_provider.config._get_default_effort", lambda: "xhigh"
        )
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        approval = PlanApprovalResult(action="approve", plan_file=plan_file)
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(tmp_path / "spec.md", tmp_path / "plan.md"),
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        assert call("/tmp/followup", "reasoning_effort", "xhigh") in (
            accept_mod.update_meta_field.call_args_list
        )

    def test_epic_followup_records_default_effort(self, tmp_path, monkeypatch) -> None:
        """Epic follow-up metadata records llm_provider.default_effort."""
        monkeypatch.setattr(
            "sase.llm_provider.config._get_default_effort", lambda: "high"
        )
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "epic.md")
        (tmp_path / "epic.md").write_text("# Plan")

        approval = PlanApprovalResult(action="epic", plan_file=plan_file)
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(tmp_path / "spec.md", tmp_path / "epic.md"),
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        assert call("/tmp/followup", "reasoning_effort", "high") in (
            accept_mod.update_meta_field.call_args_list
        )

    def test_custom_coder_prompt_effort_beats_default(
        self, tmp_path, monkeypatch
    ) -> None:
        """A custom coder prompt's explicit %effort wins over the default."""
        monkeypatch.setattr(
            "sase.llm_provider.config._get_default_effort", lambda: "high"
        )
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            coder_prompt="%effort:low\nUse low effort for the handoff.",
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
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        assert call("/tmp/followup", "reasoning_effort", "low") in (
            accept_mod.update_meta_field.call_args_list
        )

    def test_followup_model_suffix_effort_beats_default(
        self, tmp_path, monkeypatch
    ) -> None:
        """A %model:...@effort suffix is recorded as explicit effort."""
        monkeypatch.setattr(
            "sase.llm_provider.config._get_default_effort", lambda: "high"
        )
        state = make_state(tmp_path)
        state.current_artifacts_dir = "/tmp/followup"

        accept_mod._write_followup_effort_meta(
            state, "%model:@claude_coder@xhigh\nImplement the approved plan."
        )

        assert call("/tmp/followup", "reasoning_effort", "xhigh") in (
            accept_mod.update_meta_field.call_args_list
        )

    def test_approve_followup_omits_unset_effort(self, tmp_path, monkeypatch) -> None:
        """No explicit/default effort leaves plan-chain follow-up effort absent."""
        monkeypatch.setattr(
            "sase.llm_provider.config._get_default_effort", lambda: None
        )
        ctx = make_ctx(tmp_path)
        ctx.agent_meta["reasoning_effort"] = "xhigh"
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        approval = PlanApprovalResult(action="approve", plan_file=plan_file)
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(tmp_path / "spec.md", tmp_path / "plan.md"),
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        effort_calls = [
            meta_call
            for meta_call in accept_mod.update_meta_field.call_args_list
            if meta_call.args[1] == "reasoning_effort"
        ]
        assert effort_calls == []
        followup_base_meta = accept_mod.create_followup_artifacts.call_args.args[1]
        assert "reasoning_effort" not in followup_base_meta

    def test_coder_prompt_uses_saved_sdd_plan_ref(self, tmp_path) -> None:
        """Normal approved plans hand off the committed canonical plan file."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "scratch_plan.md")
        (tmp_path / "scratch_plan.md").write_text("# Plan")
        sdd_plan = tmp_path / "sdd" / "plans" / "202605" / "scratch_plan.md"
        sdd_plan.parent.mkdir(parents=True)
        sdd_plan.write_text("# Saved Plan")

        approval = PlanApprovalResult(action="approve", plan_file=plan_file)
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(
                    tmp_path
                    / "sdd"
                    / "plans"
                    / "202605"
                    / "prompts"
                    / "scratch_plan.md",
                    sdd_plan,
                ),
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        assert "@sdd/plans/202605/scratch_plan.md" in state.current_prompt

    def test_coder_prompt_no_commit_uses_archived_plan_ref(
        self, tmp_path, monkeypatch
    ) -> None:
        """No-commit approvals hand off the archived plan, not local SDD."""
        monkeypatch.delenv("SASE_PLAN", raising=False)
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        archived_plan = tmp_path / "archive" / "scratch_plan.md"
        archived_plan.parent.mkdir()
        archived_plan.write_text("# Archived Plan")
        sdd_plan = tmp_path / "sdd" / "plans" / "202605" / "scratch_plan.md"
        sdd_plan.parent.mkdir(parents=True)
        sdd_plan.write_text("# Saved Plan")

        approval = PlanApprovalResult(
            action="approve",
            plan_file=str(archived_plan),
            commit_plan=False,
            run_coder=True,
        )
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(
                    tmp_path
                    / "sdd"
                    / "plans"
                    / "202605"
                    / "prompts"
                    / "scratch_plan.md",
                    sdd_plan,
                ),
            ),
        ):
            handle_plan_marker({"plan_file": str(archived_plan)}, ctx, state)

        assert state.current_prompt.startswith("%model:@claude_coder\n#gh:sase ")
        assert f"@{archived_plan}" in state.current_prompt
        assert "@sdd/plans/202605/scratch_plan.md" not in state.current_prompt
        assert os.environ["SASE_PLAN"] == str(archived_plan)

    def test_coder_prompt_commit_failure_uses_archived_plan_ref(
        self, tmp_path, monkeypatch
    ) -> None:
        """Failed SDD commits do not hand coder agents volatile repo SDD refs."""
        monkeypatch.delenv("SASE_PLAN", raising=False)
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        archived_plan = tmp_path / "archive" / "scratch_plan.md"
        archived_plan.parent.mkdir()
        archived_plan.write_text("# Archived Plan")
        sdd_plan = tmp_path / "sdd" / "plans" / "202605" / "scratch_plan.md"
        sdd_plan.parent.mkdir(parents=True)
        sdd_plan.write_text("# Saved Plan")

        approval = PlanApprovalResult(
            action="approve",
            plan_file=str(archived_plan),
            commit_plan=True,
            run_coder=True,
        )
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(
                    tmp_path
                    / "sdd"
                    / "plans"
                    / "202605"
                    / "prompts"
                    / "scratch_plan.md",
                    sdd_plan,
                ),
            ),
            patch(
                "sase.axe.run_agent_exec_plan_accept._commit_sdd_files",
                return_value=False,
            ),
        ):
            handle_plan_marker({"plan_file": str(archived_plan)}, ctx, state)

        assert f"@{archived_plan}" in state.current_prompt
        assert "@sdd/plans/202605/scratch_plan.md" not in state.current_prompt
        assert os.environ["SASE_PLAN"] == str(archived_plan)
        relationships = accept_mod.create_followup_artifacts.call_args.kwargs[
            "relationships"
        ]
        assert relationships["plan_committed"] is False
        assert call(str(tmp_path / "artifacts"), "plan_committed", False) in (
            accept_mod.update_meta_field.call_args_list
        )

    def test_epic_commit_failure_uses_archived_plan_ref(self, tmp_path) -> None:
        """Epic handoffs fall back to the archived plan after commit failure."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        archived_plan = tmp_path / "archive" / "epic_plan.md"
        archived_plan.parent.mkdir()
        archived_plan.write_text("# Archived Plan")
        sdd_plan = tmp_path / "sdd" / "plans" / "202605" / "epic_plan.md"
        sdd_plan.parent.mkdir(parents=True)
        sdd_plan.write_text("# Saved Plan")

        approval = PlanApprovalResult(
            action="epic",
            plan_file=str(archived_plan),
            commit_plan=True,
            run_coder=True,
        )
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(
                    tmp_path / "sdd" / "plans" / "202605" / "prompts" / "epic_plan.md",
                    sdd_plan,
                ),
            ),
            patch(
                "sase.axe.run_agent_exec_plan_accept._commit_sdd_files",
                return_value=False,
            ),
        ):
            handle_plan_marker({"plan_file": str(archived_plan)}, ctx, state)

        assert f"#bd/new_epic:{archived_plan}" in state.current_prompt
        assert "sdd/plans/202605/epic_plan.md" not in state.current_prompt
        relationships = accept_mod.create_followup_artifacts.call_args.kwargs[
            "relationships"
        ]
        assert relationships["plan_committed"] is False
