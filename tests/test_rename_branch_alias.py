"""Tests for branch alias persistence during manual rename.

When a provider reports can_rename_branch() == False (e.g. GitHub),
manual rename via ``n`` keymap must persist a branch alias via
branch_map instead of calling provider.rename_branch().  When
can_rename_branch() == True (bare git), the rename proceeds as before
and stale aliases are cleaned up.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from sase.ace.tui.actions.rename import RenameMixin

# Patches for lazy imports inside _execute_rename / run_handler.
_PATCHES = {
    "base_status": "sase.ace.changespec.get_base_status",
    "update_name": "sase.ace.revert.update_changespec_name_atomic",
    "first_ws": "sase.running_field.get_first_available_axe_workspace",
    "ws_dir": "sase.running_field.get_workspace_directory_for_num",
    "running": "sase.running_field.update_running_field_cl_name",
    "parent_refs": "sase.status_state_machine.update_parent_references_atomic",
    "claim": "sase.running_field.claim_workspace",
    "release": "sase.running_field.release_workspace",
    # Module-level imports in rename.py — patch in that namespace.
    "provider_fn": "sase.ace.tui.actions.rename.get_vcs_provider",
    "hg_clean": "sase.ace.tui.actions.rename.run_sase_hg_clean",
    # Branch map utilities (lazy import inside run_handler).
    "write_alias": "sase.core.branch_map.write_branch_alias",
    "remove_alias": "sase.core.branch_map.remove_branch_alias",
    "read_map": "sase.core.branch_map.read_branch_map",
}


def _make_mixin() -> RenameMixin:
    """Create a minimal RenameMixin instance with mocked TUI methods."""
    obj = object.__new__(RenameMixin)
    obj.suspend = MagicMock()  # type: ignore[attr-defined]
    obj.notify = MagicMock()  # type: ignore[attr-defined]
    obj._reload_and_reposition = MagicMock()  # type: ignore[attr-defined]
    return obj


def _make_changespec(
    name: str = "old_cl",
    file_path: str = "/tmp/proj.gp",
    status: str = "WIP",
) -> MagicMock:
    cs = MagicMock()
    cs.name = name
    cs.file_path = file_path
    cs.status = status
    return cs


# === immutable provider: writes alias when no existing alias ===


@patch(_PATCHES["remove_alias"])
@patch(_PATCHES["write_alias"])
@patch(_PATCHES["read_map"], return_value={})
@patch(_PATCHES["release"])
@patch(_PATCHES["provider_fn"])
@patch(_PATCHES["hg_clean"], return_value=(True, None))
@patch(_PATCHES["claim"], return_value=True)
@patch(_PATCHES["running"])
@patch(_PATCHES["parent_refs"])
@patch(_PATCHES["update_name"])
@patch(_PATCHES["ws_dir"], return_value=("/ws", None))
@patch(_PATCHES["first_ws"], return_value=100)
@patch(_PATCHES["base_status"], return_value="WIP")
def test_immutable_writes_alias_no_existing(
    _bs: MagicMock,
    _fw: MagicMock,
    _wd: MagicMock,
    _un: MagicMock,
    _pr: MagicMock,
    _rn: MagicMock,
    _cl: MagicMock,
    _hg: MagicMock,
    mock_provider_fn: MagicMock,
    _rel: MagicMock,
    _read: MagicMock,
    mock_write: MagicMock,
    mock_remove: MagicMock,
) -> None:
    provider = MagicMock()
    provider.resolve_revision.return_value = "origin/proj_old_cl"
    provider.checkout.return_value = (True, None)
    provider.can_rename_branch.return_value = False
    mock_provider_fn.return_value = provider

    mixin = _make_mixin()
    cs = _make_changespec(name="old_cl")
    mixin._execute_rename(cs, "new_cl")

    # Should NOT call provider rename
    provider.rename_branch.assert_not_called()

    # Should write alias: new_cl -> proj_old_cl (origin/ stripped)
    mock_write.assert_called_once_with("proj", "new_cl", "proj_old_cl")

    # No existing alias to remove
    mock_remove.assert_not_called()


# === immutable provider: re-keys existing alias to new name ===


@patch(_PATCHES["remove_alias"])
@patch(_PATCHES["write_alias"])
@patch(_PATCHES["read_map"], return_value={"old_cl": "proj_original_branch"})
@patch(_PATCHES["release"])
@patch(_PATCHES["provider_fn"])
@patch(_PATCHES["hg_clean"], return_value=(True, None))
@patch(_PATCHES["claim"], return_value=True)
@patch(_PATCHES["running"])
@patch(_PATCHES["parent_refs"])
@patch(_PATCHES["update_name"])
@patch(_PATCHES["ws_dir"], return_value=("/ws", None))
@patch(_PATCHES["first_ws"], return_value=100)
@patch(_PATCHES["base_status"], return_value="WIP")
def test_immutable_rekeys_existing_alias(
    _bs: MagicMock,
    _fw: MagicMock,
    _wd: MagicMock,
    _un: MagicMock,
    _pr: MagicMock,
    _rn: MagicMock,
    _cl: MagicMock,
    _hg: MagicMock,
    mock_provider_fn: MagicMock,
    _rel: MagicMock,
    _read: MagicMock,
    mock_write: MagicMock,
    mock_remove: MagicMock,
) -> None:
    provider = MagicMock()
    provider.resolve_revision.return_value = "origin/proj_old_cl"
    provider.checkout.return_value = (True, None)
    provider.can_rename_branch.return_value = False
    mock_provider_fn.return_value = provider

    mixin = _make_mixin()
    cs = _make_changespec(name="old_cl")
    mixin._execute_rename(cs, "new_cl")

    # Should NOT call provider rename
    provider.rename_branch.assert_not_called()

    # Should re-key: remove old alias, write new with same actual branch
    mock_remove.assert_called_once_with("proj", "old_cl")
    mock_write.assert_called_once_with("proj", "new_cl", "proj_original_branch")


# === mutable provider: renames and cleans up stale alias ===


@patch(_PATCHES["remove_alias"])
@patch(_PATCHES["write_alias"])
@patch(_PATCHES["read_map"])
@patch(_PATCHES["release"])
@patch(_PATCHES["provider_fn"])
@patch(_PATCHES["hg_clean"], return_value=(True, None))
@patch(_PATCHES["claim"], return_value=True)
@patch(_PATCHES["running"])
@patch(_PATCHES["parent_refs"])
@patch(_PATCHES["update_name"])
@patch(_PATCHES["ws_dir"], return_value=("/ws", None))
@patch(_PATCHES["first_ws"], return_value=100)
@patch(_PATCHES["base_status"], return_value="WIP")
def test_mutable_renames_and_removes_stale_alias(
    _bs: MagicMock,
    _fw: MagicMock,
    _wd: MagicMock,
    _un: MagicMock,
    _pr: MagicMock,
    _rn: MagicMock,
    _cl: MagicMock,
    _hg: MagicMock,
    mock_provider_fn: MagicMock,
    _rel: MagicMock,
    _read: MagicMock,
    mock_write: MagicMock,
    mock_remove: MagicMock,
) -> None:
    provider = MagicMock()
    provider.resolve_revision.return_value = "origin/proj_old_cl"
    provider.checkout.return_value = (True, None)
    provider.can_rename_branch.return_value = True
    provider.rename_branch.return_value = (True, None)
    mock_provider_fn.return_value = provider

    mixin = _make_mixin()
    cs = _make_changespec(name="old_cl")
    mixin._execute_rename(cs, "new_cl")

    # Should call provider rename
    provider.rename_branch.assert_called_once_with("new_cl", "/ws")

    # Should clean up stale alias for new name
    mock_remove.assert_called_once_with("proj", "new_cl")

    # Should NOT write any new alias
    mock_write.assert_not_called()
