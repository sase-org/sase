"""Bootstrap identity-pending claims for the agent-name registry rebuild.

Split from ``tests.test_agent_name_registry_rebuild``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
from unittest.mock import patch

import pytest

from sase.agent.names import (
    claim_exact_planned_registered_name,
    claim_registered_clan_name,
    lookup_registered_name,
    rebuild_name_registry,
    reserve_registered_clan_name,
    reserve_registered_name,
)
from sase.agent.names import _registry
from sase.core.process_identity import process_identity_token

from tests._agent_names_fixtures import make_agent as _make_agent

__all__ = [
    "test_locked_fallback_keeps_live_identity_pending_claim",
    "test_registry_rebuild_derives_named_meta_landing_after_scan",
    "test_registry_rebuild_drops_claim_for_removed_dir",
    "test_registry_rebuild_drops_claim_when_dir_names_another_identity",
    "test_registry_rebuild_drops_dead_identity_pending_claim",
    "test_registry_rebuild_keeps_live_identity_pending_claim",
    "test_registry_rebuild_keeps_live_identity_pending_clan_claim",
]


def _make_identity_pending_agent(base: Path, suffix: str = "pending") -> Path:
    """Create the bootstrap metadata present before an agent publishes its name."""
    artifact_dir = (
        base / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / suffix
    )
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "process_identity": process_identity_token(os.getpid()),
                "launch_scratch_key": "test-key",
            }
        ),
        encoding="utf-8",
    )
    return artifact_dir


def _claim_identity_pending_name(artifact_dir: Path, name: str) -> None:
    reserve_registered_name(name, artifact_dir)
    assert claim_exact_planned_registered_name(name, artifact_dir)


def test_registry_rebuild_keeps_live_identity_pending_claim(
    tmp_path: Path,
) -> None:
    artifact_dir = _make_identity_pending_agent(tmp_path)
    with patch.object(Path, "home", return_value=tmp_path):
        _claim_identity_pending_name(artifact_dir, "pending")
        # Adding a sibling makes the registry stale while this runner is in its
        # bootstrap-to-named-metadata interval.
        _make_agent(tmp_path, "proj", "sibling", "sibling")
        rebuilt = rebuild_name_registry()
        assert rebuilt["entries"]["pending"]["reservation_kind"] == "claimed"

        (artifact_dir / "agent_meta.json").write_text(
            json.dumps({"name": "pending", "pid": os.getpid()}),
            encoding="utf-8",
        )
        with patch.object(
            _registry, "rebuild_name_registry", wraps=rebuild_name_registry
        ) as rebuild:
            assert lookup_registered_name("pending") is not None
            assert rebuild.call_count == 0


def test_locked_fallback_keeps_live_identity_pending_claim(tmp_path: Path) -> None:
    artifact_dir = _make_identity_pending_agent(tmp_path)
    with patch.object(Path, "home", return_value=tmp_path):
        _claim_identity_pending_name(artifact_dir, "pending")
        with patch.object(_registry, "_REBUILD_LOCK_RETRIES", 0):
            rebuilt = rebuild_name_registry()

    assert rebuilt["entries"]["pending"]["reservation_kind"] == "claimed"


@pytest.mark.parametrize("bootstrap_meta", [{}, {"pid": 99_999_999}])
def test_registry_rebuild_drops_dead_identity_pending_claim(
    tmp_path: Path,
    bootstrap_meta: dict[str, object],
) -> None:
    artifact_dir = _make_identity_pending_agent(tmp_path)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps(bootstrap_meta), encoding="utf-8"
    )
    with patch.object(Path, "home", return_value=tmp_path):
        _claim_identity_pending_name(artifact_dir, "pending")
        rebuilt = rebuild_name_registry()

    assert "pending" not in rebuilt["entries"]


def test_registry_rebuild_derives_named_meta_landing_after_scan(tmp_path: Path) -> None:
    artifact_dir = _make_identity_pending_agent(tmp_path)
    with patch.object(Path, "home", return_value=tmp_path):
        _claim_identity_pending_name(artifact_dir, "pending")
        (artifact_dir / "agent_meta.json").write_text(
            json.dumps({"name": "pending", "pid": os.getpid()}),
            encoding="utf-8",
        )
        # Model an unlocked scan that completed before the name was published.
        with patch.object(
            _registry, "_collect_rebuild_source_entries", return_value={}
        ):
            rebuilt = rebuild_name_registry()

    assert rebuilt["entries"]["pending"]["reservation_kind"] == "claimed"


def test_registry_rebuild_drops_claim_when_dir_names_another_identity(
    tmp_path: Path,
) -> None:
    artifact_dir = _make_identity_pending_agent(tmp_path)
    with patch.object(Path, "home", return_value=tmp_path):
        _claim_identity_pending_name(artifact_dir, "old-name")
        (artifact_dir / "agent_meta.json").write_text(
            json.dumps({"name": "new-name", "pid": os.getpid()}),
            encoding="utf-8",
        )
        rebuilt = rebuild_name_registry()

    assert "old-name" not in rebuilt["entries"]
    assert rebuilt["entries"]["new-name"]["reservation_kind"] == "claimed"


def test_registry_rebuild_drops_claim_for_removed_dir(tmp_path: Path) -> None:
    artifact_dir = _make_identity_pending_agent(tmp_path)
    with patch.object(Path, "home", return_value=tmp_path):
        _claim_identity_pending_name(artifact_dir, "pending")
        shutil.rmtree(artifact_dir)
        rebuilt = rebuild_name_registry()

    assert "pending" not in rebuilt["entries"]


def test_registry_rebuild_keeps_live_identity_pending_clan_claim(
    tmp_path: Path,
) -> None:
    artifact_dir = _make_identity_pending_agent(tmp_path)
    with patch.object(Path, "home", return_value=tmp_path):
        reserve_registered_clan_name("clan", "generation", artifact_dir)
        claim_registered_clan_name("clan", "generation", artifact_dir)
        rebuilt = rebuild_name_registry()

    assert rebuilt["entries"]["clan"]["reservation_kind"] == "clan"
