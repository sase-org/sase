"""Public rendering API for the ``sase plugin`` commands."""

from __future__ import annotations

from sase.plugins.render_catalog import (
    build_catalog_list_panel,
    build_community_warning_panel,
    build_detail_panel,
    render_catalog_list,
    render_catalog_show,
    render_show_not_found,
)
from sase.plugins.render_results import (
    render_install_already_installed,
    render_install_dry_run,
    render_install_result,
    render_no_plugins_installed,
    render_plugin_not_installed,
    render_plugin_uninstall_dry_run,
    render_plugin_uninstall_not_installed,
    render_plugin_uninstall_result,
    render_plugin_update_dry_run,
    render_plugin_update_result,
)

__all__ = [
    "build_catalog_list_panel",
    "build_community_warning_panel",
    "build_detail_panel",
    "render_catalog_list",
    "render_catalog_show",
    "render_install_already_installed",
    "render_install_dry_run",
    "render_install_result",
    "render_no_plugins_installed",
    "render_plugin_not_installed",
    "render_plugin_uninstall_dry_run",
    "render_plugin_uninstall_not_installed",
    "render_plugin_uninstall_result",
    "render_plugin_update_dry_run",
    "render_plugin_update_result",
    "render_show_not_found",
]
