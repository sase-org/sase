"""Ready-stage actions for the New Project wizard."""

from __future__ import annotations

import asyncio
from typing import Any

from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.current_project import SetCurrentProjectOutcome, set_current_project
from sase.project_tags import ensure_project_tag_catalog

from ._new_project_apply_shared import (
    MODAL_TASKS,
    find_projects_pane,
    reload_projects_if_mounted,
)
from .project_selection_types import SelectionItem

SET_CURRENT_NOTIFY_SEVERITY: dict[str, str] = {
    "set": "information",
    "unchanged": "information",
    "ineligible": "warning",
    "unverified": "error",
}


def show_outcome(modal: Any, outcome: str) -> Any:
    from .new_project_modal import NewProjectSelection

    return NewProjectSelection(
        outcome,
        modal._state.workflow_type,
        project_key=getattr(modal, "_ready_key", ""),
        operation_id=str(getattr(modal, "_apply_proc_id", "") or ""),
    )


def dismiss_ready(modal: Any, outcome: str | None) -> None:
    result = None if outcome is None else modal._show_outcome(outcome)
    modal.dismiss(result)


def launch_from_ready(modal: Any) -> None:
    spawn_pump_free_task(
        modal,
        modal._ensure_catalog_and_launch(),
        name="new-project-plus-launch",
        registry_attr=MODAL_TASKS,
    )


async def ensure_catalog_and_launch(modal: Any) -> None:
    await asyncio.to_thread(ensure_project_tag_catalog)
    if not modal.is_mounted:
        return
    key = getattr(modal, "_ready_key", "")
    name = getattr(modal, "_ready_name", "") or key
    selection = SelectionItem(
        display_name=name,
        item_type="project",
        project_name=key,
        cl_name=None,
        project_label=name or None,
    )
    app = modal.app
    modal.dismiss(modal._show_outcome("added"))
    modal._dismiss_center_underneath()
    starter = getattr(app, "_start_custom_agent_from_selection", None)
    if callable(starter):
        starter(selection)


def dismiss_center_underneath(modal: Any) -> None:
    try:
        from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
    except Exception:
        return
    for screen in getattr(modal.app, "screen_stack", ()):
        if isinstance(screen, ConfigCenterModal):
            dismiss = getattr(screen, "dismiss", None)
            if callable(dismiss):
                dismiss(None)
            return


def make_ready_current(modal: Any) -> None:
    key = getattr(modal, "_ready_key", "")
    if not key:
        return
    spawn_pump_free_task(
        modal,
        modal._set_current_key(key),
        name="new-project-set-current",
        registry_attr=MODAL_TASKS,
    )


async def set_current_key(modal: Any, key: str) -> None:
    outcome = await asyncio.to_thread(set_current_project, key)
    if not modal.is_mounted:
        return
    if not isinstance(outcome, SetCurrentProjectOutcome):
        modal.notify("Could not set current project", severity="error")
        return
    modal.notify(
        outcome.message,
        severity=SET_CURRENT_NOTIFY_SEVERITY.get(outcome.status, "information"),
    )
    if outcome.status == "set":
        pane = find_projects_pane(modal.app)
        invalidate = getattr(pane, "_invalidate_current_project_indicator", None)
        if callable(invalidate):
            invalidate()
        reload_projects_if_mounted(modal.app)


__all__ = [
    "dismiss_center_underneath",
    "dismiss_ready",
    "ensure_catalog_and_launch",
    "launch_from_ready",
    "make_ready_current",
    "set_current_key",
    "show_outcome",
]
