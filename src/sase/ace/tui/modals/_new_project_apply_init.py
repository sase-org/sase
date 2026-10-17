"""Init host adapter for the New Project wizard."""

from __future__ import annotations

import weakref
from typing import Any

from ._new_project_apply_shared import (
    find_projects_pane,
    reload_projects_if_mounted,
    wizard_is_open,
)
from sase.ace.tui.modals.projects_pane_init import InitScope
from sase.ace.tui.modals.projects_pane_init_flow import run_project_init


class NewProjectInitHost:
    """Wizard adapter for :func:`run_project_init`."""

    def __init__(self, modal: Any) -> None:
        self._modal_ref = weakref.ref(modal)
        self._app = modal.app
        self._status = ""
        self._finished = False
        self._waiting_check = True
        self._awaiting_apply = False

    @property
    def app(self) -> Any:
        return self._app

    @property
    def is_mounted(self) -> bool:
        modal = self._modal_ref()
        if wizard_is_open(modal):
            return True
        pane = find_projects_pane(self._app)
        return pane is not None and getattr(pane, "is_mounted", False)

    def push_screen(self, modal: Any, callback: Any) -> None:
        self._waiting_check = False

        def _wrapped(decision: Any) -> None:
            self._awaiting_apply = (
                decision is not None and getattr(decision, "action", None) == "apply"
            )
            callback(decision)

        self._app.push_screen(modal, _wrapped)

    def notify(self, message: str, **kwargs: Any) -> None:
        notify = getattr(self._app, "notify", None)
        if callable(notify):
            notify(message, **kwargs)

    def get_status(self) -> str:
        return self._status

    def set_status(self, message: str) -> None:
        self._status = message

    def suspend(self) -> Any:
        return self._app.suspend()

    def reload_projects(self) -> None:
        reload_projects_if_mounted(self._app)

    def report_init_outcome(self, initialized: bool) -> None:
        self._finish(initialized)

    def recheck_after_terminal(self) -> bool:
        return True

    def _finish(self, initialized: bool) -> None:
        if self._finished:
            return
        self._finished = True
        modal = self._modal_ref()
        if modal is not None and wizard_is_open(modal):
            modal._on_init_finished(initialized)


__all__ = ["NewProjectInitHost"]
