"""Modal open helpers for Config Center PNG visual snapshots."""

from __future__ import annotations

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_center_modal import CenterTab, ConfigCenterModal
from sase.ace.tui.modals.config_pane import ConfigPane
from sase.ace.tui.modals.logs_pane import LogsPane
from sase.ace.tui.modals.plugins_browser_pane import PluginsBrowserPane
from sase.ace.tui.modals.projects_pane import ProjectsPane
from sase.ace.tui.modals.tasks_pane import TasksPane
from sase.ace.tui.modals.telemetry_pane import TelemetryPane
from tests.ace.tui.visual._ace_png_snapshot_helpers import wait_for_visual_idle


async def _open_modal(page: AcePage, initial_tab: CenterTab) -> ConfigCenterModal:
    modal = ConfigCenterModal(initial_tab=initial_tab)
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await wait_for_visual_idle(page)
    return modal


async def _open_config_modal(page: AcePage) -> tuple[ConfigCenterModal, ConfigPane]:
    modal = ConfigCenterModal(initial_tab="config")
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#config")))
    pane = modal.query_one("#config", ConfigPane)
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
    await wait_for_visual_idle(page)
    return modal, pane


async def _open_logs_modal(page: AcePage) -> tuple[ConfigCenterModal, LogsPane]:
    modal = ConfigCenterModal(initial_tab="logs")
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#logs")))
    pane = modal.query_one("#logs", LogsPane)
    await page.wait_for(lambda _s: not pane._loading)
    await wait_for_visual_idle(page)
    return modal, pane


async def _open_tasks_modal(page: AcePage) -> tuple[ConfigCenterModal, TasksPane]:
    modal = ConfigCenterModal(initial_tab="tasks")
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#tasks")))
    pane = modal.query_one("#tasks", TasksPane)
    await wait_for_visual_idle(page)
    return modal, pane


async def _open_telemetry_modal(
    page: AcePage,
    *,
    wait_for_load: bool = True,
) -> tuple[ConfigCenterModal, TelemetryPane]:
    modal = ConfigCenterModal(initial_tab="telemetry")
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#telemetry")))
    pane = modal.query_one("#telemetry", TelemetryPane)
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
    await wait_for_visual_idle(page)
    return modal, pane


async def _wait_for_plugins_detail(page: AcePage, pane: PluginsBrowserPane) -> None:
    """Let the pane's debounced detail repaint settle before snapshotting."""
    debouncer = pane._detail_debouncer
    if debouncer is not None:
        await page.wait_for(lambda _s: not debouncer.is_pending)
    await wait_for_visual_idle(page)
