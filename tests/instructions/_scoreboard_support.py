"""Shared fixtures for scoreboard coverage tests.

This is a private helper module: the names it defines are public on
purpose so the split ``test_scoreboard_*`` modules can import them
without crossing a ``_``-prefixed boundary. Test-only helpers used by
a single module live in that module instead.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.instructions import coverage as coverage_mod
from sase.instructions._runs import ScoredRun
from sase.instructions.manifests import RunManifest

RENDERED = "2026-10-06T12:00:00Z"
COVERED_START = datetime(2026, 10, 6, 12, 1, tzinfo=UTC)
UNCOVERED_START = datetime(2026, 10, 6, 11, 59, tzinfo=UTC)
RUN_START = datetime(2026, 10, 6, 11, 0, tzinfo=UTC)
RUN_END = datetime(2026, 10, 6, 13, 0, tzinfo=UTC)
WORKSPACE = "/work/synthetic"
SESSION_TS = "2026-10-06T12:01:00Z"


def make_run(
    provider: str,
    name: str,
    artifacts: Path,
    *,
    workspace: str = WORKSPACE,
    started_at: datetime = RUN_START,
) -> ScoredRun:
    return ScoredRun(
        provider=provider,
        name=name,
        workspace_dir=workspace,
        artifact_dir=str(artifacts),
        started_at=started_at,
        ended_at=RUN_END,
        project="fixture",
    )


def make_record(manifest: dict[str, Any], artifacts: Path, seq: int = 0) -> Any:
    entry = RunManifest(
        seq=seq,
        provider=str(manifest["facts"]["provider"]),
        bundle_path=artifacts / "instructions" / f"{seq:02d}-x.md",
        manifest_path=artifacts / "instructions" / f"{seq:02d}-x.json",
        manifest=manifest,
    )
    record = coverage_mod.record_from_entry(entry, artifacts)
    assert record is not None
    return record


__all__ = [
    "COVERED_START",
    "RENDERED",
    "RUN_END",
    "RUN_START",
    "SESSION_TS",
    "UNCOVERED_START",
    "WORKSPACE",
    "make_record",
    "make_run",
]
