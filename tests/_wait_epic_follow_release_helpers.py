"""Shared release-decision fixtures for wait-epic-follow release tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    resolve_wait_release,
)
from tests._agent_names_fixtures import make_agent

NOW = 1_800_000_000.0


def build_release_index(*artifact_dirs: Path) -> WaitDependencyIndex:
    index = WaitDependencyIndex.empty()
    index.add_many(
        (
            artifact_dir,
            json.loads((artifact_dir / "agent_meta.json").read_text(encoding="utf-8")),
            "proj",
        )
        for artifact_dir in artifact_dirs
    )
    return index


def make_release_planner(
    tmp_path: Path,
    suffix: str,
    name: str = "planner",
    *,
    done: bool = True,
    outcome: str | None = "completed",
    extra_meta: dict[str, object] | None = None,
) -> Path:
    return make_agent(
        tmp_path,
        "proj",
        suffix,
        name,
        agent_session="planner",
        done=done,
        outcome=outcome,
        extra_meta=extra_meta,
    )


def make_release_waiter(
    tmp_path: Path,
    suffix: str = "waiter",
    *,
    extra_meta: dict[str, object] | None = None,
) -> Path:
    artifact_dir = (
        tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / suffix
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    meta: dict[str, object] = {"name": "waiter", "model": "test"}
    if extra_meta:
        meta.update(extra_meta)
    (artifact_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return artifact_dir


def make_release_marker(
    waiting_for: list[str],
    armed: list[str] | None,
    **extra: Any,
) -> dict[str, Any]:
    marker: dict[str, Any] = {"waiting_for": list(waiting_for)}
    if armed is not None:
        marker["wait_for_epics_of"] = list(armed)
    marker.update(extra)
    return marker


def decide_release(
    index: WaitDependencyIndex,
    marker: dict[str, Any],
    waiter_dir: Path,
    *,
    closed: frozenset[str] | None = None,
    dismissed: Path | None = None,
    now: float = NOW,
) -> Any:
    return resolve_wait_release(
        index,
        marker,
        waiter_dir=waiter_dir,
        closed_bead_ids=closed,
        now=now,
        dismissed_artifact_dir=dismissed,
        fresh_index=lambda: index,
    )


def write_release_argv(planner: Path, now: float = NOW) -> None:
    (planner / "epic_launch_argv.json").write_text(
        json.dumps(
            {"argv": ["sase", "bead", "work", "202610/epic.md", "--yes-to-all"]}
        ),
        encoding="utf-8",
    )
    os.utime(planner / "epic_launch_argv.json", (now, now))
