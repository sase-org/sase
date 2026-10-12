"""Provider tabs, inventory loading, and health for the New Project wizard."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import replace
from time import monotonic
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.widgets import Static

from sase import workspace_provider
from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.project_onboarding import (
    CandidateInputs,
    OwnerResult,
    Preferences,
    load_candidate_inputs,
    load_preferences,
)
from sase.workspace_provider import WorkflowMetadata

from ..widgets.panel_tab_strip import PanelTab, PanelTabStrip
from ._new_project_modal_shared import MODAL_TASKS
from .new_project_rendering import clean_source_text
from .new_project_source import NewProjectSource
from .new_project_source_model import (
    create_source_row,
    format_cache_age,
    health_chip_text,
)

if TYPE_CHECKING:
    from textual.app import App
    from textual.widget import Widget as _MixinBase

    from .new_project_state import NewProjectStateMachine
else:
    _MixinBase = object

_PROVIDER_ACCENTS = {"gh": "#87D7FF", "git": "#00D7AF"}


class NewProjectModalProvidersMixin(_MixinBase):
    """Own provider selection, cached loads, and create-support discovery."""

    if TYPE_CHECKING:
        app: App[Any]
        is_mounted: bool
        _create_support: dict[str, str]
        _create_support_loading: set[str]
        _current_workflow_type: str
        _disabled_providers: set[str]
        _inputs: dict[str, CandidateInputs]
        _inputs_arrived_at: dict[str, float]
        _loaded: set[str]
        _loading: set[str]
        _owner_jobs: set[asyncio.Task[tuple[str, CandidateInputs | None]]]
        _owner_semaphore: asyncio.Semaphore
        _pending_by_provider: dict[str, set[str]]
        _preferences: Preferences
        _provided_inputs: dict[str, CandidateInputs]
        _provider_by_id: dict[str, WorkflowMetadata]
        _providers: tuple[WorkflowMetadata, ...]
        _state: NewProjectStateMachine
        _tabs_disabled_snapshot: frozenset[str]

        def notify(self, message: str, **kwargs: Any) -> None: ...
        def query_one(self, *args: Any, **kwargs: Any) -> Any: ...
        def _persist_provider_selection(self, workflow_type: str) -> None: ...

    def action_previous_provider(self) -> None:
        """Select the previous provider tab."""
        self._cycle_provider(-1)

    def action_next_provider(self) -> None:
        """Select the next provider tab."""
        self._cycle_provider(1)

    def _cycle_provider(self, offset: int) -> None:
        if self._state.stage != "source":
            return
        enabled = [
            item
            for item in self._providers
            if item.workflow_type not in self._disabled_providers
        ]
        if not enabled:
            return
        current = self._state.workflow_type
        try:
            index = next(
                i for i, item in enumerate(enabled) if item.workflow_type == current
            )
        except StopIteration:
            index = 0
        target = enabled[(index + offset) % len(enabled)]
        self.select_provider(target.workflow_type)

    def action_refresh_provider(self) -> None:
        """Revalidate every owner for the selected provider, bypassing cache."""
        workflow_type = self._state.workflow_type
        if workflow_type:
            if workflow_type in self._loading:
                return
            self._loading.add(workflow_type)
            self._maybe_discover_create_support(workflow_type, force=True)
            spawn_pump_free_task(
                self,
                self._refresh_all_owners(workflow_type, force=True),
                name=f"new-project-refresh:{workflow_type}",
                registry_attr=MODAL_TASKS,
            )

    async def _bootstrap(self) -> None:
        metadata, preferences = await asyncio.gather(
            asyncio.to_thread(workspace_provider.get_all_workflow_metadata),
            asyncio.to_thread(load_preferences),
        )
        if not self.is_mounted:
            return
        self._configure_providers(tuple(metadata), preferences, {})

    def _configure_providers(
        self,
        metadata: Sequence[WorkflowMetadata],
        preferences: Preferences,
        inputs: Mapping[str, CandidateInputs],
    ) -> None:
        self._providers = tuple(metadata)
        self._provider_by_id = {item.workflow_type: item for item in self._providers}
        self._preferences = preferences
        self._inputs.update(inputs)
        self._loaded.update(inputs)
        tabs = tuple(
            PanelTab(
                item.workflow_type,
                clean_source_text(item.display_name or item.workflow_type),
                _PROVIDER_ACCENTS.get(item.workflow_type, "#AF87D7"),
                compact_label=clean_source_text(item.workflow_type),
            )
            for item in self._providers
        )
        selected = (
            preferences.last_provider
            if preferences.last_provider in self._provider_by_id
            else self._current_workflow_type
            if self._current_workflow_type in self._provider_by_id
            else self._providers[0].workflow_type
            if self._providers
            else None
        )
        strip = self.query_one("#new-project-providers", PanelTabStrip)
        strip.set_tabs(tabs, active_tab=selected)
        self._state.workflow_type = selected or ""
        source = self.query_one(NewProjectSource)
        source.set_workflow_type(selected or "")
        source.set_inputs(self._inputs.get(selected or ""))
        if selected is not None:
            self._maybe_discover_create_support(selected)
        if selected is None:
            self.query_one("#new-project-health", Static).update(
                "No workspace providers are available."
            )
            return
        source.set_refresh_callback(self.action_refresh_provider)
        self._update_health(selected)
        self._sync_disabled_tabs()
        if selected in self._provided_inputs:
            return
        if selected not in self._loaded:
            self._start_provider_load(selected)

    def select_provider(self, workflow_type: str) -> None:
        """Switch the selected provider tab, preserving the Source filter."""
        if self._state.stage != "source":
            return
        if workflow_type not in self._provider_by_id:
            return
        if workflow_type in self._disabled_providers:
            return
        self._state.workflow_type = workflow_type
        self.query_one("#new-project-providers", PanelTabStrip).set_active_tab(
            workflow_type
        )
        source = self.query_one(NewProjectSource)
        source.set_workflow_type(workflow_type)
        source.set_create_row(None)
        source.set_inputs(
            self._inputs.get(workflow_type),
            pending_owners=frozenset(
                self._pending_by_provider.get(workflow_type, set())
            ),
        )
        self._update_health(workflow_type)
        self._start_provider_load(workflow_type)
        self._maybe_discover_create_support(workflow_type)
        self._persist_provider_selection(workflow_type)

    def _start_provider_load(self, workflow_type: str) -> None:
        if workflow_type in self._loaded or workflow_type in self._loading:
            return
        self._loading.add(workflow_type)
        spawn_pump_free_task(
            self,
            self._load_provider(workflow_type),
            name=f"new-project-load:{workflow_type}",
            registry_attr=MODAL_TASKS,
        )

    def _maybe_discover_create_support(
        self, workflow_type: str, *, force: bool = False
    ) -> None:
        """Describe the provider creation form off-thread, once per provider.

        A non-None form pins the first Source Create row; None (or a
        failure) leaves the ordinary add-only Source list.
        """
        if not workflow_type:
            return
        if workflow_type in self._create_support_loading:
            return
        if not force and workflow_type in self._create_support:
            self._apply_create_support(workflow_type)
            return
        if force:
            self._create_support.pop(workflow_type, None)
        self._create_support_loading.add(workflow_type)
        spawn_pump_free_task(
            self,
            self._observe_create_support(workflow_type),
            name=f"new-project-create-support:{workflow_type}",
            registry_attr=MODAL_TASKS,
        )

    async def _observe_create_support(self, workflow_type: str) -> None:
        inputs = self._inputs.get(workflow_type)
        namespace = ""
        if inputs is not None:
            namespace = inputs.account or next(
                (owner.name for owner in inputs.owners if owner.name), ""
            )
        try:
            form = await asyncio.to_thread(
                workspace_provider.describe_repo_creation, workflow_type, namespace
            )
        except Exception:
            form = None
        if not self.is_mounted:
            self._create_support_loading.discard(workflow_type)
            return
        self._create_support_loading.discard(workflow_type)
        self._create_support[workflow_type] = (
            "supported" if form is not None else "unsupported"
        )
        self._apply_create_support(workflow_type)

    def _apply_create_support(self, workflow_type: str) -> None:
        """Pin or clear the Source Create row from cached discovery."""
        if not self.is_mounted or workflow_type != self._state.workflow_type:
            return
        if self._create_support.get(workflow_type) != "supported":
            self.query_one(NewProjectSource).set_create_row(None)
            return
        metadata = self._provider_by_id.get(workflow_type)
        display = str(getattr(metadata, "display_name", "") or workflow_type)
        self.query_one(NewProjectSource).set_create_row(
            create_source_row(display, workflow_type)
        )

    async def _load_provider(self, workflow_type: str) -> None:
        try:
            inputs = await asyncio.to_thread(
                load_candidate_inputs, workflow_type, cache_only=True
            )
        except Exception as error:
            inputs = CandidateInputs(workflow_type, workflow_type, "")
            inputs.owners = [
                OwnerResult(name="provider", status="error", message=str(error))
            ]
        self._inputs[workflow_type] = inputs
        self._loaded.add(workflow_type)
        pending = {owner.name for owner in inputs.owners}
        self._pending_by_provider[workflow_type] = pending
        self._show_inputs_if_selected(workflow_type)
        await self._refresh_owner_set(workflow_type, inputs, pending, force=False)
        self._loading.discard(workflow_type)
        self._update_health(workflow_type)

    async def _refresh_all_owners(self, workflow_type: str, *, force: bool) -> None:
        inputs = self._inputs.get(workflow_type)
        if inputs is None:
            self._loading.discard(workflow_type)
            self._start_provider_load(workflow_type)
            return
        pending = {owner.name for owner in inputs.owners}
        self._pending_by_provider[workflow_type] = pending
        self._show_inputs_if_selected(workflow_type)
        await self._refresh_owner_set(workflow_type, inputs, pending, force=force)
        self._loading.discard(workflow_type)
        self._update_health(workflow_type)

    async def _refresh_owner_set(
        self,
        workflow_type: str,
        inputs: CandidateInputs,
        pending: set[str],
        *,
        force: bool,
    ) -> None:
        async def refresh_owner(owner_name: str) -> tuple[str, CandidateInputs | None]:
            async with self._owner_semaphore:
                try:
                    updated = await asyncio.to_thread(
                        load_candidate_inputs,
                        workflow_type,
                        cache_only=False,
                        refresh=force,
                        namespaces=[owner_name],
                    )
                    return owner_name, updated
                except Exception:
                    return owner_name, None

        jobs = [asyncio.create_task(refresh_owner(name)) for name in tuple(pending)]
        for job in jobs:
            self._owner_jobs.add(job)
            job.add_done_callback(self._owner_jobs.discard)
        try:
            for completed in asyncio.as_completed(jobs):
                try:
                    owner_name, updated = await completed
                except asyncio.CancelledError:
                    break
                pending.discard(owner_name)
                current = self._inputs.get(workflow_type, inputs)
                if updated is not None:
                    fresh_owner = next(
                        (owner for owner in updated.owners if owner.name == owner_name),
                        None,
                    )
                    if fresh_owner is not None:
                        owners = [
                            fresh_owner if owner.name == owner_name else owner
                            for owner in current.owners
                        ]
                        if not any(
                            owner.name == owner_name for owner in current.owners
                        ):
                            owners.append(fresh_owner)
                        current = replace(
                            current,
                            owners=owners,
                            remote=[
                                entry for owner in owners for entry in owner.entries
                            ],
                        )
                        self._inputs[workflow_type] = current
                self._pending_by_provider[workflow_type] = pending
                if self.is_mounted:
                    self._show_inputs_if_selected(workflow_type)
                    self._update_health(workflow_type)
        finally:
            for job in jobs:
                self._owner_jobs.discard(job)
        if self.is_mounted:
            self._maybe_discover_create_support(workflow_type)
            self._sync_disabled_tabs()

    def _show_inputs_if_selected(self, workflow_type: str) -> None:
        if workflow_type != self._state.workflow_type or not self.is_mounted:
            return
        self._inputs_arrived_at[workflow_type] = monotonic()
        self.query_one(NewProjectSource).set_inputs(
            self._inputs.get(workflow_type),
            pending_owners=frozenset(
                self._pending_by_provider.get(workflow_type, set())
            ),
        )

    def _cache_age(self, workflow_type: str) -> str:
        """Format the age of the displayed candidate inputs for the chip."""
        arrived = self._inputs_arrived_at.get(workflow_type)
        if arrived is None:
            return ""
        return format_cache_age(monotonic() - arrived)

    def _update_health(self, workflow_type: str) -> None:
        if workflow_type != self._state.workflow_type:
            return
        inputs = self._inputs.get(workflow_type)
        text = health_chip_text(
            inputs,
            workflow_type=workflow_type,
            pending_owners=frozenset(
                self._pending_by_provider.get(workflow_type, set())
            ),
            cache_age=self._cache_age(workflow_type),
        )
        self.query_one("#new-project-health", Static).update(
            Text(
                text,
                style="#00D7AF"
                if text.startswith("✓")
                else "#FFAF5F"
                if text.startswith("⚠")
                else "#FF6666"
                if text.startswith("✗")
                else "dim",
            )
        )

    def _sync_disabled_tabs(self) -> None:
        """Disable provider tabs whose tool is missing, and step off them."""
        disabled = {
            workflow_type
            for workflow_type, inputs in self._inputs.items()
            if inputs.owners
            and all(
                owner.status == "error" and owner.error_kind == "tool_missing"
                for owner in inputs.owners
            )
        }
        self._disabled_providers = disabled
        if frozenset(disabled) == self._tabs_disabled_snapshot:
            return
        self._tabs_disabled_snapshot = frozenset(disabled)
        strip = self.query_one("#new-project-providers", PanelTabStrip)
        strip.set_tabs(
            tuple(
                PanelTab(
                    item.workflow_type,
                    clean_source_text(item.display_name or item.workflow_type),
                    _PROVIDER_ACCENTS.get(item.workflow_type, "#AF87D7"),
                    compact_label=clean_source_text(item.workflow_type),
                    disabled=item.workflow_type in disabled,
                )
                for item in self._providers
            ),
            active_tab=self._state.workflow_type,
        )
        if self._state.workflow_type in disabled:
            fallback = next(
                (
                    item.workflow_type
                    for item in self._providers
                    if item.workflow_type not in disabled
                ),
                "",
            )
            if fallback:
                self.select_provider(fallback)


__all__ = ["NewProjectModalProvidersMixin"]
