"""Tests for GitHub-safe branch rename behavior in suffix.py.

When a project is GitHub-hosted, suffix strip/append must NOT delete
the old remote branch (which would close any open PR on that branch).
"""

from unittest.mock import MagicMock, patch

from sase.status_state_machine.suffix import (
    _is_github_project,
    handle_suffix_append,
    handle_suffix_strip,
)

# _is_github_project does a lazy `from sase.workspace_provider import
# detect_workflow_type` — patch at the source module.
_DWT = "sase.workspace_provider.detect_workflow_type"

# Lazy imports inside handle_suffix_strip / handle_suffix_append — patch
# at the source module for each.
_PATCHES = {
    "update_name": "sase.ace.revert.update_changespec_name_atomic",
    "to_branch": "sase.core.changespec.changespec_name_to_branch",
    "to_branch_sfx": "sase.core.changespec.changespec_name_to_branch_with_suffix",
    "first_ws": "sase.running_field.get_first_available_axe_workspace",
    "ws_dir": "sase.running_field.get_workspace_directory_for_num",
    "running": "sase.running_field.update_running_field_cl_name",
    "parent_refs": "sase.status_state_machine.field_updates.update_parent_references_atomic",
    # Module-level imports in suffix.py — safe to patch directly.
    "provider_fn": "sase.status_state_machine.suffix.get_vcs_provider",
    "revert": "sase.status_state_machine.suffix.revert_sibling_draft_changespecs",
    "push": "sase.status_state_machine.suffix._push_branch_rename",
    "is_gh": "sase.status_state_machine.suffix._is_github_project",
}


# === _is_github_project ===


@patch(_DWT, return_value="gh")
def test_is_github_project_true(mock_detect: MagicMock) -> None:
    assert _is_github_project("/tmp/proj.gp") is True
    mock_detect.assert_called_once_with("/tmp/proj.gp")


@patch(_DWT, return_value="git")
def test_is_github_project_false_bare_git(mock_detect: MagicMock) -> None:
    assert _is_github_project("/tmp/proj.gp") is False


@patch(_DWT, side_effect=ValueError("no plugin"))
def test_is_github_project_false_on_error(mock_detect: MagicMock) -> None:
    assert _is_github_project("/tmp/proj.gp") is False


# === handle_suffix_strip: GitHub skips _push_branch_rename ===


@patch(_PATCHES["is_gh"], return_value=True)
@patch(_PATCHES["push"])
@patch(_PATCHES["revert"], return_value=[])
@patch(_PATCHES["provider_fn"])
@patch(_PATCHES["running"])
@patch(_PATCHES["parent_refs"])
@patch(_PATCHES["ws_dir"], return_value=("/ws", None))
@patch(_PATCHES["first_ws"], return_value=100)
@patch(_PATCHES["update_name"])
@patch(_PATCHES["to_branch"], return_value="feat-bar")
def test_suffix_strip_skips_push_for_github(
    _br: MagicMock,
    _un: MagicMock,
    _fw: MagicMock,
    _wd: MagicMock,
    _pr: MagicMock,
    _rn: MagicMock,
    mock_provider_fn: MagicMock,
    _rv: MagicMock,
    mock_push: MagicMock,
    _ig: MagicMock,
) -> None:
    provider = MagicMock()
    provider.resolve_revision.return_value = "origin/feat-bar-1"
    provider.checkout.return_value = (True, None)
    provider.rename_branch.return_value = (True, None)
    mock_provider_fn.return_value = provider

    handle_suffix_strip("/tmp/proj.gp", "proj_feat_bar__1", "proj_feat_bar")

    provider.rename_branch.assert_called_once_with("feat-bar", "/ws")
    mock_push.assert_not_called()


@patch(_PATCHES["is_gh"], return_value=False)
@patch(_PATCHES["push"])
@patch(_PATCHES["revert"], return_value=[])
@patch(_PATCHES["provider_fn"])
@patch(_PATCHES["running"])
@patch(_PATCHES["parent_refs"])
@patch(_PATCHES["ws_dir"], return_value=("/ws", None))
@patch(_PATCHES["first_ws"], return_value=100)
@patch(_PATCHES["update_name"])
@patch(_PATCHES["to_branch"], return_value="feat-bar")
def test_suffix_strip_pushes_for_bare_git(
    _br: MagicMock,
    _un: MagicMock,
    _fw: MagicMock,
    _wd: MagicMock,
    _pr: MagicMock,
    _rn: MagicMock,
    mock_provider_fn: MagicMock,
    _rv: MagicMock,
    mock_push: MagicMock,
    _ig: MagicMock,
) -> None:
    provider = MagicMock()
    provider.resolve_revision.return_value = "origin/feat-bar-1"
    provider.checkout.return_value = (True, None)
    provider.rename_branch.return_value = (True, None)
    mock_provider_fn.return_value = provider

    handle_suffix_strip("/tmp/proj.gp", "proj_feat_bar__1", "proj_feat_bar")

    provider.rename_branch.assert_called_once_with("feat-bar", "/ws")
    mock_push.assert_called_once_with("/ws", "feat-bar", "origin/feat-bar-1")


# === handle_suffix_append: GitHub skips _push_branch_rename ===


@patch(_PATCHES["is_gh"], return_value=True)
@patch(_PATCHES["push"])
@patch(_PATCHES["provider_fn"])
@patch(_PATCHES["running"])
@patch(_PATCHES["parent_refs"])
@patch(_PATCHES["ws_dir"], return_value=("/ws", None))
@patch(_PATCHES["first_ws"], return_value=100)
@patch(_PATCHES["update_name"])
@patch(_PATCHES["to_branch_sfx"], return_value="feat-bar-1")
def test_suffix_append_skips_push_for_github(
    _bs: MagicMock,
    _un: MagicMock,
    _fw: MagicMock,
    _wd: MagicMock,
    _pr: MagicMock,
    _rn: MagicMock,
    mock_provider_fn: MagicMock,
    mock_push: MagicMock,
    _ig: MagicMock,
) -> None:
    provider = MagicMock()
    provider.resolve_revision.return_value = "origin/feat-bar"
    provider.checkout.return_value = (True, None)
    provider.rename_branch.return_value = (True, None)
    mock_provider_fn.return_value = provider

    handle_suffix_append("/tmp/proj.gp", "proj_feat_bar", "proj_feat_bar__1")

    provider.rename_branch.assert_called_once_with("feat-bar-1", "/ws")
    mock_push.assert_not_called()
