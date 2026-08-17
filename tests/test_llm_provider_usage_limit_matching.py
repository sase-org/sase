"""Tests for usage-limit text normalization and pattern matching."""

from sase.llm_provider.usage_limit_config import (
    ProviderUsageLimitConfig,
    find_matching_pattern,
    is_usage_limit_error,
    normalize_for_match,
)


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
