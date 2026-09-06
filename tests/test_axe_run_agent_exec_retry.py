"""Tests for run_agent_exec_retry continuation-nudge behavior."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.axe.run_agent_exec import LoopState
from sase.axe.run_agent_exec_retry import (
    RetryTracker,
    _maybe_prepend_continuation,
    handle_workflow_error,
)
from sase.llm_provider.retry_config import (
    ProviderRetryConfig,
    RetryState,
    get_retry_config,
)
from tests._axe_run_agent_exec_retry_helpers import (
    _restore_model_override_env,  # noqa: F401 (registers the autouse fixture)
    config_with_nudge,
    make_ctx,
    make_ctx_with_update_target,
    make_state,
)

_CODEX_TRANSIENT_FAILURE = (
    "ERROR codex_api::endpoint::responses_websocket: failed to connect to "
    "websocket: HTTP error: 403 Forbidden, "
    "url: wss://chatgpt.com/backend-api/codex/responses Reconnecting 5/5\n"
    "[turn.failed] exceeded retry limit, last status: 429 Too Many Requests"
)

_CODEX_INPUT_TOO_LARGE_FAILURE = (
    "[turn.failed] turn/start failed: JSON-RPC error -32602: "
    "input validation failed; input_error_code=input_too_large; "
    "max_chars=1048576; actual_chars=1913445; "
    "warning: stale rollout path /tmp/codex-rollout"
)


class TestMaybePrependContinuation:
    def test_prepends_nudge_when_set(self) -> None:
        state = make_state("Original prompt body.")
        cfg = config_with_nudge("NUDGE")
        _maybe_prepend_continuation(state, cfg)
        assert state.current_prompt == "NUDGE\n\nOriginal prompt body."

    def test_noop_when_nudge_is_none(self) -> None:
        state = make_state("Original prompt body.")
        cfg = config_with_nudge(None)
        _maybe_prepend_continuation(state, cfg)
        assert state.current_prompt == "Original prompt body."

    def test_noop_when_nudge_is_empty_string(self) -> None:
        state = make_state("Original prompt body.")
        cfg = config_with_nudge("")
        _maybe_prepend_continuation(state, cfg)
        assert state.current_prompt == "Original prompt body."

    def test_idempotent_when_already_prepended(self) -> None:
        state = make_state("NUDGE\n\nOriginal prompt body.")
        cfg = config_with_nudge("NUDGE")
        _maybe_prepend_continuation(state, cfg)
        _maybe_prepend_continuation(state, cfg)
        assert state.current_prompt == "NUDGE\n\nOriginal prompt body."

    def test_noop_when_prompt_is_empty(self) -> None:
        state = make_state("")
        cfg = config_with_nudge("NUDGE")
        _maybe_prepend_continuation(state, cfg)
        assert state.current_prompt == ""


class TestHandleWorkflowErrorContinuation:
    def test_prepends_nudge_on_retry(self, tmp_path: Path) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state("Do the work.")
        tracker = RetryTracker(retry_cfg=config_with_nudge("NUDGE", max_retries=2))

        with (
            patch(
                "sase.axe.run_agent_exec_retry.time.sleep",
                MagicMock(),
            ),
            patch(
                "sase.axe.run_agent_exec_retry.was_killed",
                return_value=False,
            ),
            patch(
                "sase.axe.run_agent_exec_retry.prepare_workspace",
                MagicMock(),
            ),
            patch("sase.linked_repos.clear_workspace_repos") as clear_repos,
        ):
            action = handle_workflow_error(
                RuntimeError("API Error: 400 - Prompt is too long"),
                tracker,
                ctx,
                state,
            )

        assert action == "continue"
        clear_repos.assert_not_called()
        assert state.current_prompt.startswith("NUDGE\n\n")
        assert "Do the work." in state.current_prompt

    def test_does_not_double_prepend_on_repeated_retries(self, tmp_path: Path) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state("Do the work.")
        tracker = RetryTracker(retry_cfg=config_with_nudge("NUDGE", max_retries=3))

        with (
            patch(
                "sase.axe.run_agent_exec_retry.time.sleep",
                MagicMock(),
            ),
            patch(
                "sase.axe.run_agent_exec_retry.was_killed",
                return_value=False,
            ),
            patch(
                "sase.axe.run_agent_exec_retry.prepare_workspace",
                MagicMock(),
            ),
        ):
            handle_workflow_error(
                RuntimeError("Prompt is too long"), tracker, ctx, state
            )
            first_prompt = state.current_prompt
            handle_workflow_error(
                RuntimeError("Prompt is too long"), tracker, ctx, state
            )

        assert state.current_prompt == first_prompt
        assert state.current_prompt.count("NUDGE") == 1

    def test_raises_after_max_retries_exhausted(self, tmp_path: Path) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state("Do the work.")
        tracker = RetryTracker(
            retry_cfg=config_with_nudge("NUDGE", max_retries=1),
            retry_count=1,
        )

        with (
            patch(
                "sase.axe.run_agent_exec_retry.time.sleep",
                MagicMock(),
            ),
            patch(
                "sase.axe.run_agent_exec_retry.was_killed",
                return_value=False,
            ),
            patch(
                "sase.axe.run_agent_exec_retry.prepare_workspace",
                MagicMock(),
            ),
        ):
            action = handle_workflow_error(
                RuntimeError("Prompt is too long"), tracker, ctx, state
            )

        assert action == "raise"

    def test_prepends_nudge_on_zero_wait_retry(self, tmp_path: Path) -> None:
        """Built-in default wait=0 still injects nudge and writes retry state."""
        ctx = make_ctx_with_update_target(tmp_path)
        state = make_state("Do the work.")
        # Use the built-in claude config, forcing a fresh load of the
        # built-in (no user config).
        with patch(
            "sase.llm_provider.retry_config.load_merged_config",
            return_value={},
        ):
            retry_cfg = get_retry_config("claude")
        assert retry_cfg is not None
        tracker = RetryTracker(retry_cfg=retry_cfg)

        with (
            patch("sase.axe.run_agent_exec_retry.time.sleep", MagicMock()),
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
            patch(
                "sase.axe.run_agent_exec_retry.prepare_workspace",
                MagicMock(),
            ) as mock_prepare,
        ):
            action = handle_workflow_error(
                RuntimeError("API Error: 400 - Prompt is too long"),
                tracker,
                ctx,
                state,
            )

        assert action == "continue"
        assert "context limit" in state.current_prompt
        assert "transient provider failure" in state.current_prompt
        assert "Do the work." in state.current_prompt
        # retry_state.json should have been written during the retry cycle.
        assert (tmp_path / "artifacts" / "retry_state.json").exists()
        # Built-in claude config has preserve_workspace=True, so the coder's
        # on-disk edits must not be wiped.
        mock_prepare.assert_not_called()


class TestHandleWorkflowErrorNoNudge:
    """A retry config without a continuation_prompt leaves the prompt alone."""

    def test_no_nudge_leaves_prompt_untouched(self, tmp_path: Path) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state("Original prompt.")
        cfg = ProviderRetryConfig(
            max_retries=2,
            error_patterns=["rate limit"],
            wait_times=[0],
        )
        tracker = RetryTracker(retry_cfg=cfg)

        with (
            patch("sase.axe.run_agent_exec_retry.time.sleep", MagicMock()),
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
            patch(
                "sase.axe.run_agent_exec_retry.prepare_workspace",
                MagicMock(),
            ),
        ):
            action = handle_workflow_error(
                RuntimeError("hit a rate limit"), tracker, ctx, state
            )

        assert action == "continue"
        assert state.current_prompt == "Original prompt."


class TestHandleWorkflowErrorCodexDefaults:
    def test_codex_input_too_large_failure_does_not_retry(self, tmp_path: Path) -> None:
        ctx = replace(make_ctx_with_update_target(tmp_path), agent_llm_provider="codex")
        state = make_state("Do the work.")
        tracker = RetryTracker(retry_cfg=None, execution_provider="codex")

        with (
            patch(
                "sase.llm_provider.retry_config.load_merged_config",
                return_value={},
            ),
            patch("sase.axe.run_agent_exec_retry.time.sleep") as sleep,
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
            patch(
                "sase.axe.run_agent_exec_retry.prepare_workspace",
                MagicMock(),
            ) as prepare,
        ):
            action = handle_workflow_error(
                RuntimeError(_CODEX_INPUT_TOO_LARGE_FAILURE),
                tracker,
                ctx,
                state,
            )

        assert action == "raise"
        assert tracker.retry_count == 0
        assert RetryState.read_from(ctx.artifacts_dir) is None
        sleep.assert_not_called()
        prepare.assert_not_called()

    def test_codex_transient_default_retries_with_preserved_workspace(
        self, tmp_path: Path
    ) -> None:
        ctx = replace(make_ctx_with_update_target(tmp_path), agent_llm_provider="codex")
        state = make_state("Do the work.")
        with patch(
            "sase.llm_provider.retry_config.load_merged_config",
            return_value={},
        ):
            retry_cfg = get_retry_config("codex")
        assert retry_cfg is not None
        tracker = RetryTracker(retry_cfg=retry_cfg, execution_provider="codex")

        with (
            patch("sase.axe.run_agent_exec_retry.time.sleep") as sleep,
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
            patch(
                "sase.axe.run_agent_exec_retry.prepare_workspace",
                MagicMock(),
            ) as prepare,
        ):
            action = handle_workflow_error(
                RuntimeError(_CODEX_TRANSIENT_FAILURE),
                tracker,
                ctx,
                state,
            )

        retry_state = RetryState.read_from(ctx.artifacts_dir)
        assert action == "continue"
        assert tracker.retry_count == 1
        assert retry_state is not None
        assert retry_state.status == "running_retry"
        assert retry_state.retry_count == 1
        assert "transient provider failure" in state.current_prompt
        assert "Do the work." in state.current_prompt
        assert sleep.call_count == 60
        prepare.assert_not_called()


class TestHandleWorkflowErrorSpawnNewAgent:
    def test_spawn_new_agent_retry_uses_fresh_shell_when_opted_in(
        self, tmp_path: Path
    ) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state("Do the work.")
        cfg = ProviderRetryConfig(
            max_retries=2,
            error_patterns=["transient provider failure"],
            wait_times=[0],
            continuation_prompt="NUDGE",
            preserve_workspace=True,
            spawn_new_agent=True,
        )
        tracker = RetryTracker(retry_cfg=cfg, execution_provider="codex")
        spawn_result = {
            "child_artifacts_timestamp": "20260906010101",
            "chain_root_timestamp": "20260906000000",
            "handoff_path": str(tmp_path / "retry_handoff.json"),
            "error_category": "transient_provider_failure",
        }

        with (
            patch("sase.axe.run_agent_exec_retry.time.sleep", MagicMock()),
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
            patch(
                "sase.axe.run_agent_retry_spawn.spawn_retry_agent",
                return_value=spawn_result,
            ) as spawn,
            patch("sase.axe.run_agent_retry_spawn.mark_parent_retried") as mark_parent,
            patch(
                "sase.axe.run_agent_exec_retry.prepare_workspace",
                MagicMock(),
            ) as prepare,
        ):
            action = handle_workflow_error(
                RuntimeError("transient provider failure"),
                tracker,
                ctx,
                state,
            )

        assert action == "break"
        assert tracker.retry_count == 1
        assert state.loop_outcome == "failed_retried"
        spawn.assert_called_once()
        mark_parent.assert_called_once()
        prepare.assert_not_called()


class TestHandleWorkflowErrorPostPhaseTransition:
    """Retries must fire after the plan has been approved / questions answered."""

    def test_retry_fires_for_coder_after_plan_approval(self, tmp_path: Path) -> None:
        """A coder-shaped LoopState (agent_step=2, .code suffix) still retries."""
        ctx = make_ctx(tmp_path)
        state = LoopState(
            current_prompt="@/tmp/plan.md\n\nThe above plan has been reviewed...",
            current_role_suffix=".code",
            current_artifacts_dir=str(tmp_path / "artifacts"),
            loop_outcome="completed",
            sdd_spec_path=None,
            original_prompt="Implement feature X.",
            agent_step=2,
        )
        tracker = RetryTracker(retry_cfg=config_with_nudge("NUDGE", max_retries=2))

        with (
            patch("sase.axe.run_agent_exec_retry.time.sleep", MagicMock()),
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
            patch(
                "sase.axe.run_agent_exec_retry.prepare_workspace",
                MagicMock(),
            ),
        ):
            action = handle_workflow_error(
                RuntimeError("Step 'main' failed: ... Prompt is too long"),
                tracker,
                ctx,
                state,
            )

        assert action == "continue"
        assert state.current_prompt.startswith("NUDGE\n\n")
        assert tracker.retry_count == 1
