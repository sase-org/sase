"""Tests for LLM provider retry configuration lookup."""

from pathlib import Path

from unittest.mock import patch

import yaml

from sase.llm_provider.retry_config import (
    ProviderRetryConfig,
    find_retry_config_for_error,
    get_retry_config,
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

    def test_default_sdd_version_skew_is_fresh_process_retryable(self) -> None:
        default_config = yaml.safe_load(
            (
                Path(__file__).resolve().parents[1]
                / "src"
                / "sase"
                / "default_config.yml"
            ).read_text(encoding="utf-8")
        )
        error = (
            "SddMaterializationError: SDD store record /repo/.sase/sdd-store.json "
            "uses a format this process does not understand"
        )

        with patch(
            "sase.llm_provider.retry_config.load_merged_config",
            return_value=default_config,
        ):
            config = find_retry_config_for_error(error)

        assert config is not None
        assert config.max_retries == 1
        assert config.wait_times == [0]
        assert config.preserve_workspace is True
        assert config.spawn_new_agent is True
