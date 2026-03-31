"""Tests for create_changespec_for_workflow parameter forwarding and env vars."""

from unittest.mock import patch

import pytest

from sase.workspace_provider.changespec import create_changespec_for_workflow


# --- parent parameter ---


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


# --- SASE_AGENT_CHAT_PATH env var ---


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


# --- bug parameter ---


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


# --- Full success path ---


def test_create_changespec_for_workflow_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_AGENT_CHAT_PATH", raising=False)
    monkeypatch.delenv("SASE_PLAN", raising=False)
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


# --- SASE_PLAN env var ---


def test_create_changespec_for_workflow_passes_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SASE_PLAN env var propagates as plan_path in initial_commits tuple."""
    monkeypatch.delenv("SASE_AGENT_CHAT_PATH", raising=False)
    monkeypatch.setenv("SASE_PLAN", "/home/user/.sase/plans/my_plan.md")
    monkeypatch.setenv("HOME", "/home/user")
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
            return_value="proj_plan_1",
        ) as mock_add,
        patch("sase.workspace_provider.changespec.subprocess.run"),
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
        assert result == "proj_plan_1"
        initial_commits = mock_add.call_args.kwargs["initial_commits"]
        assert len(initial_commits) == 1
        commit_tuple = initial_commits[0]
        # Positions 0-3: num, note, chat, diff
        assert commit_tuple[:4] == (
            1,
            "[run] Initial Commit",
            "~/chats/f.md",
            "~/diffs/f.diff",
        )
        # Position 4: commit_body (None), position 5: plan_path (HOME-shortened)
        assert commit_tuple[4] is None
        assert commit_tuple[5] == "~/.sase/plans/my_plan.md"


def test_create_changespec_for_workflow_plan_outside_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SASE_PLAN path not under HOME is passed through unchanged."""
    monkeypatch.delenv("SASE_AGENT_CHAT_PATH", raising=False)
    monkeypatch.setenv("SASE_PLAN", "/opt/plans/my_plan.md")
    monkeypatch.setenv("HOME", "/home/user")
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
            return_value="proj_plan_2",
        ) as mock_add,
        patch("sase.workspace_provider.changespec.subprocess.run"),
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
        assert result == "proj_plan_2"
        initial_commits = mock_add.call_args.kwargs["initial_commits"]
        assert len(initial_commits) == 1
        commit_tuple = initial_commits[0]
        assert commit_tuple[:4] == (
            1,
            "[run] Initial Commit",
            "~/chats/f.md",
            "~/diffs/f.diff",
        )
        # Position 4: commit_body (None), position 5: plan_path (unchanged)
        assert commit_tuple[4] is None
        assert commit_tuple[5] == "/opt/plans/my_plan.md"


def test_create_changespec_for_workflow_no_plan_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without SASE_PLAN, initial_commits tuple stays at 4 elements."""
    monkeypatch.delenv("SASE_AGENT_CHAT_PATH", raising=False)
    monkeypatch.delenv("SASE_PLAN", raising=False)
    with (
        patch(
            "sase.workspace_provider.changespec._get_commits_ahead",
            return_value=["feat: thing"],
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
        patch("sase.workspace_provider.changespec.get_change_label", return_value="CL"),
        patch(
            "sase.workspace_provider.changespec.add_changespec_to_project_file",
            return_value="proj_thing_1",
        ) as mock_add,
        patch("sase.workspace_provider.changespec.subprocess.run"),
    ):
        create_changespec_for_workflow(
            project_name="proj",
            project_file="/fake/proj.gp",
            checkout_target="origin/main",
            branch_name="swift-falcon",
            prompt="do stuff",
            response="done",
            workflow_name="gh",
        )
        initial_commits = mock_add.call_args.kwargs["initial_commits"]
        assert len(initial_commits[0]) == 4
