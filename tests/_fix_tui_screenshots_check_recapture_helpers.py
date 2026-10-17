"""Shared fixtures for the check-mode screenshot recapture tests."""

from __future__ import annotations

import json
from pathlib import Path

from tests._fix_tui_screenshots_helpers import (
    ACE_NODE,
    PAGER_NODE,
    FakeRunner,
    ScriptedCapture,
    commit_all,
    init_repo,
    make_png,
    write_golden,
)


def read_manifest(repo: Path) -> dict[object, object]:
    paths = sorted(
        (repo / ".pytest_cache/sase-visual/runs").glob("*/manifest.json"),
        key=lambda path: path.stat().st_mtime_ns,
    )
    assert paths
    return json.loads(paths[-1].read_text(encoding="utf-8"))


def pair(repo: Path, *, candidate: bytes) -> tuple[bytes, Path, FakeRunner]:
    init_repo(repo)
    red = make_png(1, 1, (255, 0, 0, 255))
    ace = write_golden(repo, "ace", "shot.png", red)
    write_golden(repo, "pager", "shot.png", red)
    commit_all(repo)
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "shot", "ace", candidate),
            ScriptedCapture(PAGER_NODE, "shot", "pager", red),
        ],
        repo_root=repo,
    )
    return red, ace, runner
