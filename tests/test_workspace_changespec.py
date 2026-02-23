"""Tests for sase.workspace_changespec."""

from unittest.mock import MagicMock, patch

import pytest

from sase.workspace_changespec import (
    _build_description,
    _derive_cl_name,
    _get_commits_ahead,
    _save_committed_diff,
    create_changespec_for_workflow,
)


# --- _get_commits_ahead ---


def test_get_commits_ahead_returns_oldest_first() -> None:
    mock_result = MagicMock(returncode=0, stdout="third\nsecond\nfirst\n")
    with patch("sase.workspace_changespec.subprocess.run", return_value=mock_result):
        assert _get_commits_ahead("origin/main", "agent_1") == [
            "first",
            "second",
            "third",
        ]


def test_get_commits_ahead_empty_on_no_output() -> None:
    mock_result = MagicMock(returncode=0, stdout="  \n")
    with patch("sase.workspace_changespec.subprocess.run", return_value=mock_result):
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
    with patch("sase.workspace_changespec.subprocess.run", return_value=mock_result):
        assert (
            _save_committed_diff("cl", "origin/main", "agent_1", "260101_120000")
            is None
        )


def test_save_committed_diff_writes_file(tmp_path: object) -> None:
    diffs_dir = str(tmp_path)
    mock_result = MagicMock(returncode=0, stdout="diff --git a/f b/f\n+hello\n")
    with (
        patch("sase.workspace_changespec.subprocess.run", return_value=mock_result),
        patch(
            "sase.workspace_changespec.ensure_sase_directory", return_value=diffs_dir
        ),
        patch("sase.workspace_changespec.shorten_path", side_effect=lambda p: p),
    ):
        path = _save_committed_diff("my_cl", "origin/main", "agent_1", "260101_120000")
        assert path is not None
        assert path.endswith(".diff")


# --- create_changespec_for_workflow ---


def test_create_changespec_for_workflow_no_commits() -> None:
    with patch(
        "sase.workspace_changespec._get_commits_ahead",
        return_value=[],
    ):
        result = create_changespec_for_workflow(
            project_name="proj",
            project_file="/fake/proj.gp",
            checkout_target="origin/main",
            branch_name="swift-falcon",
            prompt="do stuff",
            response="done",
            workflow_name="gh",
        )
        assert result is None


def test_create_changespec_for_workflow_success() -> None:
    with (
        patch(
            "sase.workspace_changespec._get_commits_ahead",
            return_value=["feat: add thing"],
        ),
        patch(
            "sase.workspace_changespec.generate_timestamp", return_value="260101_120000"
        ),
        patch(
            "sase.workspace_changespec.save_chat_history", return_value="~/chats/f.md"
        ),
        patch(
            "sase.workspace_changespec._save_committed_diff",
            return_value="~/diffs/f.diff",
        ),
        patch(
            "sase.workspace_changespec.get_initial_hooks_for_changespec",
            return_value=[],
        ),
        patch("sase.workspace_changespec.get_cl_field_label", return_value="PR"),
        patch(
            "sase.workspace_changespec.add_changespec_to_project_file",
            return_value="proj_add_thing__1",
        ) as mock_add,
        patch("sase.workspace_changespec.subprocess.run"),  # Prevent real git branch -m
    ):
        result = create_changespec_for_workflow(
            project_name="proj",
            project_file="/fake/proj.gp",
            checkout_target="origin/main",
            branch_name="swift-falcon",
            prompt="do stuff",
            response="done",
            workflow_name="gh",
            cl_url="https://github.com/org/repo/pull/1",
        )
        assert result == "proj_add_thing__1"
        mock_add.assert_called_once_with(
            "proj",
            "proj_add_thing",
            "feat: add thing",
            parent=None,
            cl_url="https://github.com/org/repo/pull/1",
            initial_hooks=[],
            initial_commits=[
                (1, "[run] Initial Commit", "~/chats/f.md", "~/diffs/f.diff")
            ],
            cl_label="PR",
        )
