"""Tests for built-in LLM provider usage-limit detection defaults.

The regression corpus below uses the verbatim captured strings recorded in
the epic sase-n4 plan research (apostrophes intact), plus explicit negative
cases that must NOT trip a disable.
"""

from unittest.mock import patch

from sase.llm_provider.registry import iter_plugins
from sase.llm_provider.usage_limit_config import (
    get_usage_limit_config,
    is_usage_limit_error,
)

# --- Regression corpus: real captured provider messages ---

_CLAUDE_WEEKLY_LIMIT = "You've hit your weekly limit · resets 8pm (America/New_York)"

# U+2019 RIGHT SINGLE QUOTATION MARK in "You’ve", verified by hexdump per the
# plan's research.
_GROK_USAGE_LIMIT = (
    "Error: You’ve reached your free Grok Build usage limit for now. "
    "Get SuperGrok for much higher limits, or try again later: "
    "https://grok.com/supergrok?referrer=grok-build"
)

_CODEX_UPGRADE_TO_PRO = (
    "You've hit your usage limit. Upgrade to Pro "
    "(https://chatgpt.com/explore/pro), visit "
    "https://chatgpt.com/codex/settings/usage to purchase more credits"
)

# --- Negative cases: must NOT match (Claude advisory/cooldown text) ---

_CLAUDE_APPROACHING_ADVISORY = (
    "[Usage limit approaching. Checkpoint now: finish the current step…]"
)
_CLAUDE_GRACE_WINDOW_ADVISORY = (
    "[Usage limit reached — grace window active. Wrap up: finish or checkpoint…]"
)
_CLAUDE_FAST_MODE_COOLDOWN = (
    "Fast limit reached and temporarily disabled · resets in 5m"
)
_CLAUDE_CLOSE_TO_LIMIT_ADVISORY = "You're close to your usage limit"


class TestClaudeBuiltInDefaults:
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_built_in_returned_without_user_config(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("claude")
        assert config is not None
        assert "you've hit your weekly limit" in config.patterns
        assert "usage limit approaching" in config.exclude_patterns

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_matches_captured_weekly_limit_failure(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("claude")
        assert config is not None
        assert is_usage_limit_error(_CLAUDE_WEEKLY_LIMIT, config) is True

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_does_not_match_approaching_advisory(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("claude")
        assert config is not None
        assert is_usage_limit_error(_CLAUDE_APPROACHING_ADVISORY, config) is False

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_does_not_match_grace_window_advisory(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("claude")
        assert config is not None
        assert is_usage_limit_error(_CLAUDE_GRACE_WINDOW_ADVISORY, config) is False

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_does_not_match_fast_mode_cooldown(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("claude")
        assert config is not None
        assert is_usage_limit_error(_CLAUDE_FAST_MODE_COOLDOWN, config) is False

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_does_not_match_close_to_limit_advisory(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("claude")
        assert config is not None
        assert is_usage_limit_error(_CLAUDE_CLOSE_TO_LIMIT_ADVISORY, config) is False

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_user_appends_custom_pattern_to_built_in(self, mock_config: object) -> None:
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "usage_limit": {
                    "providers": {"claude": {"patterns": ["my custom claude pattern"]}}
                }
            }
        }
        config = get_usage_limit_config("claude")
        assert config is not None
        assert "usage limit reached" in config.patterns
        assert "my custom claude pattern" in config.patterns


class TestCodexBuiltInDefaults:
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_built_in_returned_without_user_config(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("codex")
        assert config is not None
        assert "you've hit your usage limit" in config.patterns
        assert "usage limit approaching" in config.exclude_patterns

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_matches_captured_upgrade_to_pro_failure(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("codex")
        assert config is not None
        assert is_usage_limit_error(_CODEX_UPGRADE_TO_PRO, config) is True


class TestGrokBuiltInDefaults:
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_built_in_returned_without_user_config(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("grok")
        assert config is not None
        assert config.patterns

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_matches_captured_live_failure_with_curly_apostrophe(
        self, mock_config: object
    ) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("grok")
        assert config is not None
        assert is_usage_limit_error(_GROK_USAGE_LIMIT, config) is True


class TestQwenAndAgyBuiltInDefaults:
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_qwen_matches_transport_level_quota_error(
        self, mock_config: object
    ) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("qwen")
        assert config is not None
        assert (
            is_usage_limit_error("RESOURCE_EXHAUSTED: quota exceeded", config) is True
        )

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_agy_matches_quota_error(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("agy")
        assert config is not None
        assert is_usage_limit_error("Quota exceeded for this project", config) is True


class TestUnverifiedProviderBaselines:
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_muse_has_conservative_baseline(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("muse")
        assert config is not None
        assert is_usage_limit_error("usage limit reached", config) is True

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_opencode_has_conservative_baseline(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("opencode")
        assert config is not None
        assert is_usage_limit_error("quota exceeded", config) is True


class TestFakeyBuiltInDefaults:
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_fakey_matches_deterministic_trigger(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("fakey")
        assert config is not None
        assert is_usage_limit_error("stderr: FAKEY-USAGE-LIMIT tripped", config) is True

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_fakey_does_not_match_unrelated_text(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("fakey")
        assert config is not None
        assert is_usage_limit_error("some other failure", config) is False


class TestEveryRegisteredProviderHasABuiltIn:
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_every_registered_provider_returns_a_built_in_config(
        self, mock_config: object
    ) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        provider_names = [name for name, _ in iter_plugins()]
        assert provider_names  # sanity: plugins are actually registered
        for name in provider_names:
            config = get_usage_limit_config(name)
            assert config is not None, f"{name} has no built-in usage-limit config"
            assert config.patterns, f"{name}'s built-in has no patterns"
