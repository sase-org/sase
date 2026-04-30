"""Tests for create_changespec_for_workflow core behavior."""

from unittest.mock import patch

from sase.workspace_provider.changespec import create_changespec_for_workflow


# --- No-commits edge cases ---


def test_create_changespec_for_workflow_no_commits() -> None:
    with (
        patch(
            "sase.workspace_provider.changespec._get_commits_ahead",
            return_value=[],
        ),
        patch(
            "sase.workspace_provider.changespec.refresh_deltas_after_commits_change",
        ) as mock_refresh,
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
        mock_refresh.assert_not_called()


def test_create_changespec_for_workflow_refreshes_deltas_after_creation() -> None:
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
        ),
        patch(
            "sase.workspace_provider.changespec.os.getcwd", return_value="/workspace"
        ),
        patch(
            "sase.workspace_provider.changespec.refresh_deltas_after_commits_change",
            return_value=False,
        ) as mock_refresh,
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

        assert result == "proj_add_thing_1"
        mock_refresh.assert_called_once_with(
            "/fake/proj.gp",
            "proj_add_thing_1",
            workspace_dir="/workspace",
        )


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
            commit_description="Add new feature\n\nDetailed body text.",
        )
        assert result == "proj_my_cl_1"
        # Should use full commit_description (multi-line preserved)
        mock_add.assert_called_once()
        call_kwargs = mock_add.call_args
        assert call_kwargs[0][1] == "proj_my_cl"  # cl_name passed through
        assert "Detailed body text" in call_kwargs[0][2]


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


# --- commit_description behavior ---


def test_create_changespec_uses_full_commit_description() -> None:
    """When commit_description is provided AND git log returns subjects,
    the full commit_description is used for DESCRIPTION (not just subjects)."""
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
        patch("sase.workspace_provider.changespec.get_change_label", return_value="PR"),
        patch(
            "sase.workspace_provider.changespec.add_changespec_to_project_file",
            return_value="proj_add_thing_1",
        ) as mock_add,
    ):
        result = create_changespec_for_workflow(
            project_name="proj",
            project_file="/fake/proj.gp",
            checkout_target="origin/main",
            branch_name="swift-falcon",
            prompt="do stuff",
            response="done",
            workflow_name="gh",
            cl_name="proj_add_thing",
            commit_description="feat: add thing\n\nThis adds a new feature with\nmulti-line description body.",
        )
        assert result == "proj_add_thing_1"
        mock_add.assert_called_once()
        description = mock_add.call_args[0][2]
        assert "multi-line description body" in description
        assert description != "feat: add thing"


def test_create_changespec_adds_project_prefix_to_cl_name() -> None:
    """cl_name without project prefix gets normalized before passing through."""
    with (
        patch(
            "sase.workspace_provider.changespec._get_commits_ahead",
            return_value=["fix: something"],
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
        patch("sase.workspace_provider.changespec.get_change_label", return_value="PR"),
        patch(
            "sase.workspace_provider.changespec.add_changespec_to_project_file",
            return_value="sase_fix_split_1",
        ) as mock_add,
    ):
        create_changespec_for_workflow(
            project_name="sase",
            project_file="/fake/sase.gp",
            checkout_target="origin/main",
            branch_name="fix-split",
            prompt="",
            response="",
            workflow_name="gh",
            cl_name="fix_split",  # Missing project prefix
        )
        mock_add.assert_called_once()
        # cl_name passed to add_changespec should now include the prefix
        assert mock_add.call_args[0][1] == "sase_fix_split"


def test_create_changespec_strips_pr_tags_from_commit_description() -> None:
    """strip_pr_tags is applied to the full commit_description."""
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
        patch("sase.workspace_provider.changespec.get_change_label", return_value="PR"),
        patch(
            "sase.workspace_provider.changespec.add_changespec_to_project_file",
            return_value="proj_add_thing_1",
        ) as mock_add,
        patch(
            "sase.vcs_provider.config.strip_pr_tags",
            side_effect=lambda s: s.replace("[TAG]", ""),
        ) as mock_strip,
    ):
        create_changespec_for_workflow(
            project_name="proj",
            project_file="/fake/proj.gp",
            checkout_target="origin/main",
            branch_name="swift-falcon",
            prompt="",
            response="",
            workflow_name="gh",
            cl_name="proj_add_thing",
            commit_description="feat: add thing [TAG]\n\nBody text [TAG]",
        )
        mock_strip.assert_called()
        description = mock_add.call_args[0][2]
        assert "[TAG]" not in description
