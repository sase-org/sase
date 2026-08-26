"""Helpers for artifact link store tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.sdd.artifact_link_store import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    ArtifactLinkStore,
)
from tests._conftest_environment import redirect_sase_home


def _row(
    source: str = "plan:202608/a.md",
    relation: str = "implements",
    target: str = "plan:202608/b.md",
    *,
    origin: str = "manual",
    description: str = "extends the ref contract this epic landed",
    created_by: str = "bbugyi200.athena.y2",
    created_at: str = "2026-08-18T23:40:00Z",
    uses: int = 1,
) -> dict[str, object]:
    return {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "source_ref": source,
        "relation": relation,
        "target_ref": target,
        "description": description,
        "origin": origin,
        "created_by": created_by,
        "created_at": created_at,
        "uses": uses,
    }


def _store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ArtifactLinkStore:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    plans.mkdir()
    research.mkdir()
    return ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans, "research": research},
    )


def _plan_index(tmp_path: Path, stem: str) -> Path:
    return tmp_path / "plans" / "links" / "202608" / f"{stem}.json"
