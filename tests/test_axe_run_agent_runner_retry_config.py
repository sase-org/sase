"""Tests for retry configuration helpers."""

from sase.llm_provider.retry_config import truncate_error_snippet


class TestTruncateErrorSnippet:
    def test_short_string_unchanged(self) -> None:
        assert truncate_error_snippet("short error") == "short error"

    def test_exact_max_len_unchanged(self) -> None:
        s = "a" * 100
        assert truncate_error_snippet(s) == s

    def test_long_string_truncated(self) -> None:
        s = "a" * 150
        result = truncate_error_snippet(s)
        assert result == "a" * 100 + "..."
        assert len(result) == 103

    def test_custom_max_len(self) -> None:
        result = truncate_error_snippet("hello world", max_len=5)
        assert result == "hello..."

    def test_strips_whitespace(self) -> None:
        assert truncate_error_snippet("  error  ") == "error"

    def test_empty_string(self) -> None:
        assert truncate_error_snippet("") == ""

    def test_whitespace_only(self) -> None:
        assert truncate_error_snippet("   ") == ""
