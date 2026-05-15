"""Provider factory helpers."""

from __future__ import annotations

from ._direct import DirectAgentsDataProvider
from ._types import AgentsDataProvider


def make_agents_data_provider() -> AgentsDataProvider:
    """Return the configured Agents-tab data provider."""
    return DirectAgentsDataProvider()
