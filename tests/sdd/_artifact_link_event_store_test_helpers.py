"""Shared factories for artifact-link event-store tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.rust import require_rust_binding
from sase.sdd.artifact_link_store import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    ArtifactLinkStore,
)
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_store_helpers import allow_machine_sidecar_writes


PROJECT_KEY = "gh_sase-org__sase"


def row(
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


def make_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ArtifactLinkStore:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    plans.mkdir()
    research.mkdir()
    return ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={"plan": plans, "research": research},
    )


def edge_event(
    operation_id: str,
    *,
    source: str = "plan:202608/a.md",
    relation: str = "implements",
    target: str = "plan:202608/b.md",
    description: str = "event-backed link",
    origin: str = "manual",
    created_at: str = "2026-09-09T00:00:00Z",
    occurrences: int = 1,
) -> dict[str, object]:
    edge = {
        "kind": "directed",
        "source_ref": source,
        "relation": relation,
        "target_ref": target,
    }
    kind = (
        {
            "type": "observation",
            "edge": edge,
            "description": description,
            "occurrences": occurrences,
        }
        if origin == "read"
        else {
            "type": "edge-put",
            "edge": edge,
            "description": description,
            "observed_operation_ids": [],
        }
    )
    return _canonicalize_event(
        {
            "schema_version": int(
                require_rust_binding("artifact_link_event_schema_version")()
            ),
            "project_key": PROJECT_KEY,
            "operation_id": operation_id,
            "created_by": "agent:event.athena.worker",
            "origin": origin,
            "created_at": created_at,
            "kind": kind,
        }
    )


def remove_event(
    operation_id: str,
    *,
    source: str = "plan:202608/a.md",
    relation: str = "implements",
    target: str = "plan:202608/b.md",
    observed: tuple[str, ...],
) -> dict[str, object]:
    return _canonicalize_event(
        {
            "schema_version": int(
                require_rust_binding("artifact_link_event_schema_version")()
            ),
            "project_key": PROJECT_KEY,
            "operation_id": operation_id,
            "created_by": "agent:event.athena.worker",
            "origin": "manual",
            "created_at": "2026-09-09T00:00:00Z",
            "kind": {
                "type": "edge-remove",
                "edge": {
                    "kind": "directed",
                    "source_ref": source,
                    "relation": relation,
                    "target_ref": target,
                },
                "observed_operation_ids": list(observed),
            },
        }
    )


def write_event(root: Path, event: dict[str, object]) -> Path:
    digest = str(require_rust_binding("artifact_link_event_digest")(event))
    relpath = str(require_rust_binding("artifact_link_event_path_for_digest")(digest))
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        str(require_rust_binding("artifact_link_event_canonical_json")(event)),
        encoding="utf-8",
    )
    return path


def _canonicalize_event(event: dict[str, object]) -> dict[str, object]:
    return dict(require_rust_binding("artifact_link_event_canonicalize")(event))
