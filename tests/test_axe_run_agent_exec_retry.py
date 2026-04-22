"""Tests for run_agent_exec_retry.handle_workflow_error and helpers."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.axe.run_agent_exec import AgentExecContext, LoopState
from sase.axe.run_agent_exec_retry import (
    RetryTracker,
    _maybe_prepend_continuation,
    handle_workflow_error,
)
from sase.llm_provider.retry_config import ProviderRetryConfig


def _make_ctx(tmp_path: Path) -> AgentExecContext:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    return AgentExecContext(
        cl_name="test-cl",
        project_file=str(tmp_path / "project.gp"),
        workspace_dir=str(tmp_path),
        output_path=str(tmp_path / "output.log"),
        workspace_num=1,
        timestamp="20260421_120000",
        update_target="",
        project_name="sase",
        is_home_mode=False,
        artifacts_dir=str(artifacts),
        artifacts_timestamp="20260421_120000",
        vcs_tag=None,
        agent_name="agent",
        agent_model=None,
        agent_llm_provider="claude",
        agent_vcs_provider=None,
        agent_hidden=False,
        agent_meta={},
        local_xprompts={},
    )


def _make_state(prompt: str = "Do the work.") -> LoopState:
    return LoopState(
        current_prompt=prompt,
        current_role_suffix="",
        current_artifacts_dir="",
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt=prompt,
    )


def _config_with_nudge(
    nudge: str | None = "CONTINUATION NUDGE",
    max_retries: int = 2,
) -> ProviderRetryConfig:
    return ProviderRetryConfig(
        max_retries=max_retries,
        error_patterns=["Prompt is too long"],
        wait_times=[0],
        continuation_prompt=nudge,
    )


class TestMaybePrependContinuation:
    def test_prepends_nudge_when_set(self) -> None:
        state = _make_state("Original prompt body.")
        cfg = _config_with_nudge("NUDGE")
        _maybe_prepend_continuation(state, cfg)
        assert state.current_prompt == "NUDGE\n\nOriginal prompt body."

    def test_noop_when_nudge_is_none(self) -> None:
        state = _make_state("Original prompt body.")
        cfg = _config_with_nudge(None)
        _maybe_prepend_continuation(state, cfg)
        assert state.current_prompt == "Original prompt body."

    def test_noop_when_nudge_is_empty_string(self) -> None:
        state = _make_state("Original prompt body.")
        cfg = _config_with_nudge("")
        _maybe_prepend_continuation(state, cfg)
        assert state.current_prompt == "Original prompt body."

    def test_idempotent_when_already_prepended(self) -> None:
        state = _make_state("NUDGE\n\nOriginal prompt body.")
        cfg = _config_with_nudge("NUDGE")
        _maybe_prepend_continuation(state, cfg)
        _maybe_prepend_continuation(state, cfg)
        assert state.current_prompt == "NUDGE\n\nOriginal prompt body."

    def test_noop_when_prompt_is_empty(self) -> None:
        state = _make_state("")
        cfg = _config_with_nudge("NUDGE")
        _maybe_prepend_continuation(state, cfg)
        assert state.current_prompt == ""


class TestHandleWorkflowErrorContinuation:
    def test_prepends_nudge_on_retry(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path)
        state = _make_state("Do the work.")
        tracker = RetryTracker(retry_cfg=_config_with_nudge("NUDGE", max_retries=2))

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
                RuntimeError("API Error: 400 - Prompt is too long"),
                tracker,
                ctx,
                state,
            )

        assert action == "continue"
        assert state.current_prompt.startswith("NUDGE\n\n")
        assert "Do the work." in state.current_prompt

    def test_does_not_double_prepend_on_repeated_retries(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path)
        state = _make_state("Do the work.")
        tracker = RetryTracker(retry_cfg=_config_with_nudge("NUDGE", max_retries=3))

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
        ctx = _make_ctx(tmp_path)
        state = _make_state("Do the work.")
        tracker = RetryTracker(
            retry_cfg=_config_with_nudge("NUDGE", max_retries=1),
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
        import dataclasses

        ctx = dataclasses.replace(_make_ctx(tmp_path), update_target="origin/master")
        state = _make_state("Do the work.")
        # Use the built-in claude config
        from sase.llm_provider.retry_config import get_retry_config

        # Force a fresh load of built-in (no user config)
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
        assert "context window" in state.current_prompt
        assert "Do the work." in state.current_prompt
        # retry_state.json should have been written during the retry cycle.
        assert (tmp_path / "artifacts" / "retry_state.json").exists()
        # Built-in claude config has preserve_workspace=True, so the coder's
        # on-disk edits must not be wiped.
        mock_prepare.assert_not_called()


class TestHandleWorkflowErrorNoNudge:
    """A retry config without a continuation_prompt leaves the prompt alone."""

    def test_no_nudge_leaves_prompt_untouched(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path)
        state = _make_state("Original prompt.")
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


class TestHandleWorkflowErrorPostPhaseTransition:
    """Retries must fire after the plan has been approved / questions answered."""

    def test_retry_fires_for_coder_after_plan_approval(self, tmp_path: Path) -> None:
        """A coder-shaped LoopState (agent_step=2, .code suffix) still retries."""
        ctx = _make_ctx(tmp_path)
        state = LoopState(
            current_prompt="@/tmp/plan.md\n\nThe above plan has been reviewed...",
            current_role_suffix=".code",
            current_artifacts_dir=str(tmp_path / "artifacts"),
            loop_outcome="completed",
            sdd_spec_path=None,
            original_prompt="Implement feature X.",
            agent_step=2,
        )
        tracker = RetryTracker(retry_cfg=_config_with_nudge("NUDGE", max_retries=2))

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


def _make_ctx_with_update_target(tmp_path: Path) -> AgentExecContext:
    """ctx with update_target set so prepare_workspace is eligible to fire."""
    import dataclasses

    return dataclasses.replace(_make_ctx(tmp_path), update_target="origin/master")


def _preserve_cfg(max_retries: int = 2) -> ProviderRetryConfig:
    return ProviderRetryConfig(
        max_retries=max_retries,
        error_patterns=["Prompt is too long"],
        wait_times=[0],
        continuation_prompt="NUDGE",
        preserve_workspace=True,
    )


def _fallback_preserve_cfg() -> ProviderRetryConfig:
    return ProviderRetryConfig(
        max_retries=0,
        error_patterns=["Prompt is too long"],
        wait_times=[0],
        fallback_model="backup-model",
        preserve_workspace=True,
    )


class TestHandleWorkflowErrorPreserveWorkspace:
    """preserve_workspace gates the in-loop prepare_workspace call."""

    def test_preserve_workspace_skips_prepare_on_retry(self, tmp_path: Path) -> None:
        ctx = _make_ctx_with_update_target(tmp_path)
        state = _make_state("Do the work.")
        tracker = RetryTracker(retry_cfg=_preserve_cfg())

        with (
            patch("sase.axe.run_agent_exec_retry.time.sleep", MagicMock()),
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
            patch(
                "sase.axe.run_agent_exec_retry.prepare_workspace",
                MagicMock(),
            ) as mock_prepare,
        ):
            action = handle_workflow_error(
                RuntimeError("Prompt is too long"), tracker, ctx, state
            )

        assert action == "continue"
        mock_prepare.assert_not_called()

    def test_preserve_workspace_skips_prepare_on_fallback(self, tmp_path: Path) -> None:
        ctx = _make_ctx_with_update_target(tmp_path)
        state = _make_state("Do the work.")
        # max_retries=0 means we skip the retry branch and go to fallback.
        tracker = RetryTracker(retry_cfg=_fallback_preserve_cfg())

        with (
            patch("sase.axe.run_agent_exec_retry.time.sleep", MagicMock()),
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
            patch(
                "sase.axe.run_agent_exec_retry.prepare_workspace",
                MagicMock(),
            ) as mock_prepare,
        ):
            action = handle_workflow_error(
                RuntimeError("Prompt is too long"), tracker, ctx, state
            )

        assert action == "continue"
        assert tracker.using_fallback is True
        mock_prepare.assert_not_called()

    def test_default_preserve_workspace_false_still_calls_prepare(
        self, tmp_path: Path
    ) -> None:
        """Rate-limit retries (preserve_workspace=False default) still wipe — no regression."""
        ctx = _make_ctx_with_update_target(tmp_path)
        state = _make_state("Do the work.")
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
            ) as mock_prepare,
        ):
            action = handle_workflow_error(
                RuntimeError("hit a rate limit"), tracker, ctx, state
            )

        assert action == "continue"
        mock_prepare.assert_called_once()
