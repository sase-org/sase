"""Tests for ACE artifact-path classification helpers."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.actions.event_refresh._artifact_paths import (
    artifact_dir_from_known_marker_path,
    artifact_path_affects_agents,
)


def test_refresh_pulse_under_artifacts_affects_agents(tmp_path: Path) -> None:
    project_pulse = tmp_path / "proj" / "artifacts" / ".ace_refresh_pulse"
    month_pulse = (
        tmp_path / "proj" / "artifacts" / "ace-run" / "202608" / ".ace_refresh_pulse"
    )
    project_pulse.parent.mkdir(parents=True)
    month_pulse.parent.mkdir(parents=True)
    project_pulse.write_text("1", encoding="utf-8")
    month_pulse.write_text("1", encoding="utf-8")

    assert artifact_path_affects_agents(project_pulse) is True
    assert artifact_path_affects_agents(month_pulse) is True
    assert artifact_dir_from_known_marker_path(project_pulse) is None
    assert artifact_dir_from_known_marker_path(month_pulse) is None


def test_unrelated_file_under_artifacts_does_not_affect_agents(tmp_path: Path) -> None:
    path = (
        tmp_path
        / "proj"
        / "artifacts"
        / "ace-run"
        / "202608"
        / "28"
        / "20260828120000"
        / "commit_diffs"
        / "001.diff"
    )
    path.parent.mkdir(parents=True)
    path.write_text("diff", encoding="utf-8")

    assert artifact_path_affects_agents(path) is False
    assert artifact_dir_from_known_marker_path(path) is None
