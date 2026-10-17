"""Private shared fixtures for the runtime commit tag tests."""

from __future__ import annotations

import pytest

from sase.core.agent_identity_facade import AgentOwnerIdentity

owner_target = "sase.config.require_agent_owner_identity"


@pytest.fixture(autouse=True)
def clean_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "SASE_AGENT_NAME",
        "SASE_ARTIFACTS_DIR",
        "SASE_MODEL_OVERRIDE",
        "SASE_AGENT_LLM_PROVIDER",
        "SASE_PLAN",
        "SASE_BUG_ID",
        "HOSTNAME",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        owner_target,
        lambda: AgentOwnerIdentity("alice", "machine_a"),
    )
