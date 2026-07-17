"""Compatibility exports for Config Center PNG visual snapshot helpers."""

from __future__ import annotations

from tests.ace.tui.visual._ace_config_center_config_helpers import (
    _build_view,
    _config_layers,
    _config_schema,
    _patch_config_view,
)
from tests.ace.tui.visual._ace_config_center_logs_helpers import _seed_logs_tab_files
from tests.ace.tui.visual._ace_config_center_modal_helpers import (
    _open_config_modal,
    _open_logs_modal,
    _open_modal,
    _open_plugins_modal,
    _open_projects_modal,
    _open_tasks_modal,
    _open_telemetry_modal,
    _wait_for_plugins_detail,
)
from tests.ace.tui.visual._ace_config_center_plugins_helpers import (
    _PLUGINS_NOW,
    _patch_plugins_catalog,
    _visual_incoming_commits,
)
from tests.ace.tui.visual._ace_config_center_projects_helpers import (
    _patch_project_records,
)
from tests.ace.tui.visual._ace_config_center_tasks_helpers import (
    _FIXED_TASK_NOW,
    _seed_tasks_tab_queue,
)
from tests.ace.tui.visual._ace_config_center_telemetry_helpers import (
    _patch_telemetry_empty,
    _patch_telemetry_loading,
    _patch_telemetry_populated,
)
from tests.ace.tui.visual._ace_config_center_xprompt_helpers import (
    _patch_xprompt_sources,
)

__all__ = [
    "_FIXED_TASK_NOW",
    "_PLUGINS_NOW",
    "_build_view",
    "_config_layers",
    "_config_schema",
    "_open_config_modal",
    "_open_logs_modal",
    "_open_modal",
    "_open_plugins_modal",
    "_open_projects_modal",
    "_open_tasks_modal",
    "_open_telemetry_modal",
    "_patch_config_view",
    "_patch_plugins_catalog",
    "_patch_project_records",
    "_patch_telemetry_empty",
    "_patch_telemetry_loading",
    "_patch_telemetry_populated",
    "_patch_xprompt_sources",
    "_seed_logs_tab_files",
    "_seed_tasks_tab_queue",
    "_visual_incoming_commits",
    "_wait_for_plugins_detail",
]
