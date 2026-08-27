"""Tests for stale artifact-read hint repair."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.actions.hints._artifact_ref_repair import repair_artifact_read_path
from sase.ace.tui.artifact_reads import ArtifactReadRefSpec


def test_repair_artifact_read_path_attempts_primary_workspace_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    primary = tmp_path / "primary"
    workspace.mkdir()
    primary.mkdir()
    recovered = primary / "doc.md"
    recovered.write_text("live", encoding="utf-8")
    attempted_contexts: list[tuple[Path, int]] = []

    def fake_artifact_ref_context(anchor: Path, num: int) -> tuple[Path, int]:
        attempted_contexts.append((anchor, num))
        return (anchor, num)

    def fake_resolve_cli_reference(
        ref: str,
        *,
        context: tuple[Path, int],
    ) -> SimpleNamespace:
        assert ref == "research:202608/design.md"
        status = "exact" if context == (primary, 1) else "missing"
        return SimpleNamespace(
            resolution=SimpleNamespace(status=status),
            path=recovered,
        )

    monkeypatch.setattr(
        "sase.sdd.plan_refs.workspace_context_for_plan_resolution",
        lambda cwd: (workspace, 11),
    )
    monkeypatch.setattr(
        "sase.sdd.files.get_primary_workspace_dir",
        lambda workspace_dir, workspace_num: str(primary),
    )
    monkeypatch.setattr(
        "sase.artifact_ref_context.artifact_ref_context",
        fake_artifact_ref_context,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.references.resolve_cli_reference",
        fake_resolve_cli_reference,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.references.resolved_file_path",
        lambda result: result.path,
    )

    repaired = repair_artifact_read_path(
        ArtifactReadRefSpec(
            ref="research:202608/design.md",
            cwd=str(workspace / "subdir"),
        )
    )

    assert repaired == str(recovered)
    assert attempted_contexts == [(workspace, 11), (primary, 1)]


def test_repair_artifact_read_path_without_cwd_returns_none() -> None:
    assert (
        repair_artifact_read_path(
            ArtifactReadRefSpec(ref="research:202608/design.md", cwd=None)
        )
        is None
    )
