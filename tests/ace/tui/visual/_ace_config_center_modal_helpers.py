"""Modal open helpers for Config Center PNG visual snapshots."""

from __future__ import annotations

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_center_modal import CenterTab, ConfigCenterModal
from sase.ace.tui.modals.config_hub_pane import ConfigHubPane
from sase.ace.tui.modals.config_hub_session import ConfigHubEntry
from sase.ace.tui.modals.config_pane import ConfigPane
from sase.ace.tui.modals.logs_pane import LogsPane
from sase.ace.tui.modals.plugins_browser_pane import PluginsBrowserPane
from sase.ace.tui.modals.projects_pane import ProjectsPane
from sase.ace.tui.modals.procs_pane import ProcsPane
from sase.ace.tui.modals.statistics_pane import StatisticsPane
from sase.logs import RegisteredError
from tests.ace.tui.visual._ace_png_snapshot_helpers import wait_for_visual_idle


async def _open_modal(
    page: AcePage,
    initial_tab: CenterTab,
    *,
    config_entry: ConfigHubEntry | None = None,
) -> ConfigCenterModal:
    modal = ConfigCenterModal(initial_tab=initial_tab, config_entry=config_entry)
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await wait_for_visual_idle(page)
    return modal


async def _open_config_modal(
    page: AcePage,
    *,
    wait_for_loaded: bool = True,
) -> tuple[ConfigCenterModal, ConfigPane]:
    modal = ConfigCenterModal(config_entry=ConfigHubEntry(subtab="misc"))
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#config")))
    hub = modal.query_one("#config", ConfigHubPane)
    await page.wait_for(lambda _s: hub._active_subtab == "misc")
    await page.wait_for(lambda _s: bool(modal.query("#misc")))
    pane = modal.query_one("#misc", ConfigPane)
    if wait_for_loaded:
        await page.wait_for(lambda _s: bool(pane._node_by_path))
    await wait_for_visual_idle(page)
    return modal, pane


async def _open_projects_modal(
    page: AcePage,
) -> tuple[ConfigCenterModal, ProjectsPane]:
    modal = ConfigCenterModal(initial_tab="projects")
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#projects-list")))
    pane = modal.query_one("#projects", ProjectsPane)
    await page.wait_for(lambda _s: pane._current_project_loaded)
    await wait_for_visual_idle(page)
    return modal, pane


async def _open_logs_modal(
    page: AcePage,
    *,
    log_error_target: RegisteredError | None = None,
) -> tuple[ConfigCenterModal, LogsPane]:
    modal = ConfigCenterModal(initial_tab="logs", log_error_target=log_error_target)
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#logs")))
    pane = modal.query_one("#logs", LogsPane)
    await page.wait_for(lambda _s: not pane._loading)
    await wait_for_visual_idle(page)
    return modal, pane


async def _open_procs_modal(page: AcePage) -> tuple[ConfigCenterModal, ProcsPane]:
    modal = ConfigCenterModal(initial_tab="procs")
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#procs")))
    pane = modal.query_one("#procs", ProcsPane)
    await wait_for_visual_idle(page)
    return modal, pane


async def _open_statistics_modal(
    page: AcePage,
    *,
    wait_for_load: bool = True,
) -> tuple[ConfigCenterModal, StatisticsPane]:
    modal = ConfigCenterModal(initial_tab="statistics")
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#statistics")))
    pane = modal.query_one("#statistics", StatisticsPane)
    if wait_for_load:
        await page.wait_for(lambda _s: pane._loaded_once and not pane._loading)
    await wait_for_visual_idle(page)
    return modal, pane


async def _open_plugins_modal(
    page: AcePage,
) -> tuple[ConfigCenterModal, PluginsBrowserPane]:
    modal = ConfigCenterModal(initial_tab="updates")
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#updates")))
    pane = modal.query_one("#updates", PluginsBrowserPane)
    await page.wait_for(lambda _s: not pane._loading)
    pane._switch_to_subtab("plugins")
    await wait_for_visual_idle(page)
    return modal, pane


async def _wait_for_plugins_detail(page: AcePage, pane: PluginsBrowserPane) -> None:
    """Let the pane's debounced detail repaint settle before snapshotting."""
    debouncer = pane._detail_debouncer
    if debouncer is not None:
        await page.wait_for(lambda _s: not debouncer.is_pending)
    await wait_for_visual_idle(page)
