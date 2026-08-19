"""Tests for built-in LLM provider usage-limit detection defaults.

The regression corpus below uses the verbatim captured strings recorded in
the epic sase-n4 plan research (apostrophes intact), plus explicit negative
cases that must NOT trip a disable.
"""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from sase.llm_provider.registry import iter_plugins
from sase.llm_provider.usage_limit_config import (
    detect_usage_limit,
    get_usage_limit_config,
    is_usage_limit_error,
)

# --- Regression corpus: real captured provider messages ---

_CLAUDE_WEEKLY_LIMIT = "You've hit your weekly limit · resets 8pm (America/New_York)"

# The >24h branch of Claude Code 2.1.235's ``fW(epoch, withZone)`` formatter,
# which is what a `seven_day` limit actually produces (see the comment on
# ``claude.py``'s ``llm_default_usage_limit_config``). Spaced meridiems are
# kept as an ICU-shape regression; the live 083 capture below is compact.
_CLAUDE_WEEKLY_LIMIT_WITH_RESET_DATE = (
    "You've hit your weekly limit · resets Aug 20, 6:38 am (America/New_York)"
)

# Verbatim trigger from agent 083 on 2026-08-19. Compact meridiem (`8pm`, no
# space) is the live ``fW`` >24h spelling; minutes of zero are omitted.
_CLAUDE_WEEKLY_LIMIT_083 = (
    "You've hit your weekly limit · resets Aug 22, 8pm (America/New_York)"
)
_CLAUDE_WEEKLY_LIMIT_083_INVOKE_WRAPPER = (
    "Error running LLM provider command (exit code 1)\n"
    "stderr: [result] You've hit your weekly limit · resets Aug 22, 8pm "
    "(America/New_York)\n"
    "output: I'll start by exploring the codebase ...\n"
    "You've hit your weekly limit · resets Aug 22, 8pm (America/New_York)"
)
_CLAUDE_WEEKLY_LIMIT_083_WORKFLOW_WRAPPER = (
    "Step 'main' failed: Error running LLM provider command (exit code 1)\n"
    "stderr: [result] You've hit your weekly limit · resets Aug 22, 8pm "
    "(America/New_York)\n"
    "output: I'll start by exploring the codebase ...\n"
    "You've hit your weekly limit · resets Aug 22, 8pm (America/New_York)"
)
_CLAUDE_FABLE_5_LIMIT = (
    "You've hit your Fable 5 limit · resets Aug 22, 8pm (America/New_York)"
)
_CLAUDE_USAGE_CREDIT_LIMIT = (
    "You've hit your usage credit limit · resets Aug 22, 8pm (America/New_York)"
)

# U+2019 RIGHT SINGLE QUOTATION MARK in "You’ve", verified by hexdump per the
# plan's research.
_GROK_USAGE_LIMIT = (
    "Error: You’ve reached your free Grok Build usage limit for now. "
    "Get SuperGrok for much higher limits, or try again later: "
    "https://grok.com/supergrok?referrer=grok-build"
)

# Verbatim stderr from the three 2026-08-18 grok agent failures (see the
# plan's Background section); JSON braces and newlines intact on purpose —
# normalization collapses whitespace, and using the real multi-line shape is
# what proves that.
_GROK_USAGE_BALANCE_EXHAUSTED = """\
Error running LLM provider command (exit code 1)
stderr: Error: Internal error: {
  "message": "API error (status 402 Payment Required): Grok Build usage balance exhausted",
  "http_status": 402,
  "promptUsage": { ... }
}"""

_CODEX_UPGRADE_TO_PRO = (
    "You've hit your usage limit. Upgrade to Pro "
    "(https://chatgpt.com/explore/pro), visit "
    "https://chatgpt.com/codex/settings/usage to purchase more credits"
)

