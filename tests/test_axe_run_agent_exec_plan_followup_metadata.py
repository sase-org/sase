"""Tests for approved plan follow-up metadata."""

import json
from datetime import UTC, datetime
from unittest.mock import call, patch

import pytest

from sase.axe.run_agent_exec_plan import handle_plan_marker
from sase.axe import run_agent_exec_plan_accept as accept_mod
from sase.axe.run_agent_exec_plan_accept import _accepted_plan_action_for_meta
from sase.llm_provider._plan_utils import PlanApprovalResult
from sase.xprompt._exceptions import DirectiveError
from tests._axe_run_agent_exec_plan_helpers import (
    _non_handoff_plan_gate_creation,
    make_ctx,
    make_state,
    patch_plan_gate_shell_result,
    patched_plan_deps,
)
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN


@pytest.fixture
def patch_plan_deps():
    with patched_plan_deps() as mocks:
        yield mocks


@pytest.mark.usefixtures("patch_plan_deps")
class TestPlanFollowupMetadata:
    """Verify approved plan metadata and action inference."""

    def test_plan_marker_passes_planner_runtime_to_approval(self, tmp_path) -> None:
        """Planner runtime spans run start through plan submission."""
        ctx = make_ctx(tmp_path, agent_model="opus", agent_llm_provider="claude")
        run_started_at = "2026-06-17T17:55:28+00:00"
        ctx.agent_meta["run_started_at"] = run_started_at
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text(VALID_TALE_PLAN, encoding="utf-8")
        submitted_at = datetime(2026, 6, 17, 18, 0, 0, tzinfo=UTC)
        approval = PlanApprovalResult(action="approve", plan_file=plan_file)

        with (
            patch("sase.axe.run_agent_exec_plan.datetime") as datetime_mock,
            patch(
                "sase.axe.run_agent_exec_plan.format_agent_run_runtime",
                return_value="4m32s",
            ) as runtime_mock,
            patch(
                "sase.plan_shell.create_plan_gate_shell",
                return_value=_non_handoff_plan_gate_creation(),
            ) as gate_mock,
            patch(
                "sase.plan_shell.plan_result_from_gate_creation",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(tmp_path / "spec.md", tmp_path / "plan.md"),
            ),
        ):
            datetime_mock.now.return_value = submitted_at
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        runtime_mock.assert_called_once_with(
            launch_timestamp_suffix=ctx.artifacts_timestamp,
            run_started_at=run_started_at,
            completion_time=submitted_at,
        )
        assert gate_mock.call_args.kwargs["agent_runtime"] == "4m32s"
        assert gate_mock.call_args.kwargs["ctx"].vcs_tag == "#gh:sase "

    def test_coder_meta_updated_when_coder_model_differs(self, tmp_path) -> None:
        """agent_meta.json reflects coder_model when it differs from planner model."""
        ctx = make_ctx(tmp_path, agent_model="gemini-3.1-pro-preview")
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text(VALID_TALE_PLAN, encoding="utf-8")

        meta_updates: dict[str, str] = {}

        def track_meta(artifacts_dir, key, value):
            meta_updates[key] = value

        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            coder_model="gemini-3-flash-preview",
        )
        with (
            patch_plan_gate_shell_result(approval),
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
        (tmp_path / "plan.md").write_text(VALID_TALE_PLAN, encoding="utf-8")

        meta_updates: dict[str, str] = {}

        def track_meta(artifacts_dir, key, value):
            meta_updates[key] = value

        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            coder_model="opus",
        )
        with (
            patch_plan_gate_shell_result(approval),
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

    def test_coder_meta_records_resolved_size_alias_when_no_picker_model(
        self, tmp_path
    ) -> None:
        """Without a picker model, agent_meta.json records the resolved size alias.

        The coder follow-up emits ``%model:@small`` and the
        recorded meta resolves that alias to the concrete provider/model the
        launch will actually use, so display and behavior stay in sync.
        """
        ctx = make_ctx(tmp_path, agent_model="opus", agent_llm_provider="claude")
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text(VALID_TALE_PLAN, encoding="utf-8")

        meta_updates: dict[str, str] = {}

        def track_meta(artifacts_dir, key, value):
            meta_updates[key] = value

        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            coder_model=None,
        )
        with (
            patch_plan_gate_shell_result(approval),
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
                return_value=("codex", "gpt-5.6-sol"),
            ) as resolve_mock,
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)
        resolve_mock.assert_any_call("@small")
        assert meta_updates.get("model") == "gpt-5.6-sol"
        assert meta_updates.get("llm_provider") == "codex"
        assert state.current_prompt.startswith("%model:@small\n")

    def test_tale_size_followup_model_carries_alias_provenance(self, tmp_path) -> None:
        """A tale-size routed follow-up carries directive alias provenance."""
        ctx = make_ctx(tmp_path, agent_model="opus", agent_llm_provider="claude")
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text(VALID_TALE_PLAN, encoding="utf-8")
        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            coder_model=None,
        )

        with patch(
            "sase.llm_provider.registry.resolve_model_provider",
            return_value=("codex", "gpt-5.6-sol"),
        ):
            followup = accept_mod._resolve_followup_model(
                approval,
                ctx,
                followup_plan_file=plan_file,
            )

        assert followup.model_alias == "small"
        assert followup.model_alias_trail == ("small",)
        assert followup.model_alias_origin == "directive"

    def test_followup_model_meta_records_size_alias(self, tmp_path) -> None:
        """The metadata rewrite records the alias that produced the model."""
        state = make_state(tmp_path)
        followup_dir = tmp_path / "followup"
        followup_dir.mkdir()
        (followup_dir / "agent_meta.json").write_text(
            json.dumps(
                {
                    "model_alias": "planner_alias",
                    "model_alias_trail": ["planner_alias"],
                    "model_alias_origin": "directive",
                }
            ),
            encoding="utf-8",
        )
        state.current_artifacts_dir = str(followup_dir)

        def update_meta(artifacts_dir: str, key: str, value: object) -> None:
            meta_path = tmp_path / "followup" / "agent_meta.json"
            assert artifacts_dir == str(followup_dir)
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta[key] = value
            meta_path.write_text(json.dumps(meta), encoding="utf-8")

        with (
            patch.object(
                accept_mod,
                "update_agent_artifact_index_for_marker_mutation",
                lambda _path: None,
            ),
            patch.object(accept_mod, "update_meta_field", update_meta),
        ):
            accept_mod._write_followup_model_meta(
                state,
                accept_mod._FollowupModel(
                    model_prefix="%model:@small\n",
                    meta=("codex", "gpt-5.6-sol"),
                    model_alias="small",
                    model_alias_trail=("small",),
                    model_alias_origin="directive",
                ),
            )

        meta = json.loads((followup_dir / "agent_meta.json").read_text())
        assert meta["model_alias"] == "small"
        assert meta["model_alias_trail"] == ["small"]
        assert meta["model_alias_origin"] == "directive"

    def test_followup_model_meta_clears_alias_for_concrete_model(
        self, tmp_path
    ) -> None:
        """A concrete coder model must not inherit the planner's alias chip."""
        state = make_state(tmp_path)
        followup_dir = tmp_path / "followup"
        followup_dir.mkdir()
        (followup_dir / "agent_meta.json").write_text(
            json.dumps(
                {
                    "model_alias": "planner_alias",
                    "model_alias_trail": ["planner_alias"],
                    "model_alias_origin": "directive",
                }
            ),
            encoding="utf-8",
        )
        state.current_artifacts_dir = str(followup_dir)

        def update_meta(artifacts_dir: str, key: str, value: object) -> None:
            meta_path = tmp_path / "followup" / "agent_meta.json"
            assert artifacts_dir == str(followup_dir)
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta[key] = value
            meta_path.write_text(json.dumps(meta), encoding="utf-8")

        with (
            patch.object(
                accept_mod,
                "update_agent_artifact_index_for_marker_mutation",
                lambda _path: None,
            ),
            patch.object(accept_mod, "update_meta_field", update_meta),
        ):
            accept_mod._write_followup_model_meta(
                state,
                accept_mod._FollowupModel(
                    model_prefix="%model:claude/opus\n",
                    meta=("claude", "opus"),
                    model_alias_origin="none",
                ),
            )

        meta = json.loads((followup_dir / "agent_meta.json").read_text())
        assert "model_alias" not in meta
        assert "model_alias_trail" not in meta
        assert "model_alias_origin" not in meta

    def test_epic_meta_is_left_to_host_without_creator_model(self, tmp_path) -> None:
        """The agent leaves launch metadata to the detached host task."""
        ctx = make_ctx(tmp_path, agent_model="opus", agent_llm_provider="claude")
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text(VALID_EPIC_PLAN)

        meta_updates: dict[str, str] = {}

        def track_meta(artifacts_dir, key, value):
            meta_updates[key] = value

        approval = PlanApprovalResult(action="epic", plan_file=plan_file)
        with (
            patch_plan_gate_shell_result(approval),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(tmp_path / "spec.md", tmp_path / "plan.md"),
            ),
            patch(
                "sase.axe.run_agent_exec_plan_accept.update_meta_field",
                side_effect=track_meta,
            ),
            patch("sase.llm_provider.registry.resolve_model_provider") as resolve,
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)
        assert "model" not in meta_updates
        assert "llm_provider" not in meta_updates
        assert "epic_bead_id" not in meta_updates
        assert state.current_prompt == "original prompt"
        resolve.assert_not_called()

    def test_coder_prompt_model_directive_updates_meta(self, tmp_path) -> None:
        """A custom prompt %model directive records the model that launch will use."""
        ctx = make_ctx(tmp_path, agent_model="opus")
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text(VALID_TALE_PLAN, encoding="utf-8")

        meta_updates: dict[str, str] = {}

        def track_meta(artifacts_dir, key, value):
            meta_updates[key] = value

        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            coder_prompt="%m:sonnet\nUse the reviewed plan.",
        )

        def fake_resolve(directive):
            # The custom prompt's %model directive supersedes the size-alias
            # default, so its model is what gets recorded.
            if directive == "sonnet":
                return ("anthropic", "claude-sonnet-4-5")
            return ("codex", "gpt-5.6-sol")

        with (
            patch_plan_gate_shell_result(approval),
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
                side_effect=fake_resolve,
            ) as resolve_mock,
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        resolve_mock.assert_any_call("sonnet")
        assert meta_updates.get("model") == "claude-sonnet-4-5"
        assert meta_updates.get("llm_provider") == "anthropic"

    def test_coder_prompt_model_directive_parse_error_is_not_swallowed(
        self, tmp_path
    ) -> None:
        """Directive parse failures must not fall back to recording worker meta."""
        ctx = make_ctx(tmp_path, agent_model="opus")
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text(VALID_TALE_PLAN, encoding="utf-8")

        meta_updates: dict[str, str] = {}

        def track_meta(artifacts_dir, key, value):
            meta_updates[key] = value

        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            coder_prompt="%m:sonnet %tribe\nUse the reviewed plan.",
        )
        with (
            patch_plan_gate_shell_result(approval),
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
                return_value=("workerprov", "worker-model"),
            ) as resolve_mock,
            pytest.raises(DirectiveError),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        # The broken directive's model must never be resolved or recorded.
        assert call("sonnet") not in resolve_mock.call_args_list
        assert "model" not in meta_updates
