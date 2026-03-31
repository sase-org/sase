"""Tests for changespec helper functions."""

from unittest.mock import MagicMock, patch

import pytest

from sase.workspace_provider.changespec import (
    _build_description,
    _derive_cl_name,
    _get_commits_ahead,
    _save_committed_diff,
)


# --- _get_commits_ahead ---


def test_get_commits_ahead_returns_oldest_first() -> None:
    mock_result = MagicMock(returncode=0, stdout="third\nsecond\nfirst\n")
    with patch(
        "sase.workspace_provider.changespec.subprocess.run", return_value=mock_result
    ):
        assert _get_commits_ahead("origin/main", "agent_1") == [
            "first",
            "second",
            "third",
        ]


def test_get_commits_ahead_empty_on_no_output() -> None:
    mock_result = MagicMock(returncode=0, stdout="  \n")
    with patch(
        "sase.workspace_provider.changespec.subprocess.run", return_value=mock_result
    ):
        assert _get_commits_ahead("origin/main", "agent_1") == []


# --- _derive_cl_name ---


@pytest.mark.parametrize(
    ("subjects", "expected"),
    [
        ([], "myproj_agent_changes"),
        (["feat: add login page"], "myproj_add_login_page"),
        (["Fix: resolve crash on startup"], "myproj_resolve_crash_on_startup"),
        (["chore:   update deps"], "myproj_update_deps"),
        (["plain commit message"], "myproj_plain_commit_message"),
        (["feat: "], "myproj_agent_changes"),
        (["a" * 100], f"myproj_{'a' * 50}"),
        (["feat: Hello--World!!"], "myproj_hello_world"),
    ],
)
def test_derive_cl_name(subjects: list[str], expected: str) -> None:
    assert _derive_cl_name("myproj", subjects) == expected


# --- _build_description ---


def test_build_description_no_commits() -> None:
    assert _build_description([]) == "Agent changes"


def test_build_description_multiple_commits() -> None:
    result = _build_description(["first", "second", "third"])
    assert result == "1. first\n2. second\n3. third"


# --- _save_committed_diff ---


def test_save_committed_diff_returns_none_on_empty(tmp_path: object) -> None:
    mock_result = MagicMock(returncode=0, stdout="")
    with patch(
        "sase.workspace_provider.changespec.subprocess.run", return_value=mock_result
    ):
        assert (
            _save_committed_diff("cl", "origin/main", "agent_1", "260101_120000")
            is None
        )


def test_save_committed_diff_writes_file(tmp_path: object) -> None:
    diffs_dir = str(tmp_path)
    mock_result = MagicMock(returncode=0, stdout="diff --git a/f b/f\n+hello\n")
    with (
        patch(
            "sase.workspace_provider.changespec.subprocess.run",
            return_value=mock_result,
        ),
        patch(
            "sase.workspace_provider.changespec.ensure_sase_directory",
            return_value=diffs_dir,
        ),
        patch(
            "sase.workspace_provider.changespec.shorten_path", side_effect=lambda p: p
        ),
    ):
        path = _save_committed_diff("my_cl", "origin/main", "agent_1", "260101_120000")
        assert path is not None
        assert path.endswith(".diff")


def test_save_committed_diff_falls_back_to_vcs_provider(tmp_path: object) -> None:
    """When git diff fails, falls back to VCS provider's committed_diff()."""
    diffs_dir = str(tmp_path)
    git_fail = MagicMock(returncode=1, stdout="")
    mock_provider = MagicMock()
    mock_provider.committed_diff.return_value = (True, "diff from provider\n")

    with (
        patch(
            "sase.workspace_provider.changespec.subprocess.run",
            return_value=git_fail,
        ),
        patch(
            "sase.vcs_provider.get_vcs_provider",
            return_value=mock_provider,
        ),
        patch(
            "sase.workspace_provider.changespec.ensure_sase_directory",
            return_value=diffs_dir,
        ),
        patch(
            "sase.workspace_provider.changespec.shorten_path", side_effect=lambda p: p
        ),
    ):
        path = _save_committed_diff("my_cl", "HEAD~1", "foobar", "260101_120000")
        assert path is not None
        assert path.endswith(".diff")
        mock_provider.committed_diff.assert_called_once()
