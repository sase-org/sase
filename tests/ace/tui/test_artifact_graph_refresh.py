"""Targeted unified artifact graph refresh tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from sase.ace.tui import artifact_graph_refresh
from sase.core.artifact_wire import (
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ARTIFACT_SOURCE_AGENT_ARTIFACT,
    ARTIFACT_SOURCE_AGENT_CREATED_FILE,
    ARTIFACT_SOURCE_AGENT_THOUGHT,
    ARTIFACT_SOURCE_BEAD_STORE,
    ARTIFACT_SOURCE_CHANGESPEC,
    ARTIFACT_SOURCE_COMMIT,
    ARTIFACT_SOURCE_DIRECTORY,
    ARTIFACT_SOURCE_PROJECT_FILE,
    ArtifactMutationResultWire,
    ArtifactRebuildRequestWire,
)


def _mutation() -> ArtifactMutationResultWire:
    return ArtifactMutationResultWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        operation="rebuild",
    )


def test_refresh_paths_targets_agent_marker_directory(
    monkeypatch, tmp_path: Path
) -> None:
    marker = (
        tmp_path
        / "home"
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "codex"
        / "20260505120000"
        / "agent_meta.json"
    )
    marker.parent.mkdir(parents=True)
    marker.write_text("{}")
    mock_builder = Mock(return_value=ArtifactRebuildRequestWire())
    mock_rebuild = Mock(return_value=_mutation())
    monkeypatch.setattr(
        artifact_graph_refresh.artifact_facade,
        "artifact_rebuild_request",
        mock_builder,
    )
    monkeypatch.setattr(
        artifact_graph_refresh.artifact_facade,
        "artifact_rebuild",
        mock_rebuild,
    )

    artifact_graph_refresh.refresh_artifact_graph_for_paths(
        "/tmp/artifacts.sqlite", [marker]
    )

    mock_builder.assert_called_once_with(
        target_path=None,
        artifact_dir=marker.parent,
        include_sources=(
            ARTIFACT_SOURCE_AGENT_ARTIFACT,
            ARTIFACT_SOURCE_AGENT_CREATED_FILE,
            ARTIFACT_SOURCE_AGENT_THOUGHT,
        ),
        beads_dir=None,
    )
    mock_rebuild.assert_called_once_with(
        "/tmp/artifacts.sqlite", mock_builder.return_value
    )


def test_refresh_paths_dedupes_by_normalized_agent_context(
    monkeypatch, tmp_path: Path
) -> None:
    artifact_dir = (
        tmp_path
        / "home"
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "codex"
        / "20260505120000"
    )
    artifact_dir.mkdir(parents=True)
    first = artifact_dir / "agent_meta.json"
    second = artifact_dir / "done.json"
    first.write_text("{}")
    second.write_text("{}")
    monkeypatch.chdir(tmp_path)
    mock_builder = Mock(return_value=ArtifactRebuildRequestWire())
    monkeypatch.setattr(
        artifact_graph_refresh.artifact_facade,
        "artifact_rebuild_request",
        mock_builder,
    )
    monkeypatch.setattr(
        artifact_graph_refresh.artifact_facade,
        "artifact_rebuild",
        Mock(return_value=_mutation()),
    )

    artifact_graph_refresh.refresh_artifact_graph_for_paths(
        "/tmp/artifacts.sqlite",
        [
            Path("home/.sase/projects/proj/artifacts/codex/20260505120000")
            / "agent_meta.json",
            second,
        ],
    )

    mock_builder.assert_called_once_with(
        target_path=None,
        artifact_dir=artifact_dir,
        include_sources=(
            ARTIFACT_SOURCE_AGENT_ARTIFACT,
            ARTIFACT_SOURCE_AGENT_CREATED_FILE,
            ARTIFACT_SOURCE_AGENT_THOUGHT,
        ),
        beads_dir=None,
    )


def test_agent_created_file_classifies_to_artifact_dir(tmp_path: Path) -> None:
    created_file = (
        tmp_path
        / "home"
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "codex"
        / "20260505120000"
        / "created_files"
        / "src"
        / "main.py"
    )
    created_file.parent.mkdir(parents=True)
    created_file.write_text("print('ok')\n")

    target = artifact_graph_refresh.classify_artifact_graph_refresh_path(created_file)

    assert target is not None
    assert target.key == ("agent", str(created_file.parents[2]))
    assert target.artifact_dir == created_file.parents[2]
    assert target.target_path is None
    assert target.include_sources == (
        ARTIFACT_SOURCE_AGENT_ARTIFACT,
        ARTIFACT_SOURCE_AGENT_CREATED_FILE,
        ARTIFACT_SOURCE_AGENT_THOUGHT,
    )


def test_refresh_paths_targets_project_file(monkeypatch, tmp_path: Path) -> None:
    project_file = tmp_path / "proj.gp"
    project_file.write_text("NAME: alpha\n")
    mock_builder = Mock(return_value=ArtifactRebuildRequestWire())
    monkeypatch.setattr(
        artifact_graph_refresh.artifact_facade,
        "artifact_rebuild_request",
        mock_builder,
    )
    monkeypatch.setattr(
        artifact_graph_refresh.artifact_facade,
        "artifact_rebuild",
        Mock(return_value=_mutation()),
    )

    artifact_graph_refresh.refresh_artifact_graph_for_paths(
        "/tmp/artifacts.sqlite", [project_file]
    )

    mock_builder.assert_called_once_with(
        target_path=project_file,
        artifact_dir=None,
        include_sources=(
            ARTIFACT_SOURCE_PROJECT_FILE,
            ARTIFACT_SOURCE_CHANGESPEC,
            ARTIFACT_SOURCE_COMMIT,
        ),
        beads_dir=None,
    )


def test_refresh_paths_targets_bead_store(monkeypatch, tmp_path: Path) -> None:
    issues = tmp_path / "sdd" / "beads" / "issues.jsonl"
    issues.parent.mkdir(parents=True)
    issues.write_text("")
    mock_builder = Mock(return_value=ArtifactRebuildRequestWire())
    monkeypatch.setattr(
        artifact_graph_refresh.artifact_facade,
        "artifact_rebuild_request",
        mock_builder,
    )
    monkeypatch.setattr(
        artifact_graph_refresh.artifact_facade,
        "artifact_rebuild",
        Mock(return_value=_mutation()),
    )

    artifact_graph_refresh.refresh_artifact_graph_for_paths(
        "/tmp/artifacts.sqlite", [issues]
    )

    mock_builder.assert_called_once_with(
        target_path=issues,
        artifact_dir=None,
        include_sources=(ARTIFACT_SOURCE_BEAD_STORE,),
        beads_dir=issues.parent,
    )


def test_refresh_paths_targets_direct_directory(monkeypatch, tmp_path: Path) -> None:
    directory = tmp_path / "docs"
    directory.mkdir()
    mock_builder = Mock(return_value=ArtifactRebuildRequestWire())
    monkeypatch.setattr(
        artifact_graph_refresh.artifact_facade,
        "artifact_rebuild_request",
        mock_builder,
    )
    monkeypatch.setattr(
        artifact_graph_refresh.artifact_facade,
        "artifact_rebuild",
        Mock(return_value=_mutation()),
    )

    artifact_graph_refresh.refresh_artifact_graph_for_paths(
        "/tmp/artifacts.sqlite", [directory]
    )

    mock_builder.assert_called_once_with(
        target_path=directory,
        artifact_dir=None,
        include_sources=(ARTIFACT_SOURCE_DIRECTORY,),
        beads_dir=None,
    )


def test_missing_artifact_refresh_prefers_agent_artifact_dir(
    monkeypatch, tmp_path: Path
) -> None:
    artifact_dir = tmp_path / "artifacts" / "codex" / "20260505120000"
    artifact_dir.mkdir(parents=True)
    context_path = tmp_path / "project.gp"
    context_path.write_text("NAME: alpha\n")
    mock_builder = Mock(return_value=ArtifactRebuildRequestWire())
    monkeypatch.setattr(
        artifact_graph_refresh.artifact_facade,
        "artifact_rebuild_request",
        mock_builder,
    )
    monkeypatch.setattr(
        artifact_graph_refresh.artifact_facade,
        "artifact_rebuild",
        Mock(return_value=_mutation()),
    )

    artifact_graph_refresh.refresh_artifact_graph_for_missing_artifact(
        "/tmp/artifacts.sqlite",
        "named-agent",
        context_path=context_path,
        artifact_dir=artifact_dir,
    )

    mock_builder.assert_called_once_with(
        target_path=None,
        artifact_dir=artifact_dir,
        include_sources=(
            ARTIFACT_SOURCE_AGENT_ARTIFACT,
            ARTIFACT_SOURCE_AGENT_CREATED_FILE,
            ARTIFACT_SOURCE_AGENT_THOUGHT,
        ),
        beads_dir=None,
    )


def test_missing_artifact_refresh_without_context_avoids_agent_sources(
    monkeypatch,
) -> None:
    mock_builder = Mock(return_value=ArtifactRebuildRequestWire())
    monkeypatch.setattr(
        artifact_graph_refresh.artifact_facade,
        "artifact_rebuild_request",
        mock_builder,
    )
    monkeypatch.setattr(
        artifact_graph_refresh.artifact_facade,
        "artifact_rebuild",
        Mock(return_value=_mutation()),
    )

    artifact_graph_refresh.refresh_artifact_graph_for_missing_artifact(
        "/tmp/artifacts.sqlite",
        "changespec:current",
    )

    mock_builder.assert_called_once_with(
        target_path=None,
        artifact_dir=None,
        include_sources=(
            ARTIFACT_SOURCE_PROJECT_FILE,
            ARTIFACT_SOURCE_CHANGESPEC,
            ARTIFACT_SOURCE_COMMIT,
        ),
        beads_dir=None,
    )
