"""Shared fixtures and helpers for llm_provider usage-limit-disable tests."""

from __future__ import annotations

import pytest

from sase.llm_provider.usage_limit_config import UsageLimitDetection

_NOW = 1_800_000_000.0


@pytest.fixture(autouse=True)
def _sase_home(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))


def _detection(
    *,
    provider: str = "claude",
    expires_at: float | None = None,
    disable_seconds: float = 100.0,
    reset_source: str | None = None,
) -> UsageLimitDetection:
    return UsageLimitDetection(
        provider=provider,
        matched_pattern="usage limit reached",
        message="usage limit reached",
        raw_message="usage limit reached",
        disable_seconds=disable_seconds,
        expires_at=expires_at,
        reset_hint=None,
        used_reset_hint=expires_at is not None,
        reset_source=reset_source,
    )
