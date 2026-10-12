"""Shell chrome for the New Project wizard.

Compose the frame, mount the Source stage, and switch stages.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import ContentSwitcher, Static

from sase.ace.tui.util.pump_tasks import cancel_pump_free_tasks, spawn_pump_free_task
from sase.project_onboarding import (
    Preferences,
    preferences_path,
    save_preferences,
)

from ..widgets.panel_tab_strip import PanelTabStrip
from ._new_project_modal_shared import MODAL_TASKS
from .new_project_configure import NewProjectConfigure
from .new_project_create import NewProjectCreateConfigure
from .new_project_failed import NewProjectFailed
from .new_project_progress import NewProjectProgress
from .new_project_ready import NewProjectReady
from .new_project_rendering import render_stepper
from .new_project_review import NewProjectReview
from .new_project_source import NewProjectSource

if TYPE_CHECKING:
    from textual.app import App
    from textual.widget import Widget as _MixinBase

    from .new_project_state import NewProjectStateMachine
else:
    _MixinBase = object


class NewProjectModalShellMixin(_MixinBase):
    """Compose the wizard frame and drive stage chrome."""

    if TYPE_CHECKING:
        app: App[Any]
        is_mounted: bool
        _preferences: Preferences
        _provided_inputs: dict[str, Any]
        _provided_metadata: Any
        _provided_preferences: Preferences | None
        _state: NewProjectStateMachine

        def notify(self, message: str, **kwargs: Any) -> None: ...
        def query_one(self, *args: Any, **kwargs: Any) -> Any: ...
        def action_refresh_provider(self) -> None: ...
        def _bootstrap(self) -> Any: ...
        def _configure_providers(self, *args: Any, **kwargs: Any) -> None: ...
        def _update_apply_chrome(self, stage: str) -> None: ...

    def compose(self) -> ComposeResult:
        with Container(id="new-project-frame"):
            yield Static("✚ New Project", id="new-project-title")
            yield Static(render_stepper("source"), id="new-project-stepper")
            with Horizontal(id="new-project-provider-row"):
                yield PanelTabStrip(
                    (), None, id="new-project-providers", fill_width=False
                )
                yield Static("Loading providers…", id="new-project-health")
            with ContentSwitcher(
                initial="new-project-source-stage", id="new-project-stages"
            ):
                yield NewProjectSource(id="new-project-source-stage")
                yield NewProjectConfigure(id="new-project-configure-stage")
                yield NewProjectCreateConfigure(id="new-project-create-stage")
                yield NewProjectReview(id="new-project-review-stage")
                yield NewProjectProgress(id="new-project-progress-stage")
                yield NewProjectReady(id="new-project-ready-stage")
                yield NewProjectFailed(id="new-project-failed-stage")
            yield Static(
                "⏎ choose · n new · [ ] provider · / filter · f forks · . all · R refresh · t provider login · esc close",
                id="new-project-hints",
            )

    def on_mount(self) -> None:
        source = self.query_one(NewProjectSource)
        source.set_refresh_callback(self.action_refresh_provider)
        if self._provided_metadata is not None:
            self._configure_providers(
                self._provided_metadata,
                self._provided_preferences or Preferences(),
                self._provided_inputs,
            )
            return
        spawn_pump_free_task(
            self,
            self._bootstrap(),
            name="new-project-bootstrap",
            registry_attr=MODAL_TASKS,
        )

    def on_unmount(self) -> None:
        cancel_pump_free_tasks(self)

    def _persist_provider_selection(self, workflow_type: str) -> None:
        self._preferences.last_provider = workflow_type
        spawn_pump_free_task(
            self,
            self._save_preferences(),
            name="new-project-save-provider-preference",
            registry_attr=MODAL_TASKS,
        )

    async def _save_preferences(self) -> None:
        try:
            await asyncio.to_thread(save_preferences, self._preferences)
        except Exception as error:
            self.notify(
                f"Could not save {preferences_path().name}: {error}",
                severity="warning",
            )

    def _show_stage(self, stage: str) -> None:
        stage_ids = {
            "source": "new-project-source-stage",
            "configure": "new-project-configure-stage",
            "create-configure": "new-project-create-stage",
            "review": "new-project-review-stage",
            "progress": "new-project-progress-stage",
            "ready": "new-project-ready-stage",
            "failed": "new-project-failed-stage",
        }
        stepper_stage = "configure" if stage == "create-configure" else stage
        self.query_one("#new-project-stepper", Static).update(
            render_stepper(stepper_stage)
        )
        self.query_one("#new-project-stages", ContentSwitcher).current = stage_ids.get(
            stage, stage_ids["source"]
        )
        self._update_apply_chrome(stage)


__all__ = ["NewProjectModalShellMixin"]
