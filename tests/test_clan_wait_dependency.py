"""Clan aggregation in the runner's wait-dependency index."""

from __future__ import annotations

import json
from pathlib import Path

from sase.core.wait_dependency_resolution import build_wait_dependency_index


def _member(
    projects_root: Path,
    timestamp: str,
    name: str,
    *,
    generation: str,
    done: bool,
) -> Path:
    artifact_dir = projects_root / "proj/artifacts/ace-run" / timestamp
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": name,
                "agent_clan": "research",
                "agent_clan_generation": generation,
            }
        )
    )
    if done:
        (artifact_dir / "done.json").write_text(json.dumps({"outcome": "completed"}))
    return artifact_dir


def test_wait_on_clan_requires_every_member(tmp_path: Path) -> None:
    first = _member(
        tmp_path,
        "20260717010101",
        "research.one",
        generation="20260717010000",
        done=True,
    )
    second = _member(
        tmp_path,
        "20260717010202",
        "research.two",
        generation="20260717010000",
        done=False,
    )
    index = build_wait_dependency_index("proj", projects_root=tmp_path)

    assert not index.is_resolved("research")
    assert index.is_resolved("research", exclude_artifact_dir=second)
    (second / "done.json").write_text(json.dumps({"outcome": "completed"}))
    index = build_wait_dependency_index("proj", projects_root=tmp_path)
    assert index.is_resolved("research")
    assert first != second


def test_wait_on_clan_uses_newest_generation(tmp_path: Path) -> None:
    _member(
        tmp_path,
        "20260717010101",
        "research.old",
        generation="20260717010000",
        done=False,
    )
    _member(
        tmp_path,
        "20260717020101",
        "research.new",
        generation="20260717020000",
        done=True,
    )

    index = build_wait_dependency_index("proj", projects_root=tmp_path)

    assert index.is_resolved("research")
