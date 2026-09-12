"""Shared fixtures and helpers for llm_provider invoke_agent tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from sase.llm_provider.provider_priority import ProviderRoutingContext
from sase.llm_provider.types import LLMInvocationOptions

_NO_EFFORT = LLMInvocationOptions(reasoning_effort=None, explicit=False)


def _assert_routing_context_kw(kwargs: dict[str, object]) -> ProviderRoutingContext:
    context = kwargs.get("routing_context")
    assert isinstance(context, ProviderRoutingContext)
    return context


def _assert_get_provider_called_once(
    mock_get_provider: MagicMock,
    provider: str,
) -> ProviderRoutingContext:
    mock_get_provider.assert_called_once()
    assert mock_get_provider.call_args.args == (provider,)
    return _assert_routing_context_kw(mock_get_provider.call_args.kwargs)


@pytest.fixture(autouse=True)
def _clear_execution_provider_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SASE_LLM_EXEC_PROVIDER", raising=False)
