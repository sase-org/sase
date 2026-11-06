"""Shared fixtures for keep-work recovery bootstrap tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.agent.hijack._recovery_successor_descriptor import (
    build_recovery_descriptor,
)


def lineage(**overrides: Any) -> dict[str, str]:
    payload = {
        "hijack_id": "hij-1",
        "from_rung": "claude/opus@high",
        "to_rung": "claude/opus@high",
        "predecessor": "acme--3",
    }
    payload.update(overrides)
    return payload


def descriptor(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = build_recovery_descriptor(
        hijack_id="hij-1",
        launch_identity="launch-1",
        concrete_target="claude/opus@high",
        reserved_successor_name="acme--4",
        project="proj",
        workspace_dir="/ws/3",
        lineage=lineage(),
        workspace_num=3,
    )
    payload.update(overrides)
    return payload


def write_meta(root: Path, **fields: Any) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "agent_meta.json").write_text(json.dumps(dict(fields)))


def write_baseline(root: Path, fingerprints: dict[str, Any] | None = None) -> None:
    from sase.llm_provider.commit_finalizer_baseline import BASELINE_FILENAME

    root.mkdir(parents=True, exist_ok=True)
    payload = (
        fingerprints
        if fingerprints is not None
        else {"/ws/3": {"a.txt": ["abc123", None]}}
    )
    (root / BASELINE_FILENAME).write_text(json.dumps(payload))
