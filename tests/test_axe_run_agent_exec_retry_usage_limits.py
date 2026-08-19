"""Tests for run_agent_exec_retry usage-limit classification and fallback."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.ace.tui.models.agent_attempt import load_attempt_history
from sase.axe.run_agent_exec_retry import (
    RetryTracker,
    _detect_usage_limit_for_error,
    handle_workflow_error,
)
from sase.llm_provider.retry_config import ProviderRetryConfig, get_retry_config
from tests._axe_run_agent_exec_retry_helpers import (
    CLAUDE_WEEKLY_LIMIT,
    _restore_model_override_env,  # noqa: F401 (registers the autouse fixture)
    make_ctx,
    make_state,
)


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
        ctx = make_ctx(tmp_path)
        state = make_state("Do the work.")

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
        ctx = make_ctx(tmp_path)
        state = make_state("Do the work.")

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
        ctx = make_ctx(tmp_path)
        state = make_state("Do the work.")
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
        ctx = make_ctx(tmp_path)
        state = make_state("Do the work.")
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
        ctx = make_ctx(tmp_path)
        state = make_state("Do the work.")

        with patch(
            "sase.llm_provider.retry_config.load_merged_config", return_value={}
        ):
            retry_cfg = get_retry_config("codex")
        assert retry_cfg is not None
        tracker = RetryTracker(retry_cfg=retry_cfg, execution_provider="codex")
        error_text = (
            f"Error: 429 Too Many Requests. Quoted Claude output: {CLAUDE_WEEKLY_LIMIT}"
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
        ctx = make_ctx(tmp_path)
        state = make_state("Do the work.")
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
                RuntimeError(CLAUDE_WEEKLY_LIMIT), tracker, ctx, state
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
        ctx = make_ctx(tmp_path)
        state = make_state("Do the work.")
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
                RuntimeError(CLAUDE_WEEKLY_LIMIT), tracker, ctx, state
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
            assert _detect_usage_limit_for_error(CLAUDE_WEEKLY_LIMIT, "codex") is None
            scanned = _detect_usage_limit_for_error(CLAUDE_WEEKLY_LIMIT, None)
        assert scanned is not None
        assert scanned.provider == "claude"
