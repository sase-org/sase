"""Tests for usage-limit detection across providers."""

from unittest.mock import patch

from sase.llm_provider.usage_limit_config import (
    ProviderUsageLimitConfig,
    detect_usage_limit,
    find_usage_limit_detection_for_error,
)

# Provider name guaranteed to have no built-in or user config.
_UNCONFIGURED_PROVIDER = "fake-unconfigured-provider"


class TestDetectUsageLimit:
    @patch("sase.llm_provider.usage_limit_config._built_in_defaults")
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_returns_none_when_disabled_globally(
        self, mock_config: object, mock_built_in: object
    ) -> None:
        mock_built_in.return_value = {  # type: ignore[union-attr]
            "test-provider": ProviderUsageLimitConfig(patterns=["usage limit reached"])
        }
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {"usage_limit": {"enabled": False}}
        }
        assert detect_usage_limit("test-provider", "usage limit reached") is None

    @patch("sase.llm_provider.usage_limit_config._built_in_defaults")
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_returns_none_when_no_config(
        self, mock_config: object, mock_built_in: object
    ) -> None:
        mock_built_in.return_value = {}  # type: ignore[union-attr]
        mock_config.return_value = {}  # type: ignore[union-attr]
        assert detect_usage_limit(_UNCONFIGURED_PROVIDER, "usage limit reached") is None

    @patch("sase.llm_provider.usage_limit_config._built_in_defaults")
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_returns_none_when_no_pattern_matches(
        self, mock_config: object, mock_built_in: object
    ) -> None:
        mock_built_in.return_value = {  # type: ignore[union-attr]
            "test-provider": ProviderUsageLimitConfig(patterns=["usage limit reached"])
        }
        mock_config.return_value = {}  # type: ignore[union-attr]
        assert detect_usage_limit("test-provider", "all good") is None

    @patch("sase.llm_provider.usage_limit_config._built_in_defaults")
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_falls_back_to_flat_disable_seconds_without_reset_hint(
        self, mock_config: object, mock_built_in: object
    ) -> None:
        mock_built_in.return_value = {  # type: ignore[union-attr]
            "test-provider": ProviderUsageLimitConfig(patterns=["usage limit reached"])
        }
        mock_config.return_value = {}  # type: ignore[union-attr]
        detection = detect_usage_limit(
            "test-provider", "usage limit reached", now=1000.0
        )
        assert detection is not None
        assert detection.provider == "test-provider"
        assert detection.matched_pattern == "usage limit reached"
        assert detection.disable_seconds == 86400
        assert detection.expires_at is None
        assert detection.used_reset_hint is False
        assert detection.reset_hint is None
        assert detection.raw_message == "usage limit reached"

    @patch("sase.llm_provider.usage_limit_config._built_in_defaults")
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_uses_reset_hint_when_available(
        self, mock_config: object, mock_built_in: object
    ) -> None:
        mock_built_in.return_value = {  # type: ignore[union-attr]
            "test-provider": ProviderUsageLimitConfig(patterns=["usage limit reached"])
        }
        mock_config.return_value = {}  # type: ignore[union-attr]
        detection = detect_usage_limit(
            "test-provider",
            "usage limit reached, try again in 5m",
            now=1000.0,
        )
        assert detection is not None
        assert detection.used_reset_hint is True
        assert detection.expires_at == 1000.0 + 5 * 60 + 60
        assert detection.disable_seconds == 5 * 60 + 60
        assert detection.reset_hint == "5m"

    @patch("sase.llm_provider.usage_limit_config._built_in_defaults")
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_clamps_reset_hint_duration_to_minimum(
        self, mock_config: object, mock_built_in: object
    ) -> None:
        mock_built_in.return_value = {  # type: ignore[union-attr]
            "test-provider": ProviderUsageLimitConfig(patterns=["usage limit reached"])
        }
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {"usage_limit": {"min_disable_seconds": 600}}
        }
        detection = detect_usage_limit(
            "test-provider",
            "usage limit reached, try again in 1m",
            now=1000.0,
        )
        assert detection is not None
        assert detection.disable_seconds == 600
        assert detection.expires_at == 1600.0

    @patch("sase.llm_provider.usage_limit_config._built_in_defaults")
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_clamps_reset_hint_duration_to_maximum(
        self, mock_config: object, mock_built_in: object
    ) -> None:
        mock_built_in.return_value = {  # type: ignore[union-attr]
            "test-provider": ProviderUsageLimitConfig(patterns=["usage limit reached"])
        }
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {"usage_limit": {"max_disable_seconds": 120}}
        }
        detection = detect_usage_limit(
            "test-provider",
            "usage limit reached, try again in 5h",
            now=1000.0,
        )
        assert detection is not None
        assert detection.disable_seconds == 120
        assert detection.expires_at == 1120.0

    @patch("sase.llm_provider.usage_limit_config._built_in_defaults")
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_honor_reset_hint_false_skips_parsing(
        self, mock_config: object, mock_built_in: object
    ) -> None:
        mock_built_in.return_value = {  # type: ignore[union-attr]
            "test-provider": ProviderUsageLimitConfig(
                patterns=["usage limit reached"], honor_reset_hint=False
            )
        }
        mock_config.return_value = {}  # type: ignore[union-attr]
        detection = detect_usage_limit(
            "test-provider",
            "usage limit reached, try again in 5m",
            now=1000.0,
        )
        assert detection is not None
        assert detection.used_reset_hint is False
        assert detection.expires_at is None
        assert detection.disable_seconds == 86400

    @patch("sase.llm_provider.usage_limit_config._built_in_defaults")
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_per_provider_disable_seconds_override(
        self, mock_config: object, mock_built_in: object
    ) -> None:
        mock_built_in.return_value = {  # type: ignore[union-attr]
            "test-provider": ProviderUsageLimitConfig(
                patterns=["usage limit reached"], disable_seconds=42
            )
        }
        mock_config.return_value = {}  # type: ignore[union-attr]
        detection = detect_usage_limit(
            "test-provider", "usage limit reached", now=1000.0
        )
        assert detection is not None
        assert detection.disable_seconds == 42