# Verbatim failure from the sase-o8.2 agent that motivated this parser fix
# (see the plan's Background section): Codex named its reset instant three
# days out and SASE disabled for the flat 24h fallback instead of honoring it.
_CODEX_TRY_AGAIN_AT_DATE = (
    "You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage to "
    "purchase more credits or try again at Aug 20th, 2026 6:38 AM."
)

_AGY_INDIVIDUAL_QUOTA_REACHED = (
    "Error: Individual quota reached. Please upgrade your subscription to increase\n"
    "your limits. Resets in 4h14m50s."
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
_CLAUDE_FAST_LIMIT_HIT = "You've hit your fast limit · resets in 5m"
_CLAUDE_CLOSE_TO_LIMIT_ADVISORY = "You're close to your usage limit"

# Grok Build pager rate-limit strings: throttling, not quota exhaustion, and
# must stay on the retry path rather than tripping a usage-limit disable.
_GROK_RATE_LIMIT_PLAN = (
    "You've hit the rate limit for your plan. Upgrade your account or try again later."
)
_GROK_TEAM_RATE_LIMIT = (
    "You've hit your team's API rate limit. Ask a team admin to purchase "
    "more credits for higher limits, or try again later."
)


class TestClaudeBuiltInDefaults:
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_built_in_returned_without_user_config(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("claude")
        assert config is not None
        assert "you've hit your weekly limit" in config.patterns
        assert "you've hit your" in config.patterns
        assert "you've reached your" in config.patterns
        assert "you're out of usage credits" in config.patterns
        assert "your org is out of usage" in config.patterns
        assert "usage limit approaching" in config.exclude_patterns
        assert "you've hit your fast limit" in config.exclude_patterns

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
    def test_does_not_match_binary_fast_limit_hit(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("claude")
        assert config is not None
        assert is_usage_limit_error(_CLAUDE_FAST_LIMIT_HIT, config) is False

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_matches_fable_5_limit_label(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("claude")
        assert config is not None
        assert is_usage_limit_error(_CLAUDE_FABLE_5_LIMIT, config) is True

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_matches_usage_credit_limit_label(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("claude")
        assert config is not None
        assert is_usage_limit_error(_CLAUDE_USAGE_CREDIT_LIMIT, config) is True

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_does_not_match_close_to_limit_advisory(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("claude")
        assert config is not None
        assert is_usage_limit_error(_CLAUDE_CLOSE_TO_LIMIT_ADVISORY, config) is False

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_weekly_limit_with_reset_date_uses_reset_hint_duration(
        self, mock_config: object
    ) -> None:
        # The >24h branch of Claude's own reset-time formatter must resolve
        # to the real ~3-day gap, not the flat 24h fallback — the same defect
        # as the Codex regression, proven here rather than merely asserted.
        mock_config.return_value = {}  # type: ignore[union-attr]
        tz = ZoneInfo("America/New_York")
        now = datetime(2026, 8, 17, 6, 38, 0, tzinfo=tz).timestamp()
        detection = detect_usage_limit(
            "claude", _CLAUDE_WEEKLY_LIMIT_WITH_RESET_DATE, now=now
        )

        assert detection is not None
        assert detection.used_reset_hint is True
        assert detection.disable_seconds == pytest.approx(3 * 86400, abs=120)
        assert detection.disable_seconds != 86400

    @pytest.mark.parametrize(
        "error_text",
        [
            _CLAUDE_WEEKLY_LIMIT_083,
            _CLAUDE_WEEKLY_LIMIT_083_INVOKE_WRAPPER,
            _CLAUDE_WEEKLY_LIMIT_083_WORKFLOW_WRAPPER,
        ],
    )
    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_captured_083_weekly_limit_uses_reset_hint_duration(
        self, mock_config: object, error_text: str
    ) -> None:
        # Live 2.1.235 compact ``8pm`` spelling. This assertion would fail if
        # ``_RESET_MONTH_DATE_RE`` required ``\s+`` before ``am|pm``.
        mock_config.return_value = {}  # type: ignore[union-attr]
        tz = ZoneInfo("America/New_York")
        now = datetime(2026, 8, 19, 15, 43, 56, tzinfo=tz).timestamp()
        detection = detect_usage_limit("claude", error_text, now=now)

        assert detection is not None
        assert "weekly limit" in detection.matched_pattern
        assert detection.used_reset_hint is True
        assert detection.reset_hint is not None
        assert "Aug 22" in detection.reset_hint
        assert "8pm" in detection.reset_hint
        expected = datetime(2026, 8, 22, 20, 0, 0, tzinfo=tz).timestamp() + 60 - now
        assert detection.disable_seconds == pytest.approx(expected, abs=2)
        assert detection.disable_seconds != 86400

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_unanchored_reset_date_honored_after_usage_limit_match(
        self, mock_config: object
    ) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        tz = ZoneInfo("America/New_York")
        now = datetime(2026, 8, 19, 15, 43, 56, tzinfo=tz).timestamp()
        detection = detect_usage_limit(
            "claude",
            "You've hit your weekly limit · Aug 22, 8pm (America/New_York)",
            now=now,
        )

        assert detection is not None
        assert detection.used_reset_hint is True
        assert detection.reset_hint is not None
        assert "Aug 22" in detection.reset_hint
        assert "8pm" in detection.reset_hint
        expected = datetime(2026, 8, 22, 20, 0, 0, tzinfo=tz).timestamp() + 60 - now
        assert detection.disable_seconds == pytest.approx(expected, abs=2)

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

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_captured_reset_at_date_failure_uses_reset_hint_duration(
        self, mock_config: object
    ) -> None:
        # The reported bug, end to end: a ~3-day-out reset instant must
        # disable for ~3 days, not the flat 24h fallback.
        mock_config.return_value = {}  # type: ignore[union-attr]
        tz = ZoneInfo("UTC")
        now = datetime(2026, 8, 17, 6, 38, 0, tzinfo=tz).timestamp()
        with patch("sase.core.time.get_timezone", return_value=tz):
            detection = detect_usage_limit("codex", _CODEX_TRY_AGAIN_AT_DATE, now=now)

        assert detection is not None
        assert detection.used_reset_hint is True
        assert detection.disable_seconds == pytest.approx(3 * 86400, abs=120)
        assert detection.disable_seconds != 86400


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

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_matches_captured_usage_balance_exhausted_failure(
        self, mock_config: object
    ) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("grok")
        assert config is not None
        assert is_usage_limit_error(_GROK_USAGE_BALANCE_EXHAUSTED, config) is True

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_disable_seconds_is_48h(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("grok")
        assert config is not None
        assert config.disable_seconds == 172800

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_does_not_match_plan_rate_limit(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("grok")
        assert config is not None
        assert is_usage_limit_error(_GROK_RATE_LIMIT_PLAN, config) is False

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_does_not_match_team_rate_limit(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("grok")
        assert config is not None
        assert is_usage_limit_error(_GROK_TEAM_RATE_LIMIT, config) is False


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

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_agy_matches_captured_individual_quota_failure(
        self, mock_config: object
    ) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_usage_limit_config("agy")
        assert config is not None
        assert is_usage_limit_error(_AGY_INDIVIDUAL_QUOTA_REACHED, config) is True

    @patch("sase.llm_provider.usage_limit_config.load_merged_config")
    def test_agy_captured_failure_uses_reset_hint_duration(
        self, mock_config: object
    ) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        detection = detect_usage_limit(
            "agy",
            _AGY_INDIVIDUAL_QUOTA_REACHED,
            now=1_800_000_000.0,
        )

        assert detection is not None
        assert detection.used_reset_hint is True
        assert detection.reset_hint == "4h14m"
        assert detection.disable_seconds == pytest.approx(4 * 3600 + 14 * 60 + 60)


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
