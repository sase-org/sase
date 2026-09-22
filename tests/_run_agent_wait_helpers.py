"""Shared helpers for run-agent wait marker lifecycle tests.

Not a conftest so split test modules opt in by importing directly.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from tests._agent_names_fixtures import make_agent


@contextmanager
def patch_index_updates(side_effect: Callable[[str], None]) -> Iterator[None]:
    """Observe Tier 1 index refreshes from both wait modules.

    ``waiting.json`` is published by ``run_agent_wait_markers`` while the wait
    barrier removes it inline, so both bindings must be intercepted.
    """
    with (
        patch(
            "sase.axe.run_agent_wait.update_agent_artifact_index_for_marker_mutation",
            side_effect=side_effect,
        ),
        patch(
            "sase.axe.run_agent_wait_markers."
            "update_agent_artifact_index_for_marker_mutation",
            side_effect=side_effect,
        ),
    ):
        yield


def make_waiter(base: Path, project: str = "proj") -> Path:
    artifact_dir = base / ".sase/projects" / project / "artifacts/ace-run/waiter"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps({"pid": 123}),
        encoding="utf-8",
    )
    return artifact_dir


def make_submitted_planner(base: Path, timestamp: str, name: str) -> Path:
    """Create a submitted-and-waiting planner artifact (no done.json)."""
    artifact_dir = make_agent(
        base,
        "proj",
        timestamp,
        name,
        workflow_name=name,
        agent_family=name,
        role_suffix="--plan",
    )
    meta_path = artifact_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["plan"] = True
    meta["plan_submitted_at"] = ["2026-06-25T18:47:16+00:00"]
    meta["plan_path"] = "sdd/plans/202606/example.md"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    (artifact_dir / "plan_path.json").write_text(
        json.dumps({"plan_path": "sdd/plans/202606/example.md"}),
        encoding="utf-8",
    )
    return artifact_dir
