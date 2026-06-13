"""Tests for approved plan follow-up metadata."""

from unittest.mock import patch

import pytest

from sase.axe.run_agent_exec_plan import handle_plan_marker
from sase.axe.run_agent_exec_plan_accept import _accepted_plan_action_for_meta
from sase.llm_provider import WorkerModelResolution
from sase.llm_provider._plan_utils import PlanApprovalResult
from sase.xprompt._exceptions import DirectiveError
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
                "sase.axe.run_agent_exec_plan_accept.update_meta_field",
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
                "sase.axe.run_agent_exec_plan_accept.update_meta_field",
                side_effect=track_meta,
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)
        assert "model" not in meta_updates

    def test_coder_meta_records_contextual_worker_lane_when_no_picker_model(
        self, tmp_path
    ) -> None:
        """Without a picker model, agent_meta.json records the contextual worker lane.

        The worker lane is resolved from the planner's concrete provider/model,
        so the recorded meta matches the concrete ``%model`` prefix the handoff
        generates rather than the bare worker alias.
        """
        ctx = make_ctx(tmp_path, agent_model="opus", agent_llm_provider="claude")
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        meta_updates: dict[str, str] = {}

        def track_meta(artifacts_dir, key, value):
            meta_updates[key] = value

        resolution = WorkerModelResolution(
            provider="codex",
            model="gpt-5.5",
            source="config",
            primary_provider="claude",
            primary_model="opus",
            matched_key="claude/opus",
            configured_target="codex/gpt-5.5",
        )
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
                "sase.axe.run_agent_exec_plan_accept.update_meta_field",
                side_effect=track_meta,
            ),
            patch(
                "sase.llm_provider.resolve_worker_provider_model_for_primary",
                return_value=resolution,
            ) as resolve_mock,
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)
        resolve_mock.assert_called_once_with("claude", "opus")
        assert meta_updates.get("model") == "gpt-5.5"
        assert meta_updates.get("llm_provider") == "codex"
        assert state.current_prompt.startswith("%model:codex/gpt-5.5\n")

    @pytest.mark.parametrize("action", ["epic", "legend"])
    def test_epic_legend_meta_records_contextual_worker_lane(
        self, tmp_path, action: str
    ) -> None:
        """Epic/legend follow-ups record the same contextual worker default."""
        ctx = make_ctx(tmp_path, agent_model="opus", agent_llm_provider="claude")
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        meta_updates: dict[str, str] = {}

        def track_meta(artifacts_dir, key, value):
            meta_updates[key] = value

        resolution = WorkerModelResolution(
            provider="codex",
            model="gpt-5.5",
            source="config",
            primary_provider="claude",
            primary_model="opus",
            matched_key="claude/opus",
            configured_target="codex/gpt-5.5",
        )
        approval = PlanApprovalResult(action=action, plan_file=plan_file)
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
                "sase.axe.run_agent_exec_plan_accept.update_meta_field",
                side_effect=track_meta,
            ),
            patch(
                "sase.llm_provider.resolve_worker_provider_model_for_primary",
                return_value=resolution,
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)
        assert meta_updates.get("model") == "gpt-5.5"
        assert meta_updates.get("llm_provider") == "codex"
        assert state.current_prompt.startswith("%model:codex/gpt-5.5\n")

    def test_coder_prompt_model_directive_updates_meta(self, tmp_path) -> None:
        """A custom prompt %model directive records the model that launch will use."""
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
            coder_prompt="%m:sonnet\nUse the reviewed plan.",
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
                "sase.axe.run_agent_exec_plan_accept.update_meta_field",
                side_effect=track_meta,
            ),
            # The custom prompt's %model directive supersedes the contextual
            # worker default, so the worker resolver must not influence meta.
            patch(
                "sase.llm_provider.resolve_worker_provider_model_for_primary",
                return_value=WorkerModelResolution(
                    provider="anthropic",
                    model="opus",
                    source="primary",
                    primary_provider="anthropic",
                    primary_model="opus",
                ),
            ),
            patch(
                "sase.llm_provider.registry.resolve_model_provider",
                return_value=("anthropic", "claude-sonnet-4-5"),
            ) as resolve_mock,
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        resolve_mock.assert_called_once_with("sonnet")
        assert meta_updates.get("model") == "claude-sonnet-4-5"
        assert meta_updates.get("llm_provider") == "anthropic"

    def test_coder_prompt_model_directive_parse_error_is_not_swallowed(
        self, tmp_path
    ) -> None:
        """Directive parse failures must not fall back to recording worker meta."""
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
            coder_prompt="%m:sonnet %group\nUse the reviewed plan.",
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
                "sase.axe.run_agent_exec_plan_accept.update_meta_field",
                side_effect=track_meta,
            ),
            patch(
                "sase.llm_provider.resolve_worker_provider_model_for_primary",
                return_value=WorkerModelResolution(
                    provider="anthropic",
                    model="opus",
                    source="primary",
                    primary_provider="anthropic",
                    primary_model="opus",
                ),
            ),
            patch(
                "sase.llm_provider.registry.resolve_model_provider",
                return_value=("workerprov", "worker-model"),
            ) as resolve_mock,
            pytest.raises(DirectiveError),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        resolve_mock.assert_not_called()
        assert "model" not in meta_updates
