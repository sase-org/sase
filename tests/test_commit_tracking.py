"""Tests for idempotent commit tracking."""

from __future__ import annotations

import os
from pathlib import Path

from sase.workflows.commit.commit_tracking import (
    _sdd_repo_name_for_commit_cwd,
    append_commits_entry,
)


def test_append_commits_entry_idempotent_with_expected_entry_id(
    tmp_path: Path,
) -> None:
    """When the COMMITS drawer already has the entry, no new line is appended."""
    project_file = tmp_path / "proj.sase"
    initial = (
        "NAME: test-cl\n"
        "DESCRIPTION:\n  desc\n"
        "COMMITS:\n"
        "  (99) existing note\n"
        "STATUS: Pending\n"
    )
    project_file.write_text(initial)
    mtime_before = os.path.getmtime(project_file)

    result = append_commits_entry(
        str(project_file),
        "test-cl",
        {"message": "won't be added"},
        "create_commit",
        None,
        expected_entry_id="99",
    )

    assert result == "99"
    assert project_file.read_text() == initial
    assert os.path.getmtime(project_file) == mtime_before


def test_append_commits_entry_appends_when_expected_entry_id_missing(
    tmp_path: Path,
) -> None:
    """When the expected ID is not present, the entry is appended normally."""
    project_file = tmp_path / "proj.sase"
    project_file.write_text(
        "NAME: test-cl\nDESCRIPTION:\n  desc\nCOMMITS:\nSTATUS: Pending\n"
    )

    result = append_commits_entry(
        str(project_file),
        "test-cl",
        {"message": "first commit"},
        "create_commit",
        None,
        expected_entry_id="99",
    )

    assert result == "1"
    assert "first commit" in project_file.read_text()


def test_custom_sidecar_commit_cwd_uses_role_name(tmp_path: Path) -> None:
    workspace = tmp_path / "sase_17"
    designs = workspace / "sase" / "repos" / "designs" / "202607"

    assert _sdd_repo_name_for_commit_cwd(str(designs), str(workspace)) == "designs"
