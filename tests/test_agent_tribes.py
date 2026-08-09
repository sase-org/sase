"""Canonical agent-tribe persistence and legacy-import tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import time
from unittest.mock import patch

from sase.ace.agent_tribes import (
    load_agent_tribes,
    save_agent_tribes,
    update_agent_tribe,
    update_agent_tribe_assignment,
)
from sase.ace.tui.models.agent import AgentType


def _paths(canonical: Path, legacy: Path):  # type: ignore[no-untyped-def]
    return (
        patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", canonical),
        patch("sase.ace.agent_tribes._LEGACY_AGENT_TAGS_FILE", legacy),
    )


def test_canonical_file_precedes_stale_legacy_assignments(tmp_path: Path) -> None:
    canonical = tmp_path / "agent_tribes.json"
    legacy = tmp_path / "agent_tags.json"
    canonical.write_text(
        json.dumps([{"id": ["run", "same", "ts"], "tribe": "current"}])
    )
    legacy.write_text(json.dumps([{"id": ["run", "same", "ts"], "tag": "stale"}]))

    canonical_patch, legacy_patch = _paths(canonical, legacy)
    with canonical_patch, legacy_patch:
        assert load_agent_tribes() == {(AgentType.RUNNING, "same", "ts"): "current"}


def test_malformed_canonical_file_does_not_resurrect_legacy(tmp_path: Path) -> None:
    canonical = tmp_path / "agent_tribes.json"
    legacy = tmp_path / "agent_tags.json"
    canonical.write_text("not json")
    legacy.write_text(json.dumps([{"id": ["run", "same", "ts"], "tag": "stale"}]))

    canonical_patch, legacy_patch = _paths(canonical, legacy)
    with canonical_patch, legacy_patch:
        assert load_agent_tribes() == {}


def test_first_mutation_imports_complete_legacy_state(tmp_path: Path) -> None:
    canonical = tmp_path / "agent_tribes.json"
    legacy = tmp_path / "agent_tags.json"
    legacy_payload = [
        {"id": ["run", "scalar", "one"], "tag": "alpha"},
        {"id": ["workflow", "list", "two"], "tags": ["beta", "older"]},
    ]
    legacy.write_text(json.dumps(legacy_payload))

    canonical_patch, legacy_patch = _paths(canonical, legacy)
    with canonical_patch, legacy_patch:
        assert update_agent_tribe((AgentType.RUNNING, "new", "three"), "gamma")
        assert load_agent_tribes() == {
            (AgentType.RUNNING, "scalar", "one"): "alpha",
            (AgentType.WORKFLOW, "list", "two"): "beta",
            (AgentType.RUNNING, "new", "three"): "gamma",
        }

    written = json.loads(canonical.read_text())
    assert all(set(record) == {"id", "tribe"} for record in written)
    assert json.loads(legacy.read_text()) == legacy_payload


def test_unset_imported_assignment_writes_authoritative_canonical_file(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "agent_tribes.json"
    legacy = tmp_path / "agent_tags.json"
    identity = (AgentType.RUNNING, "clear-me", "ts")
    legacy.write_text(json.dumps([{"id": ["run", "clear-me", "ts"], "tag": "stale"}]))

    canonical_patch, legacy_patch = _paths(canonical, legacy)
    with canonical_patch, legacy_patch:
        assert update_agent_tribe_assignment(identity, None)
        assert load_agent_tribes() == {}

    assert json.loads(canonical.read_text()) == []
    assert legacy.exists()


def test_replacement_and_round_trip_emit_only_tribe_keys(tmp_path: Path) -> None:
    canonical = tmp_path / "agent_tribes.json"
    legacy = tmp_path / "agent_tags.json"
    identity = (AgentType.RUNNING, "replace", "ts")

    canonical_patch, legacy_patch = _paths(canonical, legacy)
    with canonical_patch, legacy_patch:
        assert save_agent_tribes({identity: "before"})
        assert update_agent_tribe(identity, "after")
        assert load_agent_tribes() == {identity: "after"}

    assert json.loads(canonical.read_text()) == [
        {"id": ["run", "replace", "ts"], "tribe": "after"}
    ]


def test_concurrent_mutations_preserve_every_assignment(tmp_path: Path) -> None:
    canonical = tmp_path / "agent_tribes.json"
    legacy = tmp_path / "agent_tags.json"
    barrier = threading.Barrier(8)

    from sase.ace import agent_tribes

    original_save = agent_tribes.save_agent_tribes

    def slow_save(
        tribes: dict[tuple[AgentType, str, str | None], str],
    ) -> bool:
        time.sleep(0.005)  # sase-test-wait: concurrent save race window
        return original_save(tribes)

    def update(index: int) -> bool:
        barrier.wait()
        return update_agent_tribe(
            (AgentType.RUNNING, f"agent-{index}", str(index)),
            f"tribe-{index}",
        )

    canonical_patch, legacy_patch = _paths(canonical, legacy)
    with (
        canonical_patch,
        legacy_patch,
        patch("sase.ace.agent_tribes.save_agent_tribes", side_effect=slow_save),
        ThreadPoolExecutor(max_workers=8) as executor,
    ):
        assert all(executor.map(update, range(8)))
        stored = load_agent_tribes()

    assert stored == {
        (AgentType.RUNNING, f"agent-{index}", str(index)): f"tribe-{index}"
        for index in range(8)
    }
