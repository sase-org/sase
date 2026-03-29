"""Tests for sase.workspace_provider.changespec."""

from unittest.mock import MagicMock, patch

import pytest

from sase.workspace_provider.changespec import (
    _build_description,
    _derive_cl_name,
    _get_commits_ahead,
    _save_committed_diff,
    create_changespec_for_workflow,
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


# --- create_changespec_for_workflow ---


def test_create_changespec_for_workflow_no_commits() -> None:
    with patch(
        "sase.workspace_provider.changespec._get_commits_ahead",
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


def test_create_changespec_for_workflow_no_commits_with_fallback() -> None:
    """commit_description fallback is used when git log returns empty."""
    with (
        patch(
            "sase.workspace_provider.changespec._get_commits_ahead",
            return_value=[],
        ),
        patch(
            "sase.workspace_provider.changespec.generate_timestamp",
            return_value="260101_120000",
        ),
        patch(
            "sase.workspace_provider.changespec.save_chat_history",
            return_value="~/chats/f.md",
        ),
        patch(
            "sase.workspace_provider.changespec._save_committed_diff",
            return_value=None,
        ),
        patch(
            "sase.workspace_provider.changespec.get_initial_hooks_for_changespec",
            return_value=[],
        ),
        patch("sase.workspace_provider.changespec.get_change_label", return_value="CL"),
        patch(
            "sase.workspace_provider.changespec.add_changespec_to_project_file",
            return_value="proj_my_cl_1",
        ) as mock_add,
    ):
        result = create_changespec_for_workflow(
            project_name="proj",
            project_file="/fake/proj.gp",
            checkout_target="HEAD~1",
            branch_name="foobar",
            prompt="",
            response="",
            workflow_name="sase_commit",
            cl_url="http://cl/123",
            cl_name="proj_my_cl",
            commit_description="Add new feature",
        )
        assert result == "proj_my_cl_1"
        # Should use commit_description as the commit subject
        mock_add.assert_called_once()
        call_kwargs = mock_add.call_args
        assert call_kwargs[0][1] == "proj_my_cl"  # cl_name passed through
        assert call_kwargs[0][2] == "Add new feature"  # description from fallback


def test_create_changespec_for_workflow_no_commits_no_fallback() -> None:
    """Returns None when git log is empty and no commit_description provided."""
    with patch(
        "sase.workspace_provider.changespec._get_commits_ahead",
        return_value=[],
    ):
        result = create_changespec_for_workflow(
            project_name="proj",
            project_file="/fake/proj.gp",
            checkout_target="HEAD~1",
            branch_name="foobar",
            prompt="",
            response="",
            workflow_name="sase_commit",
            commit_description="",
        )
        assert result is None


def test_create_changespec_for_workflow_passes_parent() -> None:
    """Parent argument is forwarded to add_changespec_to_project_file."""
    with (
        patch(
            "sase.workspace_provider.changespec._get_commits_ahead",
            return_value=["feat: add thing"],
        ),
        patch(
            "sase.workspace_provider.changespec.generate_timestamp",
            return_value="260101_120000",
        ),
        patch(
            "sase.workspace_provider.changespec.save_chat_history",
            return_value="~/chats/f.md",
        ),
        patch(
            "sase.workspace_provider.changespec._save_committed_diff",
            return_value=None,
        ),
        patch(
            "sase.workspace_provider.changespec.get_initial_hooks_for_changespec",
            return_value=[],
        ),
        patch("sase.workspace_provider.changespec.get_change_label", return_value="CL"),
        patch(
            "sase.workspace_provider.changespec.add_changespec_to_project_file",
            return_value="proj_child_1",
        ) as mock_add,
    ):
        result = create_changespec_for_workflow(
            project_name="proj",
            project_file="/fake/proj.gp",
            checkout_target="HEAD~1",
            branch_name="foobar",
            prompt="",
            response="",
            workflow_name="sase_commit",
            cl_name="proj_child",
            parent="proj_parent_feature",
        )
        assert result == "proj_child_1"
        mock_add.assert_called_once()
        assert mock_add.call_args.kwargs["parent"] == "proj_parent_feature"


def test_create_changespec_uses_agent_chat_path_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When SASE_AGENT_CHAT_PATH is set, use it instead of creating a new chat file."""
    monkeypatch.setenv("SASE_AGENT_CHAT_PATH", "~/chats/ace-run-260101_120000.md")
    with (
        patch(
            "sase.workspace_provider.changespec._get_commits_ahead",
            return_value=["feat: add thing"],
        ),
        patch(
            "sase.workspace_provider.changespec.generate_timestamp",
            return_value="260101_120000",
        ),
        patch(
            "sase.workspace_provider.changespec.save_chat_history",
        ) as mock_save_chat,
        patch(
            "sase.workspace_provider.changespec._save_committed_diff",
            return_value=None,
        ),
        patch(
            "sase.workspace_provider.changespec.get_initial_hooks_for_changespec",
            return_value=[],
        ),
        patch("sase.workspace_provider.changespec.get_change_label", return_value="CL"),
        patch(
            "sase.workspace_provider.changespec.add_changespec_to_project_file",
            return_value="proj_add_thing_1",
        ) as mock_add,
    ):
        result = create_changespec_for_workflow(
            project_name="proj",
            project_file="/fake/proj.gp",
            checkout_target="origin/main",
            branch_name="agent_1",
            prompt="",
            response="",
            workflow_name="sase_commit",
        )
        assert result == "proj_add_thing_1"
        # save_chat_history should NOT have been called
        mock_save_chat.assert_not_called()
        # The env var path should be used in the COMMITS entry
        mock_add.assert_called_once()
        initial_commits = mock_add.call_args.kwargs["initial_commits"]
        assert initial_commits[0][2] == "~/chats/ace-run-260101_120000.md"


def test_create_changespec_falls_back_without_agent_chat_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When SASE_AGENT_CHAT_PATH is not set, fall back to save_chat_history."""
    monkeypatch.delenv("SASE_AGENT_CHAT_PATH", raising=False)
    with (
        patch(
            "sase.workspace_provider.changespec._get_commits_ahead",
            return_value=["feat: add thing"],
        ),
        patch(
            "sase.workspace_provider.changespec.generate_timestamp",
            return_value="260101_120000",
        ),
        patch(
            "sase.workspace_provider.changespec.save_chat_history",
            return_value="~/chats/fallback.md",
        ) as mock_save_chat,
        patch(
            "sase.workspace_provider.changespec._save_committed_diff",
            return_value=None,
        ),
        patch(
            "sase.workspace_provider.changespec.get_initial_hooks_for_changespec",
            return_value=[],
        ),
        patch("sase.workspace_provider.changespec.get_change_label", return_value="CL"),
        patch(
            "sase.workspace_provider.changespec.add_changespec_to_project_file",
            return_value="proj_add_thing_1",
        ) as mock_add,
    ):
        result = create_changespec_for_workflow(
            project_name="proj",
            project_file="/fake/proj.gp",
            checkout_target="origin/main",
            branch_name="agent_1",
            prompt="do stuff",
            response="done",
            workflow_name="gh",
        )
        assert result == "proj_add_thing_1"
        mock_save_chat.assert_called_once()
        initial_commits = mock_add.call_args.kwargs["initial_commits"]
        assert initial_commits[0][2] == "~/chats/fallback.md"


def test_create_changespec_for_workflow_passes_bug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """bug parameter is forwarded to add_changespec_to_project_file."""
    monkeypatch.delenv("SASE_AGENT_CHAT_PATH", raising=False)
    with (
        patch(
            "sase.workspace_provider.changespec._get_commits_ahead",
            return_value=["feat: add thing"],
        ),
        patch(
            "sase.workspace_provider.changespec.generate_timestamp",
            return_value="260101_120000",
        ),
        patch(
            "sase.workspace_provider.changespec.save_chat_history",
            return_value="~/chats/f.md",
        ),
        patch(
            "sase.workspace_provider.changespec._save_committed_diff",
            return_value=None,
        ),
        patch(
            "sase.workspace_provider.changespec.get_initial_hooks_for_changespec",
            return_value=[],
        ),
        patch("sase.workspace_provider.changespec.get_change_label", return_value="CL"),
        patch(
            "sase.workspace_provider.changespec.add_changespec_to_project_file",
            return_value="proj_add_thing_1",
        ) as mock_add,
    ):
        result = create_changespec_for_workflow(
            project_name="proj",
            project_file="/fake/proj.gp",
            checkout_target="HEAD~1",
            branch_name="foobar",
            prompt="",
            response="",
            workflow_name="sase_commit",
            cl_name="proj_add_thing",
            bug="http://b/12345",
        )
        assert result == "proj_add_thing_1"
        mock_add.assert_called_once()
        assert mock_add.call_args.kwargs["bug"] == "http://b/12345"


def test_create_changespec_for_workflow_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_AGENT_CHAT_PATH", raising=False)
    with (
        patch(
            "sase.workspace_provider.changespec._get_commits_ahead",
            return_value=["feat: add thing"],
        ),
        patch(
            "sase.workspace_provider.changespec.generate_timestamp",
            return_value="260101_120000",
        ),
        patch(
            "sase.workspace_provider.changespec.save_chat_history",
            return_value="~/chats/f.md",
        ),
        patch(
            "sase.workspace_provider.changespec._save_committed_diff",
            return_value="~/diffs/f.diff",
        ),
        patch(
            "sase.workspace_provider.changespec.get_initial_hooks_for_changespec",
            return_value=[],
        ),
        patch("sase.workspace_provider.changespec.get_change_label", return_value="PR"),
        patch(
            "sase.workspace_provider.changespec.add_changespec_to_project_file",
            return_value="proj_add_thing_1",
        ) as mock_add,
        patch(
            "sase.workspace_provider.changespec.subprocess.run"
        ),  # Prevent real git branch -m
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
        assert result == "proj_add_thing_1"
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
            bug=None,
            cl_label="PR",
            status="Draft",
            reserved_name=None,
        )
