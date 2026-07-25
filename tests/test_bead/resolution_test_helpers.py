"""Helpers that route bead-store resolution through an isolated test checkout."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.workspace_provider.marker import CheckoutMarker, MARKER_DIR, MARKER_FILENAME
from tests.sdd_policy_helpers import set_sdd_policy


def isolate_bead_store_resolution(
    monkeypatch: pytest.MonkeyPatch,
    checkout: Path,
    *,
    primary: Path | None = None,
    workspace_num: int = 1,
    project_name: str = "test-project",
) -> Path:
    """Plant a managed-checkout marker that keeps normal resolution in tmp."""
    checkout.mkdir(parents=True, exist_ok=True)
    resolved_primary = checkout if primary is None else primary
    resolved_primary.mkdir(parents=True, exist_ok=True)

    marker = CheckoutMarker(
        project_name=project_name,
        project_key=project_name,
        workspace_num=workspace_num,
        primary_workspace_dir=str(resolved_primary),
        registry_path=str(resolved_primary / ".sase" / "registry.json"),
    )
    marker_path = checkout / MARKER_DIR / MARKER_FILENAME
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(
        json.dumps(marker.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    set_sdd_policy(monkeypatch, "in_tree")
    monkeypatch.chdir(checkout)
    return resolved_primary
