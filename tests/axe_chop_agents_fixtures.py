"""Pytest fixtures for chop-launched agent tracking tests."""

from __future__ import annotations

import pytest

from sase.core.agent_identity_facade import AgentOwnerIdentity


@pytest.fixture(autouse=True)
def _configured_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
