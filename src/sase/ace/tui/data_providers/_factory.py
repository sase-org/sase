"""Provider factory helpers."""

from __future__ import annotations

from ._daemon import DaemonAgentsDataProvider
from ._direct import DirectAgentsDataProvider
from ._settings import agents_daemon_reads_enabled
from ._types import AgentsDataProvider


def make_agents_data_provider() -> AgentsDataProvider:
    """Return the configured Agents-tab data provider."""

    if agents_daemon_reads_enabled():
        return DaemonAgentsDataProvider()
    return DirectAgentsDataProvider()
