"""Display-cache behavior for contextual usage hints."""

from __future__ import annotations

import pytest

from sase.llm_provider.usage import peek as peek_mod
from sase.llm_provider.usage.peek import (
    _clear_usage_peek_cache,
    cached_usage_peek,
    usage_attention_enabled,
)
from tests.llm_provider._provider_config_helpers import mock_provider_config
from tests.llm_provider.test_usage_hints import _claude_model_specific_low


def test_config_opt_out_hides_planted_usage_attention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    peek_mod._peek_providers = (_claude_model_specific_low(),)
    peek_mod._peek_eligible = frozenset({"claude"})
    try:
        mock_provider_config(monkeypatch, {"usage_metrics": {"enabled": False}})
        assert usage_attention_enabled() is False
        providers, eligible = cached_usage_peek()
        assert providers == ()
        assert eligible == frozenset()
        mock_provider_config(monkeypatch, {"usage_metrics": {"enabled": True}})
        assert usage_attention_enabled() is True
        providers, eligible = cached_usage_peek()
        assert providers
        assert "claude" in eligible
    finally:
        _clear_usage_peek_cache()
