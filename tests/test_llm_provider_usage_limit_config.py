"""Tests for LLM provider usage-limit detection configuration."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sase.llm_provider.usage_limit_config import (
    ProviderUsageLimitConfig,
    UsageLimitSettings,
    detect_usage_limit,
    find_matching_pattern,
    get_usage_limit_config,
    get_usage_limit_settings,
    is_usage_limit_error,
    normalize_for_match,
    parse_reset_hint,
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

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_returns_defaults_on_exception(self, mock_config: object) -> None:
        mock_config.side_effect = RuntimeError("broken")  # type: ignore[union-attr]
        assert get_usage_limit_settings() == UsageLimitSettings()


# --- normalize_for_match tests ---


class TestNormalizeForMatch:
    def test_casefolds(self) -> None:
        assert normalize_for_match("USAGE LIMIT") == "usage limit"

    def test_collapses_whitespace(self) -> None:
        assert normalize_for_match("usage   limit\nreached") == "usage limit reached"

    def test_normalizes_curly_apostrophe(self) -> None:
        assert normalize_for_match("You’ve hit") == normalize_for_match("You've hit")

    def test_normalizes_various_apostrophe_variants(self) -> None:
        base = normalize_for_match("You've hit your limit")
        for apostrophe in ("’", "‘", "ʼ", "´", "`"):
            assert normalize_for_match(f"You{apostrophe}ve hit your limit") == base

    def test_nfkc_normalizes_compatibility_characters(self) -> None:
        # U+FF35 FULLWIDTH LATIN CAPITAL LETTER U NFKC-normalizes to "U".
        assert normalize_for_match("Ｕsage limit") == "usage limit"


# --- matching tests ---


class TestFindMatchingPattern:
    def test_matches_substring_case_insensitively(self) -> None:
        config = ProviderUsageLimitConfig(patterns=["usage limit reached"])
        assert (
            find_matching_pattern("Error: USAGE LIMIT REACHED today", config)
            == "usage limit reached"
        )

    def test_no_patterns_never_matches(self) -> None:
        config = ProviderUsageLimitConfig()
        assert find_matching_pattern("usage limit reached", config) is None

    def test_exclude_pattern_blocks_match_anywhere_in_text(self) -> None:
        config = ProviderUsageLimitConfig(
            patterns=["usage limit reached"],
            exclude_patterns=["approaching"],
        )
        text = "[Usage limit approaching. Checkpoint now] usage limit reached later"
        assert find_matching_pattern(text, config) is None

    def test_is_usage_limit_error_true_and_false(self) -> None:
        config = ProviderUsageLimitConfig(patterns=["usage limit reached"])
        assert is_usage_limit_error("usage limit reached", config) is True
        assert is_usage_limit_error("all good", config) is False


# --- parse_reset_hint tests ---


class TestParseResetHint:
    def test_resets_with_zone(self) -> None:
        now = 1755302400.0
        expires_at, hint = parse_reset_hint(
            "You've hit your weekly limit · resets 8pm (America/New_York)",
            now=now,
        )
        assert expires_at is not None
        assert expires_at > now
        assert hint == "8pm (America/New_York)"

    def test_resets_without_zone_uses_local_timezone(self) -> None:
        with patch("sase.core.time.get_timezone", return_value=ZoneInfo("UTC")):
            expires_at, hint = parse_reset_hint("resets 11:30pm", now=1755302400.0)
        assert expires_at is not None
        assert hint == "11:30pm"

    def test_resets_in_duration_minutes(self) -> None:
        now = 1000.0
        expires_at, hint = parse_reset_hint("try again in 5m", now=now)
        assert expires_at == now + 5 * 60 + 60  # grace buffer
        assert hint == "5m"

    def test_resets_in_compound_duration(self) -> None:
        now = 1000.0
        expires_at, hint = parse_reset_hint("resets in 2h 15m", now=now)
        assert expires_at == now + (2 * 3600 + 15 * 60) + 60
        assert hint == "2h 15m"

    def test_rolls_forward_when_time_already_passed_today(self) -> None:
        tz = ZoneInfo("UTC")
        now_dt = datetime(2026, 1, 1, 23, 0, 0, tzinfo=tz)
        now = now_dt.timestamp()
        with patch("sase.core.time.get_timezone", return_value=tz):
            expires_at, hint = parse_reset_hint("resets 1am", now=now)
        assert expires_at is not None
        assert hint == "1am"
        resolved = datetime.fromtimestamp(expires_at - 60, tz=tz)
        assert resolved.day == 2
        assert resolved.hour == 1

    def test_unparseable_text_returns_none(self) -> None:
        assert parse_reset_hint("no reset info here", now=1000.0) == (None, None)

    def test_unknown_zone_does_not_fall_back_to_local_time(self) -> None:
        # An explicit but unrecognized zone must not be silently reinterpreted
        # via the local-timezone form.
        expires_at, hint = parse_reset_hint("resets 8pm (Not/AZone)", now=1000.0)
        assert expires_at is None
        assert hint is None


# --- detect_usage_limit tests ---


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
