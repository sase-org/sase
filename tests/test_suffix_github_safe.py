"""Tests for branch rename behavior in suffix.py.

When a provider reports can_rename_branch() == False (e.g. GitHub),
suffix strip/append must NOT rename or push — instead they persist
a branch alias via branch_map.  When can_rename_branch() == True
(bare git), the rename + push flow proceeds as before.
"""

from unittest.mock import MagicMock, patch

from sase.status_state_machine.suffix import (
    handle_suffix_append,
    handle_suffix_strip,
)

# Lazy imports inside handle_suffix_strip / handle_suffix_append — patch
# at the source module for each.
_PATCHES = {
    "update_name": "sase.ace.revert.update_changespec_name_atomic",
    "first_ws": "sase.running_field.get_first_available_axe_workspace",
    "ws_dir": "sase.running_field.get_workspace_directory_for_num",
    "running": "sase.running_field.update_running_field_cl_name",
    "parent_refs": "sase.status_state_machine.field_updates.update_parent_references_atomic",
    # Module-level imports in suffix.py — safe to patch directly.
    "provider_fn": "sase.status_state_machine.suffix.get_vcs_provider",
    "revert": "sase.status_state_machine.suffix.revert_sibling_draft_changespecs",
    "push": "sase.status_state_machine.suffix._push_branch_rename",
    # Branch map utilities
    "write_alias": "sase.core.branch_map.write_branch_alias",
    "remove_alias": "sase.core.branch_map.remove_branch_alias",
    "read_map": "sase.core.branch_map.read_branch_map",
}


# === handle_suffix_strip: immutable branch writes alias instead of renaming ===


@patch(_PATCHES["remove_alias"])
@patch(_PATCHES["write_alias"])
@patch(_PATCHES["push"])
@patch(_PATCHES["revert"], return_value=[])
@patch(_PATCHES["provider_fn"])
@patch(_PATCHES["running"])
@patch(_PATCHES["parent_refs"])
@patch(_PATCHES["ws_dir"], return_value=("/ws", None))
@patch(_PATCHES["first_ws"], return_value=100)
@patch(_PATCHES["update_name"])
def test_suffix_strip_writes_alias_for_immutable_branch(
    _un: MagicMock,
    _fw: MagicMock,
    _wd: MagicMock,
    _pr: MagicMock,
    _rn: MagicMock,
    mock_provider_fn: MagicMock,
    _rv: MagicMock,
    mock_push: MagicMock,
    mock_write: MagicMock,
    mock_remove: MagicMock,
) -> None:
    provider = MagicMock()
    provider.resolve_revision.return_value = "origin/proj_feat_bar_1"
    provider.checkout.return_value = (True, None)
    provider.can_rename_branch.return_value = False
    mock_provider_fn.return_value = provider

    handle_suffix_strip("/tmp/proj.gp", "proj_feat_bar_1", "proj_feat_bar")

    # Should NOT rename or push
    provider.rename_branch.assert_not_called()
    mock_push.assert_not_called()

    # Should write alias
    mock_write.assert_called_once_with("proj", "proj_feat_bar", "proj_feat_bar_1")


@patch(_PATCHES["remove_alias"])
@patch(_PATCHES["push"])
@patch(_PATCHES["revert"], return_value=[])
@patch(_PATCHES["provider_fn"])
@patch(_PATCHES["running"])
@patch(_PATCHES["parent_refs"])
@patch(_PATCHES["ws_dir"], return_value=("/ws", None))
@patch(_PATCHES["first_ws"], return_value=100)
@patch(_PATCHES["update_name"])
def test_suffix_strip_renames_for_mutable_branch(
    _un: MagicMock,
    _fw: MagicMock,
    _wd: MagicMock,
    _pr: MagicMock,
    _rn: MagicMock,
    mock_provider_fn: MagicMock,
    _rv: MagicMock,
    mock_push: MagicMock,
    mock_remove: MagicMock,
) -> None:
    provider = MagicMock()
    provider.resolve_revision.return_value = "origin/proj_feat_bar_1"
    provider.checkout.return_value = (True, None)
    provider.can_rename_branch.return_value = True
    provider.derive_branch_name.return_value = "proj_feat_bar"
    provider.rename_branch.return_value = (True, None)
    mock_provider_fn.return_value = provider

    handle_suffix_strip("/tmp/proj.gp", "proj_feat_bar_1", "proj_feat_bar")

    provider.rename_branch.assert_called_once_with("proj_feat_bar", "/ws")
    mock_push.assert_called_once_with("/ws", "proj_feat_bar", "origin/proj_feat_bar_1")
    # Should clean up stale alias after successful rename
    mock_remove.assert_called_once_with("proj", "proj_feat_bar")


