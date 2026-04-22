"""Tests for LLM provider retry configuration and state."""

import json
from pathlib import Path
from unittest.mock import patch

from sase.llm_provider.retry_config import (
    RETRY_STATE_FILENAME,
    ProviderRetryConfig,
    RetryState,
    find_retry_config_for_error,
    get_retry_config,
    get_wait_time,
    is_retryable_error,
)

# Provider name guaranteed to have no built-in or user config — used to
# assert "truly unconfigured" behavior now that some providers ship with
# built-in defaults (e.g. claude's "Prompt is too long" recovery).
_UNCONFIGURED_PROVIDER = "fake-unconfigured-provider"


# --- ProviderRetryConfig tests ---


class TestProviderRetryConfig:
    def test_defaults(self) -> None:
        config = ProviderRetryConfig()
        assert config.max_retries == 0
        assert config.error_patterns == []
        assert config.wait_times == [30]
        assert config.fallback_model is None
        assert config.continuation_prompt is None
        assert config.preserve_workspace is False

    def test_custom_values(self) -> None:
        config = ProviderRetryConfig(
            max_retries=3,
            error_patterns=["rate limit", "503"],
            wait_times=[30, 60, 120],
            fallback_model="gemini-3-flash-preview",
            continuation_prompt="resume where you left off",
            preserve_workspace=True,
        )
        assert config.max_retries == 3
        assert config.error_patterns == ["rate limit", "503"]
        assert config.wait_times == [30, 60, 120]
        assert config.fallback_model == "gemini-3-flash-preview"
        assert config.continuation_prompt == "resume where you left off"
        assert config.preserve_workspace is True


# --- get_retry_config tests ---


class TestGetRetryConfig:
    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_returns_none_with_default_config(self, mock_config: object) -> None:
        mock_config.return_value = {"llm_provider": {"provider": "", "retry": {}}}  # type: ignore[union-attr]
        assert get_retry_config("gemini") is None

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_returns_config_when_set(self, mock_config: object) -> None:
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "gemini": {
                        "max_retries": 3,
                        "error_patterns": ["rate limit", "503"],
                        "wait_times": [30, 60, 120],
                        "fallback_model": "gemini-3-flash-preview",
                    }
                }
            }
        }
        config = get_retry_config("gemini")
        assert config is not None
        assert config.max_retries == 3
        assert config.error_patterns == ["rate limit", "503"]
        assert config.wait_times == [30, 60, 120]
        assert config.fallback_model == "gemini-3-flash-preview"

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_returns_none_for_unconfigured_provider(self, mock_config: object) -> None:
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "gemini": {"max_retries": 3, "error_patterns": ["rate limit"]}
                }
            }
        }
        assert get_retry_config(_UNCONFIGURED_PROVIDER) is None

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_partial_config_uses_defaults(self, mock_config: object) -> None:
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {"gemini": {"max_retries": 2, "error_patterns": ["503"]}}
            }
        }
        config = get_retry_config("gemini")
        assert config is not None
        assert config.max_retries == 2
        assert config.error_patterns == ["503"]
        assert config.wait_times == [30]  # default
        assert config.fallback_model is None  # default

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_returns_none_when_no_llm_provider_section(
        self, mock_config: object
    ) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        assert get_retry_config(_UNCONFIGURED_PROVIDER) is None

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_returns_none_when_retry_section_missing(self, mock_config: object) -> None:
        mock_config.return_value = {"llm_provider": {"provider": "gemini"}}  # type: ignore[union-attr]
        assert get_retry_config(_UNCONFIGURED_PROVIDER) is None

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_returns_none_on_exception(self, mock_config: object) -> None:
        mock_config.side_effect = RuntimeError("config error")  # type: ignore[union-attr]
        assert get_retry_config(_UNCONFIGURED_PROVIDER) is None

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_empty_fallback_model_becomes_none(self, mock_config: object) -> None:
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "gemini": {
                        "max_retries": 1,
                        "error_patterns": ["err"],
                        "fallback_model": "",
                    }
                }
            }
        }
        config = get_retry_config("gemini")
        assert config is not None
        assert config.fallback_model is None


