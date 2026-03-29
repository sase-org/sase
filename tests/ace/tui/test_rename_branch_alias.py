"""Tests for branch alias handling in the rename action.

When a provider reports can_rename_branch() == False (e.g. GitHub with an
open PR), _execute_rename must write a branch alias instead of calling
rename_branch().  When can_rename_branch() == True, it should rename as
before and clean up any stale alias.
"""

from unittest.mock import MagicMock, patch

from sase.ace.tui.actions.rename import RenameMixin

# Patch targets — lazy imports inside _execute_rename.
_PATCHES = {
    "update_name": "sase.ace.revert.update_changespec_name_atomic",
    "parent_refs": "sase.status_state_machine.update_parent_references_atomic",
    "running": "sase.running_field.update_running_field_cl_name",
    "first_ws": "sase.running_field.get_first_available_axe_workspace",
    "ws_dir": "sase.running_field.get_workspace_directory_for_num",
    "claim": "sase.running_field.claim_workspace",
    "release": "sase.running_field.release_workspace",
    "hg_clean": "sase.ace.tui.actions.rename.run_sase_hg_clean",
    "provider_fn": "sase.ace.tui.actions.rename.get_vcs_provider",
    "write_alias": "sase.core.branch_map.write_branch_alias",
    "remove_alias": "sase.core.branch_map.remove_branch_alias",
}


def _make_app(changespec: MagicMock) -> MagicMock:
    """Create a minimal mock that satisfies RenameMixin."""
    app = MagicMock(spec=RenameMixin)
    app._execute_rename = RenameMixin._execute_rename.__get__(app)
    app._reload_and_reposition = MagicMock()
    app.notify = MagicMock()
    app.suspend = MagicMock(
        return_value=MagicMock(
            __enter__=MagicMock(), __exit__=MagicMock(return_value=False)
        )
    )
    return app


def _make_changespec(name: str = "old_feature") -> MagicMock:
    cs = MagicMock()
    cs.name = name
    cs.file_path = "/tmp/proj.gp"
    cs.status = "WIP"
    return cs


@patch(_PATCHES["release"])
@patch(_PATCHES["remove_alias"])
@patch(_PATCHES["write_alias"])
@patch(_PATCHES["provider_fn"])
@patch(_PATCHES["hg_clean"], return_value=(True, None))
@patch(_PATCHES["claim"], return_value=True)
@patch(_PATCHES["ws_dir"], return_value=("/ws", None))
@patch(_PATCHES["first_ws"], return_value=100)
@patch(_PATCHES["running"])
@patch(_PATCHES["parent_refs"])
@patch(_PATCHES["update_name"])
def test_rename_writes_alias_for_immutable_branch(
    _un: MagicMock,
    _pr: MagicMock,
    _rn: MagicMock,
    _fw: MagicMock,
    _wd: MagicMock,
    _cl: MagicMock,
    _hc: MagicMock,
    mock_provider_fn: MagicMock,
    mock_write: MagicMock,
    mock_remove: MagicMock,
    _rel: MagicMock,
) -> None:
    provider = MagicMock()
    provider.resolve_revision.return_value = "origin/proj_old_feature"
    provider.checkout.return_value = (True, None)
    provider.can_rename_branch.return_value = False
    mock_provider_fn.return_value = provider

    cs = _make_changespec()
    app = _make_app(cs)

    app._execute_rename(cs, "new_feature")

    # Should NOT call rename_branch
    provider.rename_branch.assert_not_called()

    # Should write alias mapping new name -> old branch
    mock_write.assert_called_once_with("proj", "new_feature", "proj_old_feature")

    # Should NOT remove any alias
    mock_remove.assert_not_called()


@patch(_PATCHES["release"])
@patch(_PATCHES["remove_alias"])
@patch(_PATCHES["write_alias"])
@patch(_PATCHES["provider_fn"])
@patch(_PATCHES["hg_clean"], return_value=(True, None))
@patch(_PATCHES["claim"], return_value=True)
@patch(_PATCHES["ws_dir"], return_value=("/ws", None))
@patch(_PATCHES["first_ws"], return_value=100)
@patch(_PATCHES["running"])
@patch(_PATCHES["parent_refs"])
@patch(_PATCHES["update_name"])
def test_rename_renames_for_mutable_branch(
    _un: MagicMock,
    _pr: MagicMock,
    _rn: MagicMock,
    _fw: MagicMock,
    _wd: MagicMock,
    _cl: MagicMock,
    _hc: MagicMock,
    mock_provider_fn: MagicMock,
    mock_write: MagicMock,
    mock_remove: MagicMock,
    _rel: MagicMock,
) -> None:
    provider = MagicMock()
    provider.resolve_revision.return_value = "origin/proj_old_feature"
    provider.checkout.return_value = (True, None)
    provider.can_rename_branch.return_value = True
    provider.rename_branch.return_value = (True, None)
    mock_provider_fn.return_value = provider

    cs = _make_changespec()
    app = _make_app(cs)

    app._execute_rename(cs, "new_feature")

    # Should rename the branch
    provider.rename_branch.assert_called_once_with("new_feature", "/ws")

    # Should clean up stale alias
    mock_remove.assert_called_once_with("proj", "new_feature")

    # Should NOT write a new alias
    mock_write.assert_not_called()
