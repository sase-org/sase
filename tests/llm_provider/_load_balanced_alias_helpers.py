"""Shared setup helpers for load-balanced model-alias tests."""

from __future__ import annotations

import pytest

from sase.llm_provider import config as llm_config
from sase.llm_provider.config import model_alias_selector_details
from tests.llm_provider._provider_config_helpers import mock_provider_config


def configure_pool(
    monkeypatch: pytest.MonkeyPatch,
    value: str = "claude/opus@medium | codex/gpt-5.5",
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"pool": value}},
        },
    )
    llm_config._get_model_aliases_for_token.cache_clear()
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )


def pool_member_snapshot() -> tuple[llm_config.ModelAliasSelectorMember, ...]:
    details = model_alias_selector_details("pool")
    assert details is not None
    assert details.mode == "round_robin"
    return details.members
