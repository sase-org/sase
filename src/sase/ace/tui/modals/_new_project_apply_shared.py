"""Shared completion and preference helpers for the New Project apply flow."""

from __future__ import annotations

import threading
import weakref
from collections.abc import Mapping
from typing import Any

from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
from sase.project_onboarding.preferences import (
    record_owner_selection,
    record_provider_selection,
    record_visibility_selection,
)

MODAL_TASKS = "_new_project_modal_tasks"


def wizard_is_open(modal: Any) -> bool:
    """Return whether the New Project wizard is still open and queryable.

    Textual sets ``is_mounted`` once and never clears it, so a dismissed
    wizard keeps reporting mounted after teardown prunes its widgets.
    Completions that outlive the wizard (durable add/create procs, the
    ``sase init`` hand-off) must use this instead. ``dismiss()`` pops the
    wizard off the screen stack synchronously, before pruning starts, so
    stack membership closes the whole teardown window.
    """
    if modal is None:
        return False
    if not getattr(modal, "is_mounted", False):
        return False
    if getattr(modal, "_teardown_started", False):
        return False
    try:
        stack = modal.app.screen_stack
    except Exception:
        return False
    return any(screen is modal for screen in stack)


def find_projects_pane(app: Any) -> Any | None:
    """Return the mounted Projects pane from the screen stack, top-down.

    ``App.query`` does not reach widgets inside pushed screens, so a lookup
    through the live ``screen_stack`` is what production completion uses.
    """
    try:
        from sase.ace.tui.modals.projects_pane import ProjectsPane
    except Exception:
        return None
    stack = getattr(app, "screen_stack", None)
    if not isinstance(stack, (list, tuple)):
        return None
    for screen in reversed(stack):
        query = getattr(screen, "query", None)
        if not callable(query):
            continue
        try:
            for pane in query(ProjectsPane):
                if getattr(pane, "is_mounted", False):
                    return pane
        except Exception:
            continue
    return None


def reload_projects_if_mounted(app: Any) -> None:
    """Reload Projects when the pane is mounted, even if the wizard is gone."""
    pane = find_projects_pane(app)
    reload = getattr(pane, "action_reload_projects", None)
    if callable(reload):
        reload()


def on_project_add_complete(
    app: Any,
    modal_ref: weakref.ReferenceType[Any],
    intent: Mapping[str, str],
    completion: TrackedProcCompletion[Any],
) -> None:
    """Durable-add completion that outlives the wizard modal."""
    on_project_apply_complete(app, modal_ref, intent, completion)


def on_project_apply_complete(
    app: Any,
    modal_ref: weakref.ReferenceType[Any],
    intent: Mapping[str, str],
    completion: TrackedProcCompletion[Any],
) -> None:
    """Durable add/create completion that outlives the wizard modal."""
    if completion.success:
        if str(intent.get("mode") or "") == "create":
            _persist_create_preferences_async(intent)
        else:
            _persist_add_preferences_async(intent)
        _integrate_added_project_if_mounted(
            app,
            str(intent.get("project_key") or ""),
            operation_id=_completion_operation_id(completion),
        )
    else:
        reload_projects_if_mounted(app)
    modal = modal_ref()
    observe = getattr(modal, "_observe_add_completion", None)
    if wizard_is_open(modal) and callable(observe):
        observe(completion)


def record_successful_add_preferences(workflow_type: str, owner: str) -> None:
    """Persist last provider and owner after an ``ok`` add result."""
    if workflow_type:
        record_provider_selection(workflow_type)
    if workflow_type and owner:
        record_owner_selection(workflow_type, owner)


def _persist_add_preferences_async(intent: Mapping[str, str]) -> None:
    """Write the durable add request's provider and owner preferences off-thread."""
    thread = threading.Thread(
        target=record_successful_add_preferences,
        args=(
            str(intent.get("workflow_type") or ""),
            str(intent.get("owner") or ""),
        ),
        name="new-project-record-add-prefs",
        daemon=True,
    )
    thread.start()


def _completion_operation_id(completion: TrackedProcCompletion[Any]) -> str:
    """Return the durable proc id that identifies one add/create operation."""
    proc_info = getattr(completion, "proc_info", None)
    return str(getattr(proc_info, "proc_id", "") or "")


def _integrate_added_project_if_mounted(
    app: Any, project_key: str, *, operation_id: str = ""
) -> None:
    """Run the shared post-add sequence when Projects is still mounted."""
    pane = find_projects_pane(app)
    integrate = getattr(pane, "_integrate_added_project", None)
    if callable(integrate) and project_key:
        integrate(project_key, operation_id=operation_id)
        return
    reload_projects_if_mounted(app)


def record_successful_create_preferences(
    workflow_type: str, owner: str, visibility: str
) -> None:
    """Persist provider, owner, and per-owner visibility after a successful create."""
    record_successful_add_preferences(workflow_type, owner)
    if owner and visibility:
        record_visibility_selection(owner, visibility)


def _persist_create_preferences_async(intent: Mapping[str, str]) -> None:
    """Write create preferences off the UI thread; no open widget required."""
    thread = threading.Thread(
        target=record_successful_create_preferences,
        args=(
            str(intent.get("workflow_type") or ""),
            str(intent.get("owner") or ""),
            str(intent.get("visibility") or ""),
        ),
        name="new-project-record-create-prefs",
        daemon=True,
    )
    thread.start()


__all__ = [
    "MODAL_TASKS",
    "find_projects_pane",
    "on_project_add_complete",
    "on_project_apply_complete",
    "record_successful_add_preferences",
    "record_successful_create_preferences",
    "reload_projects_if_mounted",
    "wizard_is_open",
]
