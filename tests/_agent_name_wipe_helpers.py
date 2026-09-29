"""Shared fixtures for forced-reuse agent-name wipe tests.

Not a conftest so files opt in by importing the helpers directly. Names are
public so the ``test_agent_name_wipe_*`` split modules can share them without
importing ``_``-prefixed names across files.
"""

from __future__ import annotations

import json
from pathlib import Path


def make_wipe_artifact(
    home: Path,
    suffix: str,
    name: str,
    *,
    project: str = "proj",
    done: bool = False,
    done_name: str | None = None,
    day_sharded: bool = False,
    meta: dict[str, object] | None = None,
) -> Path:
    """Create a fake agent artifact directory with agent_meta.json."""
    workflow_dir = home / ".sase" / "projects" / project / "artifacts" / "ace-run"
    path = (
        workflow_dir / suffix[:6] / suffix[6:8] / suffix
        if day_sharded
        else workflow_dir / suffix
    )
    path.mkdir(parents=True, exist_ok=True)
    payload = {"name": name, "workflow_name": name, **(meta or {})}
    (path / "agent_meta.json").write_text(json.dumps(payload), encoding="utf-8")
    if done:
        (path / "done.json").write_text(
            json.dumps({"name": done_name or name, "outcome": "completed"}),
            encoding="utf-8",
        )
    return path


def make_wipe_bundle(home: Path, suffix: str, name: str, **extra: object) -> Path:
    """Create a fake dismissed-bundle file for a wipe test."""
    path = home / ".sase" / "dismissed_bundles" / "202605" / f"{suffix}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"raw_suffix": suffix, "agent_name": name, "workflow_name": name, **extra}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
