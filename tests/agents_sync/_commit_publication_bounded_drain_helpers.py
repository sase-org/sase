"""Shared public helpers for the bounded commit-publication drain test modules."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.agents_sync import _commit_publication_support as publication_support
from sase.agents_sync.models import ProjectTarget, TargetSelection
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync.commit_publication_fixtures import setup_target


def configure_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    owner: AgentOwnerIdentity,
) -> tuple[ProjectTarget, Path]:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, remote = setup_target(tmp_path)
    monkeypatch.setattr(
        publication_support,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        publication_support,
        "require_agent_owner_identity",
        lambda: owner,
    )
    return target, remote
