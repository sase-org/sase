"""Retry and fallback configuration for LLM providers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from sase.config import load_merged_config

RETRY_STATE_FILENAME = "retry_state.json"

RetryStatus = Literal["retrying", "running_retry", "running_fallback"]


@dataclass
class ProviderRetryConfig:
    """Per-provider retry configuration."""

    max_retries: int = 0
    error_patterns: list[str] = field(default_factory=list)
    wait_times: list[int] = field(default_factory=lambda: [30])
    fallback_model: str | None = None


@dataclass
class RetryState:
    """Retry state written to artifacts dir for TUI consumption."""

    status: RetryStatus
    retry_count: int
    max_retries: int
    next_retry_at_epoch: float | None = None
    wait_seconds: int = 0
    fallback_model: str | None = None
    using_fallback: bool = False
    last_error_snippet: str | None = None

    def write_to(self, artifacts_dir: str) -> None:
        """Write retry_state.json atomically to the artifacts directory."""
        path = Path(artifacts_dir) / RETRY_STATE_FILENAME
        temp_path = path.with_suffix(".tmp")
        try:
            with open(temp_path, "w") as f:
                json.dump(asdict(self), f, indent=2)
            temp_path.rename(path)
        except OSError:
            try:
                temp_path.unlink()
            except OSError:
                pass

    @classmethod
    def read_from(cls, artifacts_dir: str) -> RetryState | None:
        """Read retry_state.json from the artifacts directory."""
        path = Path(artifacts_dir) / RETRY_STATE_FILENAME
        if not path.exists():
            return None
        try:
            with open(path) as f:
                data = json.load(f)
            return cls(**data)
        except (OSError, json.JSONDecodeError, TypeError):
            return None

    @classmethod
    def delete_from(cls, artifacts_dir: str) -> None:
        """Delete retry_state.json from the artifacts directory."""
        path = Path(artifacts_dir) / RETRY_STATE_FILENAME
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def get_retry_config(provider_name: str) -> ProviderRetryConfig | None:
    """Load retry config for a specific provider from merged config.

    Returns None if no retry config is set for the provider.
    """
    try:
        data = load_merged_config()
        if not isinstance(data, dict):
            return None

        llm_config = data.get("llm_provider", {}) or {}
        retry_section = llm_config.get("retry", {}) or {}
        provider_retry = retry_section.get(provider_name)

        if not provider_retry or not isinstance(provider_retry, dict):
            return None

        return ProviderRetryConfig(
            max_retries=provider_retry.get("max_retries", 0),
            error_patterns=provider_retry.get("error_patterns", []),
            wait_times=provider_retry.get("wait_times", [30]),
            fallback_model=provider_retry.get("fallback_model") or None,
        )
    except Exception:
        return None


def is_retryable_error(error_output: str, config: ProviderRetryConfig) -> bool:
    """Check if an error matches any configured retry patterns.

    Performs case-insensitive substring matching against the error output.
    """
    if not config.error_patterns:
        return False

    error_lower = error_output.lower()
    return any(pattern.lower() in error_lower for pattern in config.error_patterns)


def get_wait_time(retry_count: int, config: ProviderRetryConfig) -> int:
    """Return the wait time in seconds for the Nth retry (1-indexed).

    If the wait_times list is shorter than the retry count, the last value
    is reused. If the list is empty, defaults to 30 seconds.
    """
    if not config.wait_times:
        return 30

    idx = min(retry_count - 1, len(config.wait_times) - 1)
    return config.wait_times[idx]
