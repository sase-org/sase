"""Tests for run_agent_exec_retry.handle_workflow_error and helpers."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.ace.tui.models.agent_attempt import load_attempt_history
from sase.axe.run_agent_exec import AgentExecContext, LoopState
from sase.axe.run_agent_exec_retry import (
    RetryTracker,
    _detect_usage_limit_for_error,
    _maybe_prepend_continuation,
    handle_workflow_error,
)
from sase.llm_provider.retry_config import ProviderRetryConfig, get_retry_config

_CLAUDE_WEEKLY_LIMIT = "You've hit your weekly limit · resets 8pm (America/New_York)"


@pytest.fixture(autouse=True)
def _restore_model_override_env():
    original = os.environ.get("SASE_MODEL_OVERRIDE")
    yield
    if original is None:
        os.environ.pop("SASE_MODEL_OVERRIDE", None)
    else:
        os.environ["SASE_MODEL_OVERRIDE"] = original


def _make_ctx(tmp_path: Path) -> AgentExecContext:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    return AgentExecContext(
        cl_name="test-cl",
        project_file=str(tmp_path / "project.sase"),
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

        try:
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
        finally:
            os.environ.pop("SASE_MODEL_OVERRIDE", None)

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


class TestHandleWorkflowErrorOccupancyGuard:
    """A retry re-prep must refuse rather than clobber a live occupant."""

    def test_refuses_when_workspace_is_occupied_by_another_live_agent(
        self, tmp_path: Path
    ) -> None:
        import dataclasses
        import tempfile

        from sase.core.occupancy_guard import WorkspaceOccupiedError
        from sase.running_field import WorkspaceClaim
        from sase.workspace_provider.occupant import (
            new_occupant_record,
            write_occupant_record,
        )

        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        other_pid = os.getppid()
        with tempfile.NamedTemporaryFile(
            dir=tmp_path, mode="w", delete=False, suffix=".sase"
        ) as f:
            f.write("# Test Project\n\nRUNNING:\n")
            f.write(
                WorkspaceClaim(
                    workspace_num=7,
                    workflow="ace(run)-other",
                    cl_name="test-cl",
                    pid=other_pid,
                    artifacts_timestamp="ts",
                ).to_line()
                + "\n"
            )
            f.write("NAME: Test Feature\nDESCRIPTION:\n  Test\nSTATUS: Ready\n")
            project_file = f.name
        write_occupant_record(
            str(workspace_dir),
            new_occupant_record(
                pid=other_pid,
                workflow="ace(run)-other",
                project="sase",
                workspace_num=7,
                agent_name="rival-agent",
            ),
        )

        ctx = dataclasses.replace(
            _make_ctx_with_update_target(tmp_path),
            workspace_dir=str(workspace_dir),
            workspace_num=7,
            project_file=project_file,
            workflow_name="ace(run)-mine",
        )
        state = _make_state("Do the work.")
        tracker = RetryTracker(
            retry_cfg=ProviderRetryConfig(
                max_retries=2,
                error_patterns=["rate limit"],
                wait_times=[0],
            )
        )

        with (
            patch("sase.axe.run_agent_exec_retry.time.sleep", MagicMock()),
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
            patch(
                "sase.axe.run_agent_exec_retry.prepare_workspace",
                MagicMock(),
            ) as mock_prepare,
            pytest.raises(WorkspaceOccupiedError, match="rival-agent"),
        ):
            handle_workflow_error(RuntimeError("hit a rate limit"), tracker, ctx, state)

        mock_prepare.assert_not_called()


class TestHandleWorkflowErrorUsageLimitPrecedence:
    """A usage-limit failure takes precedence over ordinary retry classification.

    Regression coverage for the epic sase-n4 bug: codex's built-in retry
    patterns include "rate limit" and "429 Too Many Requests", so without
    this precedence check a usage-limit failure gets misclassified as
    retryable and sleeps through wait_times = [60, 300, 1800] instead of
    failing fast.
    """

    def test_codex_usage_limit_error_does_not_consume_wait_times(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path))
        ctx = _make_ctx(tmp_path)
        state = _make_state("Do the work.")

        with patch(
            "sase.llm_provider.retry_config.load_merged_config", return_value={}
        ):
            retry_cfg = get_retry_config("codex")
        assert retry_cfg is not None
        tracker = RetryTracker(retry_cfg=retry_cfg, execution_provider="codex")

        # Overlaps both codex's retry pattern ("429 Too Many Requests") and
        # its usage-limit pattern ("you've hit your usage limit") — exactly
        # the ambiguous case the precedence check must resolve correctly.
        error_text = (
            "Error: 429 Too Many Requests. You've hit your usage limit. "
            "Upgrade to Pro (https://chatgpt.com/explore/pro)."
        )

        with (
            patch(
                "sase.llm_provider.usage_limit_config.load_merged_config",
                return_value={},
            ),
            patch(
                "sase.axe.run_agent_exec_retry.time.sleep", MagicMock()
            ) as mock_sleep,
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
        ):
            action = handle_workflow_error(
                RuntimeError(error_text), tracker, ctx, state
            )

        assert action == "raise"
        assert tracker.retry_count == 0
        mock_sleep.assert_not_called()

        attempts = load_attempt_history(str(tmp_path / "artifacts"))
        assert len(attempts) == 1
        assert attempts[0].status == "raised"
        assert attempts[0].reason is not None
        assert "usage limit" in attempts[0].reason

    def test_transient_429_not_a_usage_limit_match_still_retries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression guard for the pattern-overlap hazard: a plain 429 with
        no usage-limit prose must retry exactly as it does today."""
        monkeypatch.setenv("SASE_HOME", str(tmp_path))
        ctx = _make_ctx(tmp_path)
        state = _make_state("Do the work.")

        with patch(
            "sase.llm_provider.retry_config.load_merged_config", return_value={}
        ):
            retry_cfg = get_retry_config("codex")
        assert retry_cfg is not None
        tracker = RetryTracker(retry_cfg=retry_cfg, execution_provider="codex")

        with (
            patch(
                "sase.llm_provider.usage_limit_config.load_merged_config",
                return_value={},
            ),
            patch("sase.axe.run_agent_exec_retry.time.sleep", MagicMock()),
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
            patch("sase.axe.run_agent_exec_retry.prepare_workspace", MagicMock()),
        ):
            action = handle_workflow_error(
                RuntimeError("Error: 429 Too Many Requests"), tracker, ctx, state
            )

        assert action == "continue"
        assert tracker.retry_count == 1

    def test_fallback_allowed_to_different_non_disabled_provider(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path))
        ctx = _make_ctx(tmp_path)
        state = _make_state("Do the work.")
        cfg = ProviderRetryConfig(
            max_retries=0,
            error_patterns=["usage limit"],
            fallback_model="claude/opus",
        )
        tracker = RetryTracker(retry_cfg=cfg, execution_provider="codex")
        error_text = "You've hit your usage limit. Upgrade to Pro (...)"

        with (
            patch(
                "sase.llm_provider.usage_limit_config.load_merged_config",
                return_value={},
            ),
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
        ):
            action = handle_workflow_error(
                RuntimeError(error_text), tracker, ctx, state
            )

        assert action == "continue"
        assert tracker.using_fallback is True
        assert os.environ["SASE_MODEL_OVERRIDE"] == "claude/opus"

    def test_fallback_skipped_when_it_resolves_to_the_same_disabled_provider(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path))
        ctx = _make_ctx(tmp_path)
        state = _make_state("Do the work.")
        cfg = ProviderRetryConfig(
            max_retries=0,
            error_patterns=["usage limit"],
            fallback_model="codex/gpt-5",
        )
        tracker = RetryTracker(retry_cfg=cfg, execution_provider="codex")
        error_text = "You've hit your usage limit. Upgrade to Pro (...)"

        with (
            patch(
                "sase.llm_provider.usage_limit_config.load_merged_config",
                return_value={},
            ),
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
        ):
            action = handle_workflow_error(
                RuntimeError(error_text), tracker, ctx, state
            )

        assert action == "raise"
        assert tracker.using_fallback is False

        attempts = load_attempt_history(str(tmp_path / "artifacts"))
        assert attempts[-1].status == "raised"
        assert attempts[-1].reason is not None

    def test_known_codex_attempt_does_not_scan_quoted_claude_limit_prose(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path))
        ctx = _make_ctx(tmp_path)
        state = _make_state("Do the work.")

        with patch(
            "sase.llm_provider.retry_config.load_merged_config", return_value={}
        ):
            retry_cfg = get_retry_config("codex")
        assert retry_cfg is not None
        tracker = RetryTracker(retry_cfg=retry_cfg, execution_provider="codex")
        error_text = (
            "Error: 429 Too Many Requests. Quoted Claude output: "
            f"{_CLAUDE_WEEKLY_LIMIT}"
        )

        with (
            patch(
                "sase.llm_provider.usage_limit_config.load_merged_config",
                return_value={},
            ),
            patch(
                "sase.axe.run_agent_exec_retry.time.sleep", MagicMock()
            ) as mock_sleep,
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
            patch("sase.axe.run_agent_exec_retry.prepare_workspace", MagicMock()),
        ):
            action = handle_workflow_error(
                RuntimeError(error_text), tracker, ctx, state
            )

        assert action == "continue"
        assert tracker.retry_count == 1
        mock_sleep.assert_called()

    def test_fallback_attempt_uses_recorded_exec_llm_provider(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path))
        ctx = _make_ctx(tmp_path)
        state = _make_state("Do the work.")
        (Path(ctx.artifacts_dir) / "agent_meta.json").write_text(
            json.dumps({"exec_llm_provider": "claude"}),
            encoding="utf-8",
        )
        cfg = ProviderRetryConfig(
            max_retries=2,
            error_patterns=["weekly limit", "429"],
            wait_times=[60],
        )
        tracker = RetryTracker(
            retry_cfg=cfg,
            execution_provider="codex",
            using_fallback=True,
        )

        with (
            patch(
                "sase.llm_provider.usage_limit_config.load_merged_config",
                return_value={},
            ),
            patch(
                "sase.axe.run_agent_exec_retry.time.sleep", MagicMock()
            ) as mock_sleep,
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
        ):
            action = handle_workflow_error(
                RuntimeError(_CLAUDE_WEEKLY_LIMIT), tracker, ctx, state
            )

        assert action == "raise"
        assert tracker.execution_provider == "claude"
        assert tracker.retry_count == 0
        mock_sleep.assert_not_called()
        attempts = load_attempt_history(str(tmp_path / "artifacts"))
        assert attempts[-1].status == "raised"
        assert attempts[-1].reason is not None
        assert "claude" in attempts[-1].reason

    def test_unknown_execution_provider_still_scans_other_configs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path))
        ctx = _make_ctx(tmp_path)
        state = _make_state("Do the work.")
        cfg = ProviderRetryConfig(
            max_retries=2,
            error_patterns=["weekly limit"],
            wait_times=[60],
        )
        tracker = RetryTracker(retry_cfg=cfg, execution_provider=None)

        with (
            patch(
                "sase.llm_provider.usage_limit_config.load_merged_config",
                return_value={},
            ),
            patch(
                "sase.axe.run_agent_exec_retry.time.sleep", MagicMock()
            ) as mock_sleep,
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
        ):
            action = handle_workflow_error(
                RuntimeError(_CLAUDE_WEEKLY_LIMIT), tracker, ctx, state
            )

        assert action == "raise"
        mock_sleep.assert_not_called()
        attempts = load_attempt_history(str(tmp_path / "artifacts"))
        assert attempts[-1].reason is not None
        assert "claude" in attempts[-1].reason


class TestDetectUsageLimitForError:
    def test_known_provider_does_not_fall_through_to_scan(self) -> None:
        with patch(
            "sase.llm_provider.usage_limit_config.load_merged_config",
            return_value={},
        ):
            assert _detect_usage_limit_for_error(_CLAUDE_WEEKLY_LIMIT, "codex") is None
            scanned = _detect_usage_limit_for_error(_CLAUDE_WEEKLY_LIMIT, None)
        assert scanned is not None
        assert scanned.provider == "claude"