class TestFindUsageLimitDetectionForError:
    @patch("sase.llm_provider.usage_limit_config._built_in_defaults")
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_returns_none_when_no_provider_matches(
        self, mock_config: object, mock_built_in: object
    ) -> None:
        mock_built_in.return_value = {  # type: ignore[union-attr]
            "test-provider": ProviderUsageLimitConfig(patterns=["usage limit reached"])
        }
        mock_config.return_value = {}  # type: ignore[union-attr]
        assert find_usage_limit_detection_for_error("all good") is None

    @patch("sase.llm_provider.usage_limit_config._built_in_defaults")
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_finds_match_among_built_in_only_providers(
        self, mock_config: object, mock_built_in: object
    ) -> None:
        mock_built_in.return_value = {  # type: ignore[union-attr]
            "provider-a": ProviderUsageLimitConfig(patterns=["never matches"]),
            "provider-b": ProviderUsageLimitConfig(patterns=["usage limit reached"]),
        }
        mock_config.return_value = {}  # type: ignore[union-attr]
        detection = find_usage_limit_detection_for_error(
            "usage limit reached", now=1000.0
        )
        assert detection is not None
        assert detection.provider == "provider-b"

    @patch("sase.llm_provider.usage_limit_config._built_in_defaults")
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_prefers_user_configured_providers_first(
        self, mock_config: object, mock_built_in: object
    ) -> None:
        # Both providers match; user-configured "gemini" must be checked
        # (and returned) before the built-in-only "provider-b".
        mock_built_in.return_value = {  # type: ignore[union-attr]
            "provider-b": ProviderUsageLimitConfig(patterns=["usage limit reached"]),
        }
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "usage_limit": {
                    "providers": {
                        "gemini": {"patterns": ["usage limit reached"]},
                    }
                }
            }
        }
        detection = find_usage_limit_detection_for_error(
            "usage limit reached", now=1000.0
        )
        assert detection is not None
        assert detection.provider == "gemini"
