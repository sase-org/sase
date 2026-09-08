"""Tests for pager owner provenance and context assembly."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.artifact_ref_models import ArtifactRefDocumentOwner
from sase.pager.link_context import LinkAnchor, LinkResolutionContext
from sase.pager.owner import artifact_context_for_link_context


def test_artifact_context_for_link_context_passes_owner_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "viewer"
    workspace.mkdir()
    captured: dict[str, object] = {}

    def fake_artifact_ref_context(
        directory: Path, workspace_num: int, project: str | None = None
    ) -> object:
        captured["directory"] = Path(directory)
        captured["workspace_num"] = workspace_num
        captured["project"] = project
        return object()

    monkeypatch.setattr(
        "sase.artifact_ref_context.artifact_ref_context",
        fake_artifact_ref_context,
    )

    assembled = artifact_context_for_link_context(
        LinkResolutionContext(
            anchors=(LinkAnchor(directory=workspace),),
            owner=ArtifactRefDocumentOwner(project_key="bob-cli"),
        )
    )

    assert assembled is not None
    assert captured["project"] == "bob-cli"
    assert captured["directory"] == workspace.resolve()
    assert captured["workspace_num"] == 1
