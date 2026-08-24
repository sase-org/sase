"""Tests for LLM provider usage-limit detection configuration."""

from unittest.mock import patch

from sase.llm_provider.usage_limit_config import (
    ProviderUsageLimitConfig,
    UsageLimitSettings,
    detect_usage_limit,
    get_usage_limit_config,
    get_usage_limit_settings,
    is_usage_limit_error,
)

# Provider name guaranteed to have no built-in or user config.
_UNCONFIGURED_PROVIDER = "fake-unconfigured-provider"


# --- ProviderUsageLimitConfig / UsageLimitSettings tests ---


class TestProviderUsageLimitConfig:
    def test_defaults(self) -> None:
        config = ProviderUsageLimitConfig()
        assert config.patterns == []
        assert config.exclude_patterns == []
        assert config.disable_seconds is None
        assert config.honor_reset_hint is None

    def test_custom_values(self) -> None:
        config = ProviderUsageLimitConfig(
            patterns=["a", "b"],
            exclude_patterns=["c"],
            disable_seconds=120,
            honor_reset_hint=False,
        )
        assert config.patterns == ["a", "b"]
        assert config.exclude_patterns == ["c"]
        assert config.disable_seconds == 120
        assert config.honor_reset_hint is False


class TestUsageLimitSettings:
    def test_defaults(self) -> None:
        settings = UsageLimitSettings()
        assert settings.enabled is True
        assert settings.disable_seconds == 86400
        assert settings.min_disable_seconds == 60
        assert settings.max_disable_seconds == 604800
        assert settings.honor_reset_hint is True
        assert settings.notify is True
        assert settings.relaunch is True
        assert settings.relaunch_limit == 20


# --- get_usage_limit_config tests ---


