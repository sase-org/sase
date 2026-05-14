"""Provider factory helpers."""

from __future__ import annotations

from sase.daemon.client import LocalDaemonClient

from ._daemon import DaemonAgentsDataProvider
from ._direct import DirectAgentsDataProvider
from ._settings import agents_daemon_reads_enabled
from ._types import AgentsDataProvider


def make_agents_data_provider(
    *, client: LocalDaemonClient | None = None
) -> AgentsDataProvider:
    """Return the configured Agents-tab data provider."""

    if agents_daemon_reads_enabled():
        return DaemonAgentsDataProvider(client=client)
    return DirectAgentsDataProvider()
