"""Successful path-component validation memoization."""

from __future__ import annotations

import pytest

from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync import v2_validation


def test_component_cache_keeps_successes_and_rechecks_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(v2_validation, "_VALID_COMPONENT_CACHE", {})

    assert v2_validation.validate_component("worker", label="agent name") == "worker"
    assert "worker" in v2_validation._VALID_COMPONENT_CACHE

    with pytest.raises(AgentsSyncFormatError, match="unsafe hood name"):
        v2_validation.validate_component(".hidden", label="hood name")
    assert ".hidden" not in v2_validation._VALID_COMPONENT_CACHE

    with pytest.raises(AgentsSyncFormatError, match="unsafe run label"):
        v2_validation.validate_component(".hidden", label="run label")