# === handle_suffix_append: immutable branch re-keys alias ===


@patch(_PATCHES["remove_alias"])
@patch(_PATCHES["write_alias"])
@patch(_PATCHES["read_map"], return_value={"proj_feat_bar": "proj_feat_bar_1"})
@patch(_PATCHES["push"])
@patch(_PATCHES["provider_fn"])
@patch(_PATCHES["running"])
@patch(_PATCHES["parent_refs"])
@patch(_PATCHES["ws_dir"], return_value=("/ws", None))
@patch(_PATCHES["first_ws"], return_value=100)
@patch(_PATCHES["update_name"])
def test_suffix_append_rekeys_alias_for_immutable_branch(
    _un: MagicMock,
    _fw: MagicMock,
    _wd: MagicMock,
    _pr: MagicMock,
    _rn: MagicMock,
    mock_provider_fn: MagicMock,
    mock_push: MagicMock,
    mock_read: MagicMock,
    mock_write: MagicMock,
    mock_remove: MagicMock,
) -> None:
    provider = MagicMock()
    provider.resolve_revision.return_value = "origin/proj_feat_bar"
    provider.checkout.return_value = (True, None)
    provider.can_rename_branch.return_value = False
    mock_provider_fn.return_value = provider

    handle_suffix_append("/tmp/proj.gp", "proj_feat_bar", "proj_feat_bar_2")

    # Should NOT rename or push
    provider.rename_branch.assert_not_called()
    mock_push.assert_not_called()

    # Should re-key: remove old, write new pointing to same branch
    mock_remove.assert_called_once_with("proj", "proj_feat_bar")
    mock_write.assert_called_once_with("proj", "proj_feat_bar_2", "proj_feat_bar_1")


@patch(_PATCHES["remove_alias"])
@patch(_PATCHES["push"])
@patch(_PATCHES["provider_fn"])
@patch(_PATCHES["running"])
@patch(_PATCHES["parent_refs"])
@patch(_PATCHES["ws_dir"], return_value=("/ws", None))
@patch(_PATCHES["first_ws"], return_value=100)
@patch(_PATCHES["update_name"])
def test_suffix_append_renames_for_mutable_branch(
    _un: MagicMock,
    _fw: MagicMock,
    _wd: MagicMock,
    _pr: MagicMock,
    _rn: MagicMock,
    mock_provider_fn: MagicMock,
    mock_push: MagicMock,
    mock_remove: MagicMock,
) -> None:
    provider = MagicMock()
    provider.resolve_revision.return_value = "origin/proj_feat_bar"
    provider.checkout.return_value = (True, None)
    provider.can_rename_branch.return_value = True
    provider.derive_branch_name_with_suffix.return_value = "proj_feat_bar_1"
    provider.rename_branch.return_value = (True, None)
    mock_provider_fn.return_value = provider

    handle_suffix_append("/tmp/proj.gp", "proj_feat_bar", "proj_feat_bar_1")

    provider.rename_branch.assert_called_once_with("proj_feat_bar_1", "/ws")
    mock_push.assert_called_once_with("/ws", "proj_feat_bar_1", "origin/proj_feat_bar")
    # Should clean up stale alias
    mock_remove.assert_called_once_with("proj", "proj_feat_bar_1")