# --- find_retry_config_for_error tests ---


class TestFindRetryConfigForError:
    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_finds_matching_provider(self, mock_config: object) -> None:
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "gemini": {
                        "max_retries": 3,
                        "error_patterns": ["unexpected critical error"],
                        "wait_times": [60],
                    }
                }
            }
        }
        config = find_retry_config_for_error("An unexpected critical error occurred")
        assert config is not None
        assert config.max_retries == 3

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_returns_none_when_no_match(self, mock_config: object) -> None:
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "gemini": {
                        "max_retries": 3,
                        "error_patterns": ["unexpected critical error"],
                    }
                }
            }
        }
        assert find_retry_config_for_error("authentication failed") is None

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_returns_none_with_empty_config(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        assert find_retry_config_for_error("any error") is None

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_checks_multiple_providers(self, mock_config: object) -> None:
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "claude": {
                        "max_retries": 1,
                        "error_patterns": ["overloaded"],
                    },
                    "gemini": {
                        "max_retries": 3,
                        "error_patterns": ["quota exceeded"],
                        "fallback_model": "gemini-flash",
                    },
                }
            }
        }
        # Should match gemini config
        config = find_retry_config_for_error("quota exceeded for project")
        assert config is not None
        assert config.max_retries == 3
        assert config.fallback_model == "gemini-flash"

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_returns_none_on_exception(self, mock_config: object) -> None:
        mock_config.side_effect = RuntimeError("broken")  # type: ignore[union-attr]
        assert find_retry_config_for_error("any error") is None


# --- Built-in default tests ---


