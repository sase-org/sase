"""Tests for approved plan follow-up metadata."""

from unittest.mock import patch

import pytest

from sase.axe.run_agent_exec_plan import (
    _accepted_plan_action_for_meta,
    handle_plan_marker,
)
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
class TestPlanFollowupMetadata:
    """Verify approved plan metadata and action inference."""

    def test_coder_meta_updated_when_coder_model_differs(self, tmp_path) -> None:
        """agent_meta.json reflects coder_model when it differs from planner model."""
        ctx = make_ctx(tmp_path, agent_model="gemini-3.1-pro-preview")
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        meta_updates: dict[str, str] = {}

        def track_meta(artifacts_dir, key, value):
            meta_updates[key] = value

        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            coder_model="gemini-3-flash-preview",
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
                "sase.axe.run_agent_exec_plan.update_meta_field",
                side_effect=track_meta,
            ),
            patch(
                "sase.llm_provider.registry.resolve_model_provider",
                return_value=("gemini", "gemini-3-flash-preview"),
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)
        assert meta_updates.get("model") == "gemini-3-flash-preview"
        assert meta_updates.get("llm_provider") == "gemini"

    @pytest.mark.parametrize(
        ("action", "commit_plan", "run_coder", "expected"),
        [
            ("approve", True, True, "tale"),
            ("approve", False, True, "approve"),
            ("approve", True, False, "commit"),
            ("approve", False, False, "commit"),
            ("epic", True, True, "epic"),
            ("legend", True, True, "legend"),
        ],
    )
    def test_accepted_plan_action_for_meta_matches_choice(
        self,
        action: str,
        commit_plan: bool,
        run_coder: bool,
        expected: str,
    ) -> None:
        """Runner-side meta value mirrors the TUI's choice inference."""
        result = PlanApprovalResult(
            action=action,
            plan_file="plan.md",
            commit_plan=commit_plan,
            run_coder=run_coder,
        )
        assert _accepted_plan_action_for_meta(result) == expected

    def test_tale_round_trips_through_response_json(self) -> None:
        """A tale approval persists as 'tale' after the TUI->runner JSON hop."""
        from sase.ace.tui.actions.agents._notification_modals import (
            _build_plan_approval_response,
        )
        from sase.ace.tui.modals.plan_approval_modal import (
            PlanApprovalResult as TuiPlanApprovalResult,
        )

        tui_result = TuiPlanApprovalResult(
            action="approve",
            commit_plan=True,
            run_coder=True,
            choice="tale",
        )
        wire = _build_plan_approval_response(tui_result)

        runner_result = PlanApprovalResult(
            action=str(wire["action"]),
            plan_file="plan.md",
            commit_plan=bool(wire["commit_plan"]),
            run_coder=bool(wire["run_coder"]),
        )
        assert _accepted_plan_action_for_meta(runner_result) == "tale"

    def test_coder_meta_not_updated_when_model_same(self, tmp_path) -> None:
        """agent_meta.json not updated when coder_model matches planner model."""
        ctx = make_ctx(tmp_path, agent_model="opus")
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        meta_updates: dict[str, str] = {}

        def track_meta(artifacts_dir, key, value):
            meta_updates[key] = value

        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            coder_model="opus",
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
                "sase.axe.run_agent_exec_plan.update_meta_field",
                side_effect=track_meta,
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)
        assert "model" not in meta_updates

    def test_coder_meta_resolves_worker_lane_when_no_picker_model(
        self, tmp_path
    ) -> None:
        """Without a picker model, agent_meta.json records the worker lane."""
        ctx = make_ctx(tmp_path, agent_model="opus")
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        meta_updates: dict[str, str] = {}

        def track_meta(artifacts_dir, key, value):
            meta_updates[key] = value

        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            coder_model=None,
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
                "sase.axe.run_agent_exec_plan.update_meta_field",
                side_effect=track_meta,
            ),
            patch(
                "sase.llm_provider.registry.resolve_model_provider",
                return_value=("workerprov", "worker-model"),
            ) as resolve_mock,
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)
        resolve_mock.assert_called_once_with("worker")
        assert meta_updates.get("model") == "worker-model"
        assert meta_updates.get("llm_provider") == "workerprov"
