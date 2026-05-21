"""Tests for retry config fields used by spawn-on-retry."""

from __future__ import annotations

from sase.llm_provider.retry_config import (
    ProviderRetryConfig,
    _config_from_user_dict,
    _merge_with_built_in,
)


class TestSpawnNewAgentMerge:
    def test_user_dict_override_takes_precedence(self) -> None:
        built_in = ProviderRetryConfig(
            max_retries=2,
            error_patterns=["foo"],
            spawn_new_agent=False,
        )
        user_dict = {"spawn_new_agent": True}
        merged = _merge_with_built_in(user_dict, built_in)
        assert merged.spawn_new_agent is True

        user_only = _config_from_user_dict({"spawn_new_agent": True})
        assert user_only.spawn_new_agent is True

        merged_default = _merge_with_built_in({}, built_in)
        assert merged_default.spawn_new_agent is False
