"""Tests for run_agent_exec_retry usage-limit classification and fallback."""

import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from sase.ace.tui.models.agent_attempt import load_attempt_history
from sase.axe.run_agent_exec_retry import (
    RetryTracker,
    _detect_usage_limit_for_error,
    handle_workflow_error,
)
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_MODE_HARD,
    PROVIDER_DISABLE_MODE_SOFT,
    PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
    TemporaryProviderDisable,
    get_active_provider_disable,
)
from sase.llm_provider.retry_config import ProviderRetryConfig, get_retry_config
from sase.llm_provider.usage_limit_disable import handle_possible_usage_limit
from tests._axe_run_agent_exec_retry_helpers import (
    CLAUDE_WEEKLY_LIMIT,
    _restore_model_override_env,  # noqa: F401 (registers the autouse fixture)
    make_ctx,
    make_state,
)

_CLAUDE_WEEKLY_LIMIT_083_WORKFLOW_WRAPPER = (
    "Step 'main' failed: Error running LLM provider command (exit code 1)\n"
    "stderr: [result] You've hit your weekly limit · resets Aug 22, 8pm "
    "(America/New_York)\n"
    "output: I'll start by exploring the codebase ...\n"
    "You've hit your weekly limit · resets Aug 22, 8pm (America/New_York)"
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

    def test_fallback_allowed_when_fallback_provider_carries_soft_disable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A soft disable on the fallback provider never disqualifies it."""
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
        soft_disable = TemporaryProviderDisable(
            version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
            provider="claude",
            created_at=100.0,
            expires_at=None,
            source="test",
            mode=PROVIDER_DISABLE_MODE_SOFT,
        )

        with (
            patch(
                "sase.llm_provider.usage_limit_config.load_merged_config",
                return_value={},
            ),
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
            patch(
                "sase.axe.run_agent_exec_retry.get_active_provider_disable",
                return_value=soft_disable,
            ),
        ):
            action = handle_workflow_error(
                RuntimeError(error_text), tracker, ctx, state
            )

        assert action == "continue"
        assert tracker.using_fallback is True
        assert os.environ["SASE_MODEL_OVERRIDE"] == "claude/opus"

    def test_fallback_blocked_when_fallback_provider_carries_hard_disable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A hard disable on the fallback provider still disqualifies it."""
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
        hard_disable = TemporaryProviderDisable(
            version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
            provider="claude",
            created_at=100.0,
            expires_at=None,
            source="test",
            mode=PROVIDER_DISABLE_MODE_HARD,
        )

        with (
            patch(
                "sase.llm_provider.usage_limit_config.load_merged_config",
                return_value={},
            ),
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
            patch(
                "sase.axe.run_agent_exec_retry.get_active_provider_disable",
                return_value=hard_disable,
            ),
        ):
            action = handle_workflow_error(
                RuntimeError(error_text), tracker, ctx, state
            )

        assert action == "raise"
        assert tracker.using_fallback is False

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

    def test_claude_weekly_limit_without_retry_match_still_writes_disable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path))
        monkeypatch.setattr(
            "sase.llm_provider.registry.registered_provider_names",
            lambda: ["claude", "codex", "fakey", "grok", "agy"],
        )
        tz = ZoneInfo("America/New_York")
        fixed_now = datetime(2026, 8, 19, 15, 43, 56, tzinfo=tz).timestamp()
        monkeypatch.setattr(
            "sase.llm_provider.usage_limit_config.time.time", lambda: fixed_now
        )
        ctx = make_ctx(tmp_path)
        state = make_state("Do the work.")

        with patch(
            "sase.llm_provider.retry_config.load_merged_config", return_value={}
        ):
            retry_cfg = get_retry_config("claude")
        assert retry_cfg is not None
        tracker = RetryTracker(retry_cfg=retry_cfg, execution_provider="claude")

        with (
            patch(
                "sase.llm_provider.usage_limit_config.load_merged_config",
                return_value={},
            ),
            patch(
                "sase.axe.run_agent_exec_retry.time.sleep", MagicMock()
            ) as mock_sleep,
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
            patch(
                "sase.axe.run_agent_exec_retry.handle_possible_usage_limit",
                wraps=handle_possible_usage_limit,
            ) as mock_handle,
        ):
            action = handle_workflow_error(
                RuntimeError(_CLAUDE_WEEKLY_LIMIT_083_WORKFLOW_WRAPPER),
                tracker,
                ctx,
                state,
            )

        assert action == "raise"
        assert tracker.retry_count == 0
        mock_sleep.assert_not_called()
        mock_handle.assert_called_once()
        assert mock_handle.call_args.kwargs["provider"] == "claude"
        assert "weekly limit" in mock_handle.call_args.kwargs["error_text"]

        disable = get_active_provider_disable("claude", now=fixed_now)
        assert disable is not None
        assert disable.source == "usage_limit"
        expected_expires_at = (
            datetime(2026, 8, 22, 20, 0, 0, tzinfo=tz).timestamp() + 60
        )
        assert disable.expires_at == pytest.approx(expected_expires_at, abs=1)


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
