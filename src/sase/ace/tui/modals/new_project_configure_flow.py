"""Configure preview and failed-resume hydration for the New Project wizard."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from sase import workspace_provider
from sase.ace.tui.util.pump_tasks import spawn_pump_free_task

from .new_project_configure import NewProjectConfigure
from .new_project_configure_facts import assemble_configure_facts
from .new_project_configure_model import (
    ConfigureDraft,
    IdentityCheck,
    check_identity,
    plan_configure_display,
)
from .new_project_resume import load_resume_context, recover_resume_intent
from .new_project_review import NewProjectReview
from .new_project_source import NewProjectSource
from .new_project_source_model import SourceRow
from .new_project_state import NewProjectStateMachine

if TYPE_CHECKING:
    from textual.app import App
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object

_TASKS = "_new_project_modal_tasks"


class NewProjectConfigureFlowMixin(_MixinBase):
    """Seed Configure from Source, preview locally, and hydrate failed resumes."""

    if TYPE_CHECKING:
        app: App[Any]
        is_mounted: bool
        _state: NewProjectStateMachine
        _provider_by_id: dict[str, Any]
        _inputs: dict[str, Any]
        _preview_generation: int
        _resume_generation: int
        _active_target: dict[str, object]
        _active_records: list[dict[str, object]]
        _observed_facts: dict[str, object]
        _local_plan: dict[str, object]
        _local_plan_draft: ConfigureDraft | None

        def notify(self, message: str, **kwargs: Any) -> None: ...
        def query_one(self, *args: Any, **kwargs: Any) -> Any: ...
        def _show_stage(self, stage: str) -> None: ...

    def _seed_configure_from_row(self, row: SourceRow, *, preserve: bool) -> None:
        """Fill target, records, and draft from *row* without scheduling work."""
        metadata = self._provider_by_id.get(self._state.workflow_type)
        parsed = row.data.get("parsed")
        if parsed is None:
            try:
                parsed = workspace_provider.parse_repo_ref(
                    self._state.workflow_type, row.ref
                )
            except Exception:
                parsed = None
        parsed_value = parsed if parsed is not None else None
        project_name = str(
            getattr(parsed_value, "project_name_base", "")
            or row.data.get("project_name_base")
            or row.data.get("name")
            or row.ref.rsplit("/", 1)[-1]
        )
        target: dict[str, object] = {
            "workflow_type": self._state.workflow_type,
            "provider_display": str(
                getattr(metadata, "display_name", "") or self._state.workflow_type
            ),
            "storage_policy": str(getattr(metadata, "sdd_storage_policy", "") or ""),
            "ref": row.ref,
            "identity_key": str(
                getattr(parsed_value, "identity_key", "")
                or row.data.get("identity_key")
                or row.ref
            ),
            "display": str(getattr(parsed_value, "display", "") or row.display),
            "host": str(
                getattr(parsed_value, "host", "") or row.data.get("host") or ""
            ),
            "owner": str(
                getattr(parsed_value, "owner", "") or row.data.get("owner") or ""
            ),
            "name": str(
                getattr(parsed_value, "name", "")
                or row.data.get("name")
                or project_name
            ),
            "web_url": str(
                getattr(parsed_value, "web_url", "") or row.data.get("web_url") or ""
            ),
            "checkout_dir": str(
                row.data.get("local_path")
                or row.data.get("path")
                or getattr(parsed_value, "checkout_dir", "")
                or ""
            ),
            "project_key_base": str(
                getattr(parsed_value, "project_key_base", "")
                or row.data.get("project_key_base")
                or ""
            ),
            "project_name_base": project_name,
        }
        if preserve and self._state.draft is not None:
            draft = self._state.draft
        else:
            draft = ConfigureDraft(name=project_name)
            self._state.set_draft(draft)
        inputs = self._inputs.get(self._state.workflow_type)
        self._active_target = target
        self._active_records = [
            dict(record) for record in (inputs.projects if inputs else [])
        ]
        self._observed_facts = self._assemble_observed_facts(row)
        self._local_plan = {}
        self._local_plan_draft = None

    def _assemble_observed_facts(self, row: SourceRow) -> dict[str, object]:
        source = self.query_one(NewProjectSource)
        probe = source.cached_probe(self._state.workflow_type, row.ref)
        return assemble_configure_facts(
            records=self._active_records,
            probe=probe,
            identity_key=str(self._active_target.get("identity_key") or ""),
            source_group=row.group,
            checkout_dir=str(self._active_target.get("checkout_dir") or ""),
        )

    def _prepare_configure(self, row: SourceRow, *, preserve: bool) -> None:
        """Seed Configure from a Source row without discarding its draft."""
        self._seed_configure_from_row(row, preserve=preserve)
        draft = self._state.draft or ConfigureDraft()
        self.query_one(NewProjectConfigure).set_source(
            row,
            draft,
            {},
            IdentityCheck("invalid", "Building the local plan…"),
        )
        self._schedule_local_preview()
        if "remote" not in self._observed_facts:
            self._schedule_initial_probe(row)

    def _schedule_initial_probe(self, row: SourceRow) -> None:
        """Populate the first card from an off-thread probe when Source has none."""
        generation = self._preview_generation
        row_id = row.row_id
        workflow_type = self._state.workflow_type
        ref = row.ref
        spawn_pump_free_task(
            self,
            self._observe_initial_probe(generation, row_id, workflow_type, ref),
            name=f"new-project-configure-probe:{ref}",
            registry_attr=_TASKS,
        )

    async def _observe_initial_probe(
        self,
        generation: int,
        row_id: str,
        workflow_type: str,
        ref: str,
    ) -> None:
        try:
            probe = await asyncio.to_thread(
                workspace_provider.probe_repo, workflow_type, ref
            )
        except Exception:
            probe = None
        selected = self.query_one(NewProjectSource).selected_row()
        if (
            not self.is_mounted
            or generation != self._preview_generation
            or self._state.stage != "configure"
            or self._state.workflow_type != workflow_type
            or selected is None
            or selected.row_id != row_id
        ):
            return
        if probe is not None:
            self.query_one(NewProjectSource).remember_probe(workflow_type, ref, probe)
        self._observed_facts = self._assemble_observed_facts(selected)
        self._schedule_local_preview()

    def _schedule_local_preview(self) -> None:
        """Build the local plan on a pump-free worker, newest draft wins."""
        if self._state.selected is None or self._state.draft is None:
            return
        self._preview_generation += 1
        generation = self._preview_generation
        row_id = self._state.selected.row_id
        workflow_type = self._state.workflow_type
        target = dict(self._active_target)
        facts = dict(self._observed_facts)
        draft = self._state.draft
        spawn_pump_free_task(
            self,
            self._build_local_preview(
                generation, row_id, workflow_type, target, facts, draft
            ),
            name=f"new-project-preview:{generation}",
            registry_attr=_TASKS,
        )

    async def _build_local_preview(
        self,
        generation: int,
        row_id: str,
        workflow_type: str,
        target: dict[str, object],
        facts: dict[str, object],
        draft: ConfigureDraft,
    ) -> None:
        try:
            document = await asyncio.to_thread(
                plan_configure_display, target, draft, facts
            )
            identity = check_identity(document)
        except Exception as error:
            document = {}
            identity = IdentityCheck("invalid", str(error) or type(error).__name__)
        selected = self.query_one(NewProjectSource).selected_row()
        if (
            not self.is_mounted
            or generation != self._preview_generation
            or self._state.stage != "configure"
            or self._state.workflow_type != workflow_type
            or selected is None
            or selected.row_id != row_id
            or self._state.selected is None
            or self._state.selected.row_id != row_id
            or self._state.draft != draft
        ):
            return
        self._local_plan = document
        self._local_plan_draft = draft
        self.query_one(NewProjectConfigure).apply_preview(document, identity)

    def _start_failed_resume(self, row: SourceRow) -> None:
        """Hydrate Review from a failed journal row without mutating yet."""
        self._seed_configure_from_row(row, preserve=False)
        self._resume_generation += 1
        generation = self._resume_generation
        row_id = row.row_id
        identity_key = str(self._active_target.get("identity_key") or "")
        workflow_type = self._state.workflow_type
        self._show_stage("review")
        review = self.query_one(NewProjectReview)
        review.show_loading("Recovering the previous add…")
        spawn_pump_free_task(
            self,
            self._hydrate_failed_resume(
                generation, row_id, identity_key, workflow_type, row
            ),
            name=f"new-project-resume:{identity_key}",
            registry_attr=_TASKS,
        )

    async def _hydrate_failed_resume(
        self,
        generation: int,
        row_id: str,
        identity_key: str,
        workflow_type: str,
        row: SourceRow,
    ) -> None:
        context = await asyncio.to_thread(load_resume_context, identity_key)
        selected = self.query_one(NewProjectSource).selected_row()
        if not self._resume_still_current(generation, row_id, workflow_type, selected):
            return
        plan = recover_resume_intent(
            row=row,
            workflow_type=workflow_type,
            context=context,
            seed_target=self._active_target,
        )
        self._state.set_draft(plan.draft)
        self._active_target = plan.target
        review = self.query_one(NewProjectReview)
        if plan.error:
            review.set_error(plan.error)
            return
        facts = dict(self._observed_facts)
        try:
            document = await asyncio.to_thread(
                plan_configure_display, plan.target, plan.draft, facts
            )
            identity = check_identity(document)
        except Exception as error:
            selected = self.query_one(NewProjectSource).selected_row()
            if self._resume_still_current(generation, row_id, workflow_type, selected):
                review.set_error(str(error) or type(error).__name__)
            return
        selected = self.query_one(NewProjectSource).selected_row()
        if not self._resume_still_current(generation, row_id, workflow_type, selected):
            return
        self._local_plan = document
        self._local_plan_draft = plan.draft
        self.query_one(NewProjectConfigure).set_source(
            row, plan.draft, document, identity
        )
        review.start_check(document, notice=plan.notice)

    def _resume_still_current(
        self,
        generation: int,
        row_id: str,
        workflow_type: str,
        selected: SourceRow | None,
    ) -> bool:
        return (
            self.is_mounted
            and generation == self._resume_generation
            and self._state.stage == "review"
            and self._state.workflow_type == workflow_type
            and selected is not None
            and selected.row_id == row_id
            and self._state.selected is not None
            and self._state.selected.row_id == row_id
        )


__all__ = ["NewProjectConfigureFlowMixin"]