class TestGetUsageLimitConfig:
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_returns_none_with_default_config(self, mock_config: object) -> None:
        mock_config.return_value = {"llm_provider": {"provider": "", "usage_limit": {}}}  # type: ignore[union-attr]
        assert get_usage_limit_config(_UNCONFIGURED_PROVIDER) is None

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_returns_config_when_user_only(self, mock_config: object) -> None:
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "usage_limit": {
                    "providers": {
                        "gemini": {
                            "patterns": ["quota exceeded"],
                            "exclude_patterns": ["approaching quota"],
                            "disable_seconds": 120,
                            "honor_reset_hint": False,
                        }
                    }
                }
            }
        }
        config = get_usage_limit_config("gemini")
        assert config is not None
        assert config.patterns == ["quota exceeded"]
        assert config.exclude_patterns == ["approaching quota"]
        assert config.disable_seconds == 120
        assert config.honor_reset_hint is False

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_returns_none_for_unconfigured_provider(self, mock_config: object) -> None:
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "usage_limit": {
                    "providers": {"gemini": {"patterns": ["quota exceeded"]}}
                }
            }
        }
        assert get_usage_limit_config(_UNCONFIGURED_PROVIDER) is None

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_returns_none_when_no_llm_provider_section(
        self, mock_config: object
    ) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        assert get_usage_limit_config(_UNCONFIGURED_PROVIDER) is None

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_returns_none_on_exception(self, mock_config: object) -> None:
        mock_config.side_effect = RuntimeError("config error")  # type: ignore[union-attr]
        assert get_usage_limit_config(_UNCONFIGURED_PROVIDER) is None

    @patch("sase.llm_provider.usage_limit_config._built_in_defaults")
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_additive_merge_dedups_and_preserves_order(
        self, mock_config: object, mock_built_in: object
    ) -> None:
        mock_built_in.return_value = {  # type: ignore[union-attr]
            "test-provider": ProviderUsageLimitConfig(
                patterns=["built-in one", "built-in two"],
                exclude_patterns=["built-in exclude"],
            )
        }
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "usage_limit": {
                    "providers": {
                        "test-provider": {
                            "patterns": ["user one", "built-in one"],
                            "exclude_patterns": ["user exclude"],
                        }
                    }
                }
            }
        }
        config = get_usage_limit_config("test-provider")
        assert config is not None
        assert config.patterns == ["built-in one", "built-in two", "user one"]
        assert config.exclude_patterns == ["built-in exclude", "user exclude"]

    @patch("sase.llm_provider.usage_limit_config._built_in_defaults")
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_replace_patterns_true_replaces_built_in(
        self, mock_config: object, mock_built_in: object
    ) -> None:
        mock_built_in.return_value = {  # type: ignore[union-attr]
            "test-provider": ProviderUsageLimitConfig(patterns=["built-in one"])
        }
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "usage_limit": {
                    "providers": {
                        "test-provider": {
                            "patterns": ["replacement pattern"],
                            "replace_patterns": True,
                        }
                    }
                }
            }
        }
        config = get_usage_limit_config("test-provider")
        assert config is not None
        assert config.patterns == ["replacement pattern"]

    @patch("sase.llm_provider.usage_limit_config._built_in_defaults")
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_replace_patterns_true_with_no_user_patterns_keeps_built_in(
        self, mock_config: object, mock_built_in: object
    ) -> None:
        mock_built_in.return_value = {  # type: ignore[union-attr]
            "test-provider": ProviderUsageLimitConfig(patterns=["built-in one"])
        }
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "usage_limit": {
                    "providers": {"test-provider": {"replace_patterns": True}}
                }
            }
        }
        config = get_usage_limit_config("test-provider")
        assert config is not None
        assert config.patterns == ["built-in one"]

    @patch("sase.llm_provider.usage_limit_config._built_in_defaults")
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_replace_patterns_true_with_empty_list_disables_built_in(
        self, mock_config: object, mock_built_in: object
    ) -> None:
        mock_built_in.return_value = {  # type: ignore[union-attr]
            "test-provider": ProviderUsageLimitConfig(patterns=["built-in one"])
        }
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "usage_limit": {
                    "providers": {
                        "test-provider": {
                            "patterns": [],
                            "replace_patterns": True,
                        }
                    }
                }
            }
        }
        config = get_usage_limit_config("test-provider")
        assert config is not None
        assert config.patterns == []
        assert is_usage_limit_error("built-in one tripped", config) is False
        assert detect_usage_limit("test-provider", "built-in one tripped") is None

    @patch("sase.llm_provider.usage_limit_config._built_in_defaults")
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_exclude_patterns_have_no_replace_escape_hatch(
        self, mock_config: object, mock_built_in: object
    ) -> None:
        mock_built_in.return_value = {  # type: ignore[union-attr]
            "test-provider": ProviderUsageLimitConfig(
                patterns=["p"], exclude_patterns=["built-in exclude"]
            )
        }
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "usage_limit": {
                    "providers": {
                        "test-provider": {
                            "exclude_patterns": ["user exclude"],
                            "replace_patterns": True,
                        }
                    }
                }
            }
        }
        config = get_usage_limit_config("test-provider")
        assert config is not None
        assert config.exclude_patterns == ["built-in exclude", "user exclude"]

    @patch("sase.llm_provider.usage_limit_config._built_in_defaults")
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_explicit_null_disable_seconds_overrides_built_in(
        self, mock_config: object, mock_built_in: object
    ) -> None:
        mock_built_in.return_value = {  # type: ignore[union-attr]
            "test-provider": ProviderUsageLimitConfig(
                patterns=["p"], disable_seconds=300
            )
        }
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "usage_limit": {
                    "providers": {"test-provider": {"disable_seconds": None}}
                }
            }
        }
        config = get_usage_limit_config("test-provider")
        assert config is not None
        assert config.disable_seconds is None

    @patch("sase.llm_provider.usage_limit_config._built_in_defaults")
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_user_unset_scalar_uses_built_in(
        self, mock_config: object, mock_built_in: object
    ) -> None:
        mock_built_in.return_value = {  # type: ignore[union-attr]
            "test-provider": ProviderUsageLimitConfig(
                patterns=["p"], disable_seconds=300, honor_reset_hint=False
            )
        }
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "usage_limit": {"providers": {"test-provider": {"patterns": ["x"]}}}
            }
        }
        config = get_usage_limit_config("test-provider")
        assert config is not None
        assert config.disable_seconds == 300
        assert config.honor_reset_hint is False

    @patch("sase.llm_provider.usage_limit_config._built_in_defaults")
    def test_built_in_clone_is_defensive(self, mock_built_in: object) -> None:
        mock_built_in.return_value = {  # type: ignore[union-attr]
            "test-provider": ProviderUsageLimitConfig(patterns=["built-in"])
        }
        with patch(
            "sase.llm_provider.usage_limit_config.load_merged_config",
            return_value={},
        ):
            first = get_usage_limit_config("test-provider")
            assert first is not None
            first.patterns.append("not really a pattern")

            second = get_usage_limit_config("test-provider")
            assert second is not None
            assert "not really a pattern" not in second.patterns


# --- get_usage_limit_settings tests ---


class TestGetUsageLimitSettings:
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_defaults_with_empty_config(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        assert get_usage_limit_settings() == UsageLimitSettings()

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_user_overrides(self, mock_config: object) -> None:
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "usage_limit": {
                    "enabled": False,
                    "disable_seconds": 3600,
                    "min_disable_seconds": 30,
                    "max_disable_seconds": 7200,
                    "honor_reset_hint": False,
                    "notify": False,
                    "relaunch": False,
                    "relaunch_limit": 5,
                }
            }
        }
        settings = get_usage_limit_settings()
        assert settings.enabled is False
        assert settings.disable_seconds == 3600
        assert settings.min_disable_seconds == 30
        assert settings.max_disable_seconds == 7200
        assert settings.honor_reset_hint is False
        assert settings.notify is False
        assert settings.relaunch is False
        assert settings.relaunch_limit == 5

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_returns_defaults_on_exception(self, mock_config: object) -> None:
        mock_config.side_effect = RuntimeError("broken")  # type: ignore[union-attr]
        assert get_usage_limit_settings() == UsageLimitSettings()
