"""Tests for the usage-limit runtime-enforcement entry point.

``handle_possible_usage_limit`` is called from the LLM invocation error
paths; see ``tests/test_llm_provider_invoke.py`` for the call-site wiring.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider.provider_disable import (
    disable_provider,
    get_active_provider_disable,
)
from sase.llm_provider.usage_limit_config import UsageLimitDetection
from sase.llm_provider.usage_limit_disable import handle_possible_usage_limit

_NOW = 1_800_000_000.0


@pytest.fixture
def registered_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.registry.registered_provider_names",
        lambda: ["claude", "codex", "fakey"],
    )


@pytest.fixture(autouse=True)
def _sase_home(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))


def _detection(
    *,
    provider: str = "claude",
    expires_at: float | None = None,
    disable_seconds: float = 100.0,
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
    )


class TestHandlePossibleUsageLimit:
    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_returns_none_when_no_match(
        self, mock_detect: MagicMock, registered_providers: None
    ) -> None:
        mock_detect.return_value = None
        result = handle_possible_usage_limit(provider="claude", error_text="all good")
        assert result is None
        assert get_active_provider_disable("claude") is None

    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_writes_flat_disable_when_no_expiry(
        self, mock_detect: MagicMock, registered_providers: None
    ) -> None:
        mock_detect.return_value = _detection(disable_seconds=120.0)
        result = handle_possible_usage_limit(
            provider="claude", error_text="usage limit reached"
        )
        assert result is not None
        disable = get_active_provider_disable("claude")
        assert disable is not None
        assert disable.source == "usage_limit"
        assert disable.expires_at is not None

    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_writes_until_disable_when_expiry_present(
        self, mock_detect: MagicMock, registered_providers: None
    ) -> None:
        mock_detect.return_value = _detection(expires_at=_NOW + 3600.0)
        handle_possible_usage_limit(provider="claude", error_text="usage limit reached")
        disable = get_active_provider_disable("claude", now=_NOW)
        assert disable is not None
        assert disable.expires_at == _NOW + 3600.0
        assert disable.source == "usage_limit"

    @patch("sase.llm_provider.usage_limit_disable.disable_provider")
    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_skips_write_when_already_disabled(
        self,
        mock_detect: MagicMock,
        mock_disable: MagicMock,
        registered_providers: None,
    ) -> None:
        disable_provider("claude", 999.0, source="usage_limit", now=_NOW)
        mock_detect.return_value = _detection()

        result = handle_possible_usage_limit(
            provider="claude", error_text="usage limit reached"
        )

        assert result is not None
        mock_disable.assert_not_called()

    @patch(
        "sase.llm_provider.usage_limit_disable.detect_usage_limit",
        side_effect=RuntimeError("boom"),
    )
    def test_never_raises_on_internal_error(
        self, _mock_detect: MagicMock, registered_providers: None
    ) -> None:
        result = handle_possible_usage_limit(
            provider="claude", error_text="usage limit reached"
        )
        assert result is None

    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_increments_telemetry_counter_on_write(
        self, mock_detect: MagicMock, registered_providers: None
    ) -> None:
        mock_detect.return_value = _detection()
        mock_counter = MagicMock()
        with patch(
            "sase.llm_provider.usage_limit_disable.LLM_PROVIDER_AUTO_DISABLES",
            mock_counter,
        ):
            handle_possible_usage_limit(
                provider="claude", error_text="usage limit reached"
            )
        mock_counter.labels.assert_called_once_with(provider="claude")
        mock_counter.labels.return_value.inc.assert_called_once()

    def test_end_to_end_with_fakey_trigger(self, registered_providers: None) -> None:
        """The fakey provider's deterministic trigger exercises real detection."""
        result = handle_possible_usage_limit(
            provider="fakey",
            error_text="stderr: FAKEY-USAGE-LIMIT hit",
        )
        assert result is not None
        assert result.provider == "fakey"
        disable = get_active_provider_disable("fakey")
        assert disable is not None
        assert disable.source == "usage_limit"

    def test_end_to_end_no_match_leaves_provider_enabled(
        self, registered_providers: None
    ) -> None:
        result = handle_possible_usage_limit(
            provider="fakey",
            error_text="some unrelated transient error",
        )
        assert result is None
        assert get_active_provider_disable("fakey") is None