class TestBuiltInDefaults:
    """Built-in retry defaults for universal failure modes."""

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_claude_built_in_returned_without_user_config(
        self, mock_config: object
    ) -> None:
        """claude gets a built-in 'Prompt is too long' recovery config."""
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_retry_config("claude")
        assert config is not None
        assert config.max_retries == 3
        assert "Prompt is too long" in config.error_patterns
        assert config.wait_times == [0]
        assert config.continuation_prompt is not None
        assert "context window" in config.continuation_prompt
        assert config.preserve_workspace is True

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_built_in_returned_when_exception(self, mock_config: object) -> None:
        """Even if user config can't be loaded, built-ins still apply."""
        mock_config.side_effect = RuntimeError("broken")  # type: ignore[union-attr]
        config = get_retry_config("claude")
        assert config is not None
        assert config.max_retries == 3

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_user_appends_custom_pattern_to_built_in(self, mock_config: object) -> None:
        """User patterns are unioned with built-in patterns, deduplicated."""
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "claude": {
                        "error_patterns": ["my custom pattern", "Prompt is too long"],
                    }
                }
            }
        }
        config = get_retry_config("claude")
        assert config is not None
        # Built-in pattern appears exactly once (dedup'd) and order preserved:
        # built-in first, then new user patterns.
        assert config.error_patterns == ["Prompt is too long", "my custom pattern"]

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_user_explicit_max_retries_zero_disables(self, mock_config: object) -> None:
        """User explicitly setting max_retries=0 disables even built-in retries."""
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "claude": {"max_retries": 0},
                }
            }
        }
        config = get_retry_config("claude")
        assert config is not None
        assert config.max_retries == 0  # user's explicit 0 wins over built-in 3

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_user_unset_max_retries_uses_built_in(self, mock_config: object) -> None:
        """When user doesn't set max_retries, the built-in value is used."""
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "claude": {"error_patterns": ["other"]},
                }
            }
        }
        config = get_retry_config("claude")
        assert config is not None
        assert config.max_retries == 3  # from built-in

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_user_empty_continuation_prompt_overrides(
        self, mock_config: object
    ) -> None:
        """User setting continuation_prompt='' disables the built-in nudge."""
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "claude": {"continuation_prompt": ""},
                }
            }
        }
        config = get_retry_config("claude")
        assert config is not None
        assert config.continuation_prompt == ""

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_user_custom_continuation_prompt_wins(self, mock_config: object) -> None:
        """User-set continuation_prompt replaces the built-in nudge."""
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "claude": {"continuation_prompt": "my custom nudge"},
                }
            }
        }
        config = get_retry_config("claude")
        assert config is not None
        assert config.continuation_prompt == "my custom nudge"

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_built_in_clone_is_defensive(self, mock_config: object) -> None:
        """Mutating a returned built-in must not affect later calls."""
        mock_config.return_value = {}  # type: ignore[union-attr]
        first = get_retry_config("claude")
        assert first is not None
        first.error_patterns.append("not really a pattern")

        second = get_retry_config("claude")
        assert second is not None
        assert "not really a pattern" not in second.error_patterns

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_built_in_clone_copies_preserve_workspace(
        self, mock_config: object
    ) -> None:
        """_clone_config defensively copies the preserve_workspace flag."""
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_retry_config("claude")
        assert config is not None
        assert config.preserve_workspace is True

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_user_unset_preserve_workspace_uses_built_in(
        self, mock_config: object
    ) -> None:
        """User config without preserve_workspace inherits built-in True."""
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "claude": {"error_patterns": ["other"]},
                }
            }
        }
        config = get_retry_config("claude")
        assert config is not None
        assert config.preserve_workspace is True

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_user_explicit_preserve_workspace_false_overrides(
        self, mock_config: object
    ) -> None:
        """User explicit preserve_workspace=False overrides built-in True."""
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "claude": {"preserve_workspace": False},
                }
            }
        }
        config = get_retry_config("claude")
        assert config is not None
        assert config.preserve_workspace is False

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_user_only_config_preserve_workspace_defaults_false(
        self, mock_config: object
    ) -> None:
        """User-only provider with no preserve_workspace key defaults to False."""
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "gemini": {"max_retries": 2, "error_patterns": ["503"]},
                }
            }
        }
        config = get_retry_config("gemini")
        assert config is not None
        assert config.preserve_workspace is False

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_user_only_config_preserve_workspace_true(
        self, mock_config: object
    ) -> None:
        """User-only provider can opt in to preserve_workspace=True."""
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "gemini": {
                        "max_retries": 2,
                        "error_patterns": ["503"],
                        "preserve_workspace": True,
                    },
                }
            }
        }
        config = get_retry_config("gemini")
        assert config is not None
        assert config.preserve_workspace is True

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_find_retry_config_picks_up_built_in(self, mock_config: object) -> None:
        """find_retry_config_for_error checks built-in providers too."""
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = find_retry_config_for_error("API Error: 400 - Prompt is too long")
        assert config is not None
        assert config.max_retries == 3
        assert "Prompt is too long" in config.error_patterns


# --- is_retryable_error tests ---


class TestIsRetryableError:
    def test_matches_case_insensitive(self) -> None:
        config = ProviderRetryConfig(error_patterns=["Rate Limit"])
        assert is_retryable_error("RATE LIMIT exceeded", config) is True
        assert is_retryable_error("rate limit exceeded", config) is True

    def test_matches_any_pattern(self) -> None:
        config = ProviderRetryConfig(error_patterns=["rate limit", "503", "overloaded"])
        assert is_retryable_error("got a 503 error", config) is True
        assert is_retryable_error("service overloaded", config) is True

    def test_no_match(self) -> None:
        config = ProviderRetryConfig(error_patterns=["rate limit", "503"])
        assert is_retryable_error("authentication failed", config) is False

    def test_empty_patterns_returns_false(self) -> None:
        config = ProviderRetryConfig(error_patterns=[])
        assert is_retryable_error("any error", config) is False

    def test_empty_error_output(self) -> None:
        config = ProviderRetryConfig(error_patterns=["rate limit"])
        assert is_retryable_error("", config) is False

    def test_substring_matching(self) -> None:
        config = ProviderRetryConfig(error_patterns=["quota"])
        assert is_retryable_error("quota exceeded for project", config) is True


