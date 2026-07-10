"""Tests for LLM provider retry helpers and state persistence."""

import json
from pathlib import Path

from sase.llm_provider.retry_config import (
    RETRY_STATE_FILENAME,
    ProviderRetryConfig,
    RetryState,
    get_wait_time,
    is_retryable_error,
)


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
