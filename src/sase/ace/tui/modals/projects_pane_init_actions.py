"""``i`` / ``I`` init gestures for the Projects tab.

Sequencing (check, preview, apply, terminal valve) lives in
:mod:`sase.ace.tui.modals.projects_pane_init_flow`; this mixin is the pane
host adapter and keeps the target-selection gestures.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name

from .projects_pane_init import InitScope
from .projects_pane_init_flow import ProjectsInitFlowController

if TYPE_CHECKING:
    from textual.app import App
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object


class ProjectsPaneInitActionsMixin(_MixinBase):
    """``i`` / ``I`` init gestures backed by the shared init controller."""

    if TYPE_CHECKING:
        _records: list[ProjectRecordWire]
        _status_message: str
        _init_flow: ProjectsInitFlowController | None
        is_mounted: bool
        app: App[Any]

        def _target_records(self) -> list[ProjectRecordWire]: ...
        def _set_status(self, message: str) -> None: ...
        def notify(self, message: str, **kwargs: Any) -> None: ...
        def action_reload_projects(self) -> None: ...

    def action_initialize_project(self) -> None:
        records = self._target_records()
        if not records:
            return
        survivors, skipped = _partition_init_targets(records)
        if skipped:
            skip_message = f"Skipping {', '.join(skipped)}"
            if not survivors:
                self._set_status(skip_message)
                self.notify(skip_message, severity="warning")
                return
            self.notify(skip_message, severity="information")
        scope = InitScope.for_projects(
            [record.project_name for record in survivors],
            [effective_project_name(record) for record in survivors],
        )
        self._init_flow_controller().start_init_check(scope)

    def action_initialize_all_projects(self) -> None:
        count = sum(1 for record in self._records if _is_init_eligible(record))
        self._init_flow_controller().start_init_check(
            InitScope.everything(), project_count=count
        )

    def push_screen(self, modal: Any, callback: Any) -> None:
        """Open the init preview modal (host adapter)."""
        self.app.push_screen(modal, callback)

    def get_status(self) -> str:
        """Return the current status line (host adapter)."""
        return self._status_message

    def set_status(self, message: str) -> None:
        """Replace the status line (host adapter)."""
        self._set_status(message)

    def suspend(self) -> Any:
        """Suspend the app for the terminal valve (host adapter)."""
        return self.app.suspend()  # type: ignore[attr-defined]

    def reload_projects(self) -> None:
        """Reload project records after init (host adapter)."""
        self.action_reload_projects()

    def report_init_outcome(self, initialized: bool) -> None:
        """Pane init does not wait on a Ready-stage outcome."""
        del initialized

    def recheck_after_terminal(self) -> bool:
        """Keep the pane terminal valve as a one-shot reload."""
        return False

    def _init_flow_controller(self) -> ProjectsInitFlowController:
        flow = getattr(self, "_init_flow", None)
        if flow is None:
            flow = ProjectsInitFlowController(self)  # type: ignore[arg-type]
            self._init_flow = flow
        return flow


def _is_init_eligible(record: ProjectRecordWire) -> bool:
    return record.state == "enabled" and not record.system_managed


def _partition_init_targets(
    records: Sequence[ProjectRecordWire],
) -> tuple[list[ProjectRecordWire], list[str]]:
    survivors: list[ProjectRecordWire] = []
    skipped: list[str] = []
    for record in records:
        if _is_init_eligible(record):
            survivors.append(record)
        else:
            skipped.append(effective_project_name(record))
    return survivors, skipped


__all__ = [
    "ProjectsPaneInitActionsMixin",
]
