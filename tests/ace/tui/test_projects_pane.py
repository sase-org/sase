"""Integration tests for the Projects tab of the SASE Admin Center.

This facade preserves the original test import path while the tests live in focused
private modules.
"""

from __future__ import annotations

from datetime import datetime
import weakref

import pytest
from textual.widgets import Button, ContentSwitcher, OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.commands import build_command_catalog, execute_command
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_center_session import AdminCenterSessionState
from sase.ace.tui.modals.new_project_modal import NewProjectModal, NewProjectSelection
from sase.ace.tui.modals.project_management_rendering import hints_text
from sase.ace.tui.modals.project_inventory_panes import RepoInventoryPane
from sase.ace.tui.modals.projects_help_modal import ProjectsHelpModal
from sase.ace.tui.modals.projects_pane import ProjectsPane
from sase.current_project import CurrentProject
from sase.ace.tui.modals.projects_pane import ProjectCountsLoadResult
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.panel_tab_strip import PanelTabStrip
from sase.repo_inventory import RepoInventory
from sase.workspace_provider.inventory import WorkspaceInventory

from tests.ace.tui.modals.project_management_modal_test_helpers import (
    make_project_record,
)
from tests.ace.tui._projects_pane_navigation_tests import (
    test_admin_center_reaches_projects_tab_from_config,
    test_projects_session_restores_project_by_identity,
    test_projects_session_round_trips_current_project_display,
    test_admin_center_digit_owns_hidden_member_jump_state,
    test_admin_center_leaves_projects_tab_with_shift_tab,
    test_projects_filter_forwards_brackets_to_cycle_subtabs,
    test_projects_filter_yields_tab_to_admin_center,
)
from tests.ace.tui._projects_pane_project_lifecycle_tests import (
    test_new_project_binding_is_scoped_and_filter_safe,
    test_new_project_palette_opener_is_one_shot,
    test_new_project_gets_current_provider_and_owner_context,
    test_post_add_keeps_filter_and_offers_show_new_project,
    test_empty_projects_state_names_new_project_key,
)
from tests.ace.tui._projects_pane_keymap_tests import (
    test_inventory_escape_clears_project_before_closing_admin_center,
    test_configured_projects_bindings_dispatch_and_render_hints,
    test_configured_cycle_subtab_keys_bubble_and_forward,
    test_configured_inventory_bindings_dispatch_and_render_hints,
    test_projects_filter_applies_once_per_keystroke,
    test_projects_help_opens_from_list_and_inventory,
    test_show_new_project_key_clears_filter,
)

from tests.ace.tui._projects_pane_test_helpers import patch_panes as _patch_panes_impl


def _patch_panes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the historical helper path used by neighboring integration tests."""
    _patch_panes_impl(monkeypatch)
