"""Shared ACE daemon read client helpers."""

from __future__ import annotations

from typing import Any

from sase.daemon.client import LocalDaemonClient


def ace_daemon_read_client(app: Any) -> LocalDaemonClient:
    """Return the ACE app's shared daemon read client."""

    client = getattr(app, "_daemon_read_client", None)
    if client is None:
        client = LocalDaemonClient()
        app._daemon_read_client = client
    return client


__all__ = ["ace_daemon_read_client"]
