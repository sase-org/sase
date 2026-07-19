"""Shared artifact access helpers for agent-name lookups."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sase.core.paths import sase_projects_dir

SUCCESS_OUTCOME = "completed"


def ace_run_scan_options() -> Any:
    """Return the scan-facade options for ace-run-only name lookups.

    Imported lazily to avoid the agent-scan facade pulling in the TUI
    loader package at ``sase.agent`` import time (the loader package
    transitively depends back on ``sase.agent.names``).
    """
    from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire

    return AgentArtifactScanOptionsWire(
        only_workflow_dirs=("ace-run",),
        include_prompt_step_markers=False,
        include_raw_prompt_snippets=False,
    )


def projects_root() -> Path:
    return sase_projects_dir()


def iter_ace_run_artifact_dirs(*, newest_first: bool = False) -> Iterator[Path]:
    projects_dir = projects_root()
    if not projects_dir.exists():
        return
    from sase.core.agent_artifact_paths import iter_agent_artifact_dirs

    try:
        project_iter = projects_dir.iterdir()
    except OSError:
        return
    for project_dir in project_iter:
        if not project_dir.is_dir():
            continue
        yield from iter_agent_artifact_dirs(
            project_dir.name,
            "ace-run",
            projects_root=projects_dir,
            newest_first=newest_first,
        )


def read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def done_outcome(artifact_dir: Path) -> str | None:
    done_data = read_json_dict(artifact_dir / "done.json")
    if done_data is None:
        return None
    outcome = done_data.get("outcome")
    return outcome if isinstance(outcome, str) else None


def meta_parent_timestamp(meta: dict[str, Any]) -> str | None:
    value = meta.get("parent_timestamp")
    return value if isinstance(value, str) and value else None