# --- get_wait_time tests ---


class TestGetWaitTime:
    def test_normal_indexing(self) -> None:
        config = ProviderRetryConfig(wait_times=[30, 60, 120])
        assert get_wait_time(1, config) == 30
        assert get_wait_time(2, config) == 60
        assert get_wait_time(3, config) == 120

    def test_reuses_last_value(self) -> None:
        config = ProviderRetryConfig(wait_times=[30, 60])
        assert get_wait_time(3, config) == 60
        assert get_wait_time(10, config) == 60

    def test_empty_wait_times_defaults_to_30(self) -> None:
        config = ProviderRetryConfig(wait_times=[])
        assert get_wait_time(1, config) == 30
        assert get_wait_time(5, config) == 30

    def test_single_wait_time(self) -> None:
        config = ProviderRetryConfig(wait_times=[45])
        assert get_wait_time(1, config) == 45
        assert get_wait_time(3, config) == 45


# --- RetryState tests ---


class TestRetryState:
    def test_defaults(self) -> None:
        state = RetryState(status="retrying", retry_count=1, max_retries=3)
        assert state.next_retry_at_epoch is None
        assert state.wait_seconds == 0
        assert state.fallback_model is None
        assert state.using_fallback is False
        assert state.last_error_snippet is None

    def test_write_and_read_roundtrip(self, tmp_path: Path) -> None:
        state = RetryState(
            status="retrying",
            retry_count=2,
            max_retries=3,
            next_retry_at_epoch=1710600660.0,
            wait_seconds=60,
            fallback_model="gemini-3-flash-preview",
            using_fallback=False,
            last_error_snippet="rate limit exceeded...",
        )
        state.write_to(str(tmp_path))

        loaded = RetryState.read_from(str(tmp_path))
        assert loaded is not None
        assert loaded.status == "retrying"
        assert loaded.retry_count == 2
        assert loaded.max_retries == 3
        assert loaded.next_retry_at_epoch == 1710600660.0
        assert loaded.wait_seconds == 60
        assert loaded.fallback_model == "gemini-3-flash-preview"
        assert loaded.using_fallback is False
        assert loaded.last_error_snippet == "rate limit exceeded..."

    def test_read_from_nonexistent_returns_none(self, tmp_path: Path) -> None:
        assert RetryState.read_from(str(tmp_path)) is None

    def test_read_from_invalid_json_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / RETRY_STATE_FILENAME).write_text("not json")
        assert RetryState.read_from(str(tmp_path)) is None

    def test_read_from_wrong_fields_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / RETRY_STATE_FILENAME).write_text(json.dumps({"bad": "data"}))
        assert RetryState.read_from(str(tmp_path)) is None

    def test_delete_from(self, tmp_path: Path) -> None:
        state = RetryState(status="retrying", retry_count=1, max_retries=3)
        state.write_to(str(tmp_path))
        assert (tmp_path / RETRY_STATE_FILENAME).exists()

        RetryState.delete_from(str(tmp_path))
        assert not (tmp_path / RETRY_STATE_FILENAME).exists()

    def test_delete_from_nonexistent_no_error(self, tmp_path: Path) -> None:
        RetryState.delete_from(str(tmp_path))  # should not raise

    def test_write_creates_valid_json(self, tmp_path: Path) -> None:
        state = RetryState(
            status="running_fallback",
            retry_count=3,
            max_retries=3,
            using_fallback=True,
            fallback_model="flash",
        )
        state.write_to(str(tmp_path))

        with open(tmp_path / RETRY_STATE_FILENAME) as f:
            data = json.load(f)

        assert data["status"] == "running_fallback"
        assert data["retry_count"] == 3
        assert data["using_fallback"] is True
        assert data["fallback_model"] == "flash"
